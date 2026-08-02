"""API surface behaviors that aren't money or auth.

Run from backend/:  python -m pytest -q tests/test_api.py
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Match the other test modules: first import wins for the singletons.
os.environ.setdefault("SAMVARA_DB", os.path.join(tempfile.mkdtemp(), "test-api.db"))
os.environ.setdefault("AUTH_MODE", "token")
os.environ.setdefault("API_TOKEN", "static-cron-token")
os.environ.setdefault("AUTH_EMAIL", "owner@example.com")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app import db, main, stripe_billing  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.store import store  # noqa: E402

from _helpers import signin  # noqa: E402

client = TestClient(app)
TEST_EMAIL = "api-tests@example.com"
# settings.signup_mode is a frozen singleton for the whole pytest session
# (whichever test module python imports first locks in the env it read) — so
# this file can't rely on SIGNUP_MODE=open actually being in effect (another
# module may have already frozen "invite"). Explicitly inviting is correct
# under either mode.
store.add_invite(TEST_EMAIL, note=None)
HDR = signin(client, TEST_EMAIL)
USER_ID = store.get_user_by_email(TEST_EMAIL)["id"]


@pytest.fixture(autouse=True)
def _clean():
    with store.lock, store.engine.begin() as conn:
        conn.execute(delete(db.commitments).where(db.commitments.c.user_id == USER_ID))
        conn.execute(delete(db.metric_days).where(db.metric_days.c.user_id == USER_ID))
    yield


def mk(name: str, days: int) -> str:
    r = client.post("/v1/commitments", headers=HDR,
                    json={"name": name, "base_days": days, "base_stake": 5.0})
    assert r.status_code == 200
    return r.json()["id"]


# ── daily metrics (the Data tab) ─────────────────────────────────────────────
def test_metrics_vocabulary_and_empty_series():
    out = client.get("/v1/metrics", headers=HDR).json()
    keys = [m["key"] for m in out["metrics"]]
    assert keys == ["porn_viewed", "sexual_content_viewed", "masturbation",
                    "gaze_goal_set", "gaze_goal_broken"]
    # Ratios apply to the first three only.
    assert [m["key"] for m in out["metrics"] if m["ratio"]] == keys[:3]
    assert out["series"] == {}
    assert out["today"] == main.metrics_today(settings.metrics_tz)


def test_bump_increments_today_and_decrement_floors_at_zero():
    r = client.post("/v1/metrics/masturbation/bump", headers=HDR, json={"delta": 1})
    today = r.json()["today"]
    assert r.json()["series"]["masturbation"][today] == 1
    client.post("/v1/metrics/masturbation/bump", headers=HDR, json={"delta": 1})
    r = client.post("/v1/metrics/masturbation/bump", headers=HDR, json={"delta": -1})
    assert r.json()["series"]["masturbation"][today] == 1
    # Two more decrements: 0, then floored at 0 — never negative.
    client.post("/v1/metrics/masturbation/bump", headers=HDR, json={"delta": -1})
    r = client.post("/v1/metrics/masturbation/bump", headers=HDR, json={"delta": -1})
    assert r.json()["series"]["masturbation"][today] == 0


def test_bump_rejects_unknown_metric_and_bad_delta():
    assert client.post("/v1/metrics/nonsense/bump", headers=HDR,
                       json={"delta": 1}).status_code == 404
    assert client.post("/v1/metrics/masturbation/bump", headers=HDR,
                       json={"delta": 0}).status_code == 400
    assert client.post("/v1/metrics/masturbation/bump", headers=HDR,
                       json={"delta": 5}).status_code == 400
    assert client.get("/v1/metrics", headers=HDR).json()["series"] == {}


def test_metrics_day_boundary_is_new_york():
    import datetime as dt
    utc = dt.timezone.utc
    # 23:30 EDT on July 3 is 03:30 UTC July 4 — still July 3 in New York.
    assert main.metrics_today("America/New_York", dt.datetime(2026, 7, 4, 3, 30, tzinfo=utc)) == "2026-07-03"
    assert main.metrics_today("America/New_York", dt.datetime(2026, 7, 4, 4, 30, tzinfo=utc)) == "2026-07-04"
    # Winter (EST, UTC-5): the boundary moves an hour.
    assert main.metrics_today("America/New_York", dt.datetime(2026, 1, 10, 4, 30, tzinfo=utc)) == "2026-01-09"


def test_metrics_require_auth():
    assert client.get("/v1/metrics").status_code == 401
    assert client.post("/v1/metrics/masturbation/bump",
                       json={"delta": 1}).status_code == 401


def test_static_token_no_longer_works_on_user_routes():
    # The old single-tenant god-token accepted this everywhere; multi-tenant,
    # there's no "current user" it can resolve to, so it must be rejected here
    # even though it's still valid on /v1/tick (see test_money.py).
    cron_hdr = {"Authorization": f"Bearer {settings.api_token}"}
    assert client.get("/v1/commitments", headers=cron_hdr).status_code == 401


def test_create_survives_an_id_collision(monkeypatch):
    from app import ratchet
    taken = mk("First", days=3)
    real_new_id = ratchet.new_id
    ids = iter([taken, real_new_id()])  # collide once, then a fresh id
    monkeypatch.setattr(ratchet, "new_id", lambda: next(ids))
    r = client.post("/v1/commitments", headers=HDR,
                    json={"name": "Second", "base_days": 1, "base_stake": 5.0})
    assert r.status_code == 200
    assert r.json()["id"] != taken


def test_commitments_listed_closest_deadline_first():
    # Created in the opposite order to their deadlines, so insertion order
    # (the old behavior) would fail this.
    far = mk("Far", days=9)
    near = mk("Near", days=1)
    mid = mk("Mid", days=4)
    names = [c["name"] for c in client.get("/v1/commitments", headers=HDR).json()]
    assert names == ["Near", "Mid", "Far"]
    # An overdue/parked rung has the oldest due date, so it surfaces on top.
    cm = store.get_commitment(USER_ID, near)
    cm["current_rung"]["due"] = "2000-01-01T00:00:00.000Z"
    store.update_commitment(USER_ID, cm)
    names = [c["name"] for c in client.get("/v1/commitments", headers=HDR).json()]
    assert names[0] == "Near"
    assert far and mid  # ids used; silence linters


# ── multi-tenant isolation ───────────────────────────────────────────────────
def test_users_cannot_see_or_touch_each_others_commitments():
    store.add_invite("api-tests-other@example.com", note=None)
    other_hdr = signin(client, "api-tests-other@example.com")
    mine = mk("Mine", days=2)
    r = client.post("/v1/commitments", headers=other_hdr,
                    json={"name": "Theirs", "base_days": 2, "base_stake": 5.0})
    theirs = r.json()["id"]

    mine_names = [c["name"] for c in client.get("/v1/commitments", headers=HDR).json()]
    their_names = [c["name"] for c in client.get("/v1/commitments", headers=other_hdr).json()]
    assert "Theirs" not in mine_names
    assert "Mine" not in their_names

    assert client.get(f"/v1/commitments/{theirs}", headers=HDR).status_code == 404
    assert client.get(f"/v1/commitments/{mine}", headers=other_hdr).status_code == 404
    assert client.post(f"/v1/commitments/{mine}/confirm-clean", headers=other_hdr).status_code == 404

    # Clean up the second user's data so it doesn't leak into other tests.
    with store.lock, store.engine.begin() as conn:
        other_id = store.get_user_by_email("api-tests-other@example.com")["id"]
        conn.execute(delete(db.commitments).where(db.commitments.c.user_id == other_id))


def test_settings_are_per_user():
    client.patch("/v1/settings", headers=HDR, json={"recipient": "Mine"})
    store.add_invite("api-tests-settings@example.com", note=None)
    other_hdr = signin(client, "api-tests-settings@example.com")
    other_settings = client.get("/v1/settings", headers=other_hdr).json()
    assert other_settings["recipient"] != "Mine"
    mine = client.get("/v1/settings", headers=HDR).json()
    assert mine["recipient"] == "Mine"


# ── charge provider: 'samvara' (Stripe) is the only public choice ───────────
def test_default_charge_provider_is_samvara():
    assert client.get("/v1/settings", headers=HDR).json()["chargeProvider"] == "samvara"
    status_body = client.get("/v1/billing/status", headers=HDR).json()
    assert status_body["provider"] == "samvara"
    assert status_body["canUseBeeminder"] is False


def test_non_owner_cannot_switch_to_beeminder():
    r = client.patch("/v1/settings", headers=HDR, json={"chargeProvider": "beeminder"})
    assert r.status_code == 403
    assert client.get("/v1/settings", headers=HDR).json()["chargeProvider"] == "samvara"


def test_unknown_charge_provider_is_rejected():
    r = client.patch("/v1/settings", headers=HDR, json={"chargeProvider": "paypal"})
    assert r.status_code == 400


def test_owner_can_switch_to_beeminder():
    store.add_invite("owner@example.com", note=None)
    owner_hdr = signin(client, "owner@example.com")
    r = client.patch("/v1/settings", headers=owner_hdr, json={"chargeProvider": "beeminder"})
    assert r.status_code == 200
    assert r.json()["chargeProvider"] == "beeminder"
    status_body = client.get("/v1/billing/status", headers=owner_hdr).json()
    assert status_body["provider"] == "beeminder"
    assert status_body["canUseBeeminder"] is True
    # Clean up: don't leak a live 'beeminder' selection into other test modules.
    client.patch("/v1/settings", headers=owner_hdr, json={"chargeProvider": "samvara"})


# ── billing endpoints: card setup/save never trusts a client-supplied pm id ──
def test_setup_intent_creates_customer_and_returns_client_secret(monkeypatch):
    async def fake_create_customer(email, user_id):
        return "cus_fake"

    async def fake_create_setup_intent(customer_id):
        assert customer_id == "cus_fake"
        return {"clientSecret": "seti_secret", "id": "seti_1"}

    monkeypatch.setattr(stripe_billing, "create_customer", fake_create_customer)
    monkeypatch.setattr(stripe_billing, "create_setup_intent", fake_create_setup_intent)
    r = client.post("/v1/billing/setup-intent", headers=HDR)
    assert r.status_code == 200
    assert r.json()["clientSecret"] == "seti_secret"
    assert store.get_user_by_email(TEST_EMAIL)["stripe_customer_id"] == "cus_fake"


def test_payment_method_resolves_pm_id_server_side_not_from_client(monkeypatch):
    """The client only ever reports a SetupIntent id; the server looks up
    the actual pm_... id itself rather than trusting anything the client
    could claim in the request body (there's no paymentMethodId field to
    even send)."""
    async def fake_lookup(setup_intent_id):
        assert setup_intent_id == "seti_2"
        return "pm_resolved"

    async def fake_get_details(pm_id):
        return {"brand": "visa", "last4": "4242"}

    calls = []

    async def fake_set_default(customer_id, pm_id):
        calls.append((customer_id, pm_id))

    monkeypatch.setattr(stripe_billing, "get_setup_intent_payment_method", fake_lookup)
    monkeypatch.setattr(stripe_billing, "set_default_payment_method", fake_set_default)
    monkeypatch.setattr(stripe_billing, "get_payment_method_details", fake_get_details)
    with store.lock, store.engine.begin() as conn:
        conn.execute(
            db.users.update().where(db.users.c.id == USER_ID).values(stripe_customer_id="cus_existing")
        )
    r = client.post("/v1/billing/payment-method", headers=HDR, json={"setupIntentId": "seti_2"})
    assert r.status_code == 200
    assert r.json()["stripePaymentMethodId"] == "pm_resolved"
    assert calls == [("cus_existing", "pm_resolved")]

    # Reset so the next test (no customer on file) starts from a clean slate.
    with store.lock, store.engine.begin() as conn:
        conn.execute(
            db.users.update().where(db.users.c.id == USER_ID).values(stripe_customer_id=None)
        )


def test_payment_method_without_customer_is_409():
    r = client.post("/v1/billing/payment-method", headers=HDR, json={"setupIntentId": "seti_x"})
    assert r.status_code == 409


# ── refund endpoint ──────────────────────────────────────────────────────────
def test_refund_charge_returns_refund_id(monkeypatch):
    async def fake_refund(charge_id, amount=None):
        assert charge_id == "pi_test_123"
        return "ref_test_456"

    monkeypatch.setattr(stripe_billing, "refund_charge", fake_refund)
    r = client.delete("/v1/billing/charges/pi_test_123/refund", headers=HDR)
    assert r.status_code == 200
    assert r.json()["refundId"] == "ref_test_456"


def test_refund_partial_amount(monkeypatch):
    received_args = {}

    async def fake_refund(charge_id, amount=None):
        received_args["charge_id"] = charge_id
        received_args["amount"] = amount
        return "ref_test_789"

    monkeypatch.setattr(stripe_billing, "refund_charge", fake_refund)
    r = client.delete("/v1/billing/charges/pi_test_xyz/refund?amount=10.50", headers=HDR)
    assert r.status_code == 200
    assert received_args["charge_id"] == "pi_test_xyz"
    assert received_args["amount"] == 10.50


# ── admin charge management ──────────────────────────────────────────────────
def test_admin_list_charges_requires_admin():
    r = client.get("/v1/admin/charges", headers=HDR)
    assert r.status_code == 403  # Regular user forbidden (not admin)


def test_admin_list_charges_with_token():
    admin_hdr = {"Authorization": f"Bearer {settings.api_token}"}
    r = client.get("/v1/admin/charges", headers=admin_hdr)
    assert r.status_code == 200
    assert "charges" in r.json()
    assert isinstance(r.json()["charges"], list)


def test_admin_get_charge_not_found():
    admin_hdr = {"Authorization": f"Bearer {settings.api_token}"}
    r = client.get("/v1/admin/charges/nonexistent_id", headers=admin_hdr)
    assert r.status_code == 404


def test_admin_refund_charge_requires_admin():
    r = client.delete("/v1/admin/charges/pi_123/refund", headers=HDR)
    assert r.status_code == 403  # Regular user forbidden (not admin)


def test_admin_refund_charge_not_found():
    admin_hdr = {"Authorization": f"Bearer {settings.api_token}"}
    r = client.delete("/v1/admin/charges/nonexistent_id/refund", headers=admin_hdr)
    assert r.status_code == 404


# ── request-id middleware ────────────────────────────────────────────────────
def test_request_id_echoed_when_client_supplies_one():
    r = client.get("/v1/health", headers={"X-Request-Id": "client-supplied-123"})
    assert r.headers["x-request-id"] == "client-supplied-123"


def test_request_id_generated_when_absent():
    r = client.get("/v1/health")
    rid = r.headers.get("x-request-id")
    assert rid and rid != "-"


def test_request_id_differs_across_requests():
    a = client.get("/v1/health").headers["x-request-id"]
    b = client.get("/v1/health").headers["x-request-id"]
    assert a != b


# ── readiness ─────────────────────────────────────────────────────────────────
def test_readiness_ok_when_db_reachable():
    r = client.get("/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {"db": True}}


def test_readiness_503_when_db_unreachable(monkeypatch):
    monkeypatch.setattr(store, "ping", lambda: False)
    r = client.get("/v1/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable", "checks": {"db": False}}


def test_readiness_requires_no_auth():
    # No Authorization header at all — must not 401.
    r = client.get("/v1/health/ready", headers={})
    assert r.status_code == 200
