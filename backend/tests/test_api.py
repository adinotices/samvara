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

from app import db, main  # noqa: E402
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
