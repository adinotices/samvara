"""Coach role: sign-in confined to one address, sessions confined to the coach
routes, shared-goal visibility, pass/fail verdicts, and the charge path.

beeminder.charge is faked in-process, so no network and no money.

Run from backend/:  python -m pytest -q tests/test_coach.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Match the other suites: whichever module pytest imports first creates the
# settings/store singletons, so the values must agree for a whole-suite run.
os.environ.setdefault("SAMVARA_DB", os.path.join(tempfile.mkdtemp(), "test-coach.db"))
os.environ.setdefault("AUTH_MODE", "token")
os.environ.setdefault("API_TOKEN", "static-cron-token")
os.environ.setdefault("AUTH_EMAIL", "owner@example.com")

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, beeminder, main, ratchet  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.store import store  # noqa: E402

client = TestClient(app)
OWNER = {"Authorization": f"Bearer {settings.api_token}"}
COACH_EMAIL = "coach@example.com"
SENT: list[tuple[str, str]] = []
CHARGES: list[tuple[float, str]] = []


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    SENT.clear()
    CHARGES.clear()

    async def fake_send(email: str, code: str, subject: str = "") -> None:
        SENT.append((email, code))

    async def fake_charge(amount: float, note: str) -> beeminder.ChargeResult:
        CHARGES.append((amount, note))
        return beeminder.ChargeResult(charged=True, amount=amount, note=note,
                                      beeminder_id="fake", dryrun=False)

    monkeypatch.setattr(auth, "send_otp_email", fake_send)
    monkeypatch.setattr(beeminder, "charge", fake_charge)
    monkeypatch.setattr(main, "_charge_lock", asyncio.Lock())
    # The real coach address is hard-wired by hash; tests use a stand-in.
    monkeypatch.setattr(settings, "coach_email_sha256", auth.sha256(COACH_EMAIL))
    monkeypatch.setattr(settings, "lapse_debounce_s", 0.0)
    monkeypatch.setattr(settings, "max_charge", 50.0)
    with store.lock, store._conn:
        store._conn.execute("DELETE FROM commitments")
        store._conn.execute("DELETE FROM otp_codes")
    store.update_settings({"totalCharged": 0})
    yield


def coach_login(email: str = COACH_EMAIL) -> dict[str, str]:
    assert client.post("/v1/coach/auth/send-code", json={"email": email}).status_code == 204
    sent_email, code = SENT[-1]
    r = client.post("/v1/coach/auth/verify-code", json={"email": sent_email, "code": code})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def mk(owner=True, days=3, stake=5.0, shared=True) -> dict:
    r = client.post("/v1/commitments", headers=OWNER,
                    json={"name": "Goal", "base_days": days, "base_stake": stake})
    assert r.status_code == 200
    cm = r.json()
    if shared:
        r = client.post(f"/v1/commitments/{cm['id']}/coach", headers=OWNER, json={"shared": True})
        assert r.status_code == 200
        cm = r.json()
    return cm


def make_due(cid: str, past_grace: bool = False) -> None:
    cm = store.get_commitment(cid)
    r = cm["current_rung"]
    due = ratchet.now_ms() - ratchet.HOUR_MS - (settings.grace_ms if past_grace else 0)
    r["start"] = ratchet.iso_ms(due - r["days"] * ratchet.DAY_MS)
    r["due"] = ratchet.iso_ms(due)
    store.update_commitment(cm)


# ── sign-in ──────────────────────────────────────────────────────────────────
def test_only_the_coach_address_gets_a_code():
    for email in ("owner@example.com", "someone@example.com", "coach@example.org"):
        assert client.post("/v1/coach/auth/send-code", json={"email": email}).status_code == 204
    assert SENT == []
    client.post("/v1/coach/auth/send-code", json={"email": "  Coach@Example.com "})
    assert [e for e, _ in SENT] == [COACH_EMAIL]


def test_owner_code_cannot_open_a_coach_session():
    client.post("/v1/auth/send-code", json={"email": "owner@example.com"})
    _, code = SENT[-1]
    r = client.post("/v1/coach/auth/verify-code", json={"email": "owner@example.com", "code": code})
    assert r.status_code == 401


def test_coach_session_is_confined_to_coach_routes():
    hdr = coach_login()
    assert client.get("/v1/coach/goals", headers=hdr).status_code == 200
    for method, path in [("GET", "/v1/commitments"), ("GET", "/v1/settings"),
                         ("GET", "/v1/metrics"), ("POST", "/v1/tick")]:
        assert client.request(method, path, headers=hdr).status_code == 401, path
    # And /health doesn't reveal the config to a coach.
    assert "beeminder_dryrun" not in client.get("/v1/health", headers=hdr).json()


def test_owner_tokens_are_rejected_on_coach_routes():
    assert client.get("/v1/coach/goals", headers=OWNER).status_code == 401
    assert client.get("/v1/coach/goals").status_code == 401


def test_sign_out_revokes_a_coach_session():
    hdr = coach_login()
    assert client.post("/v1/auth/sign-out", headers=hdr).status_code == 204
    assert client.get("/v1/coach/goals", headers=hdr).status_code == 401


# ── visibility ───────────────────────────────────────────────────────────────
def test_coach_sees_only_shared_goals():
    hdr = coach_login()
    shared = mk(shared=True)
    private = mk(shared=False)
    ids = [g["id"] for g in client.get("/v1/coach/goals", headers=hdr).json()["goals"]]
    assert ids == [shared["id"]]
    assert client.post(f"/v1/coach/goals/{private['id']}/fail", headers=hdr, json={}).status_code == 404
    assert CHARGES == []


def test_coach_created_goal_is_shared_and_capped():
    hdr = coach_login()
    r = client.post("/v1/coach/goals", headers=hdr,
                    json={"name": "No phone in bed", "base_days": 5, "base_stake": 10})
    assert r.status_code == 200 and r.json()["coach"] is True
    owner_view = client.get("/v1/commitments", headers=OWNER).json()
    assert [c["name"] for c in owner_view] == ["No phone in bed"]
    r = client.post("/v1/coach/goals", headers=hdr,
                    json={"name": "x", "base_days": 5, "base_stake": 51})
    assert r.status_code == 400


# ── verdicts ─────────────────────────────────────────────────────────────────
def test_owner_cannot_self_certify_a_shared_goal():
    cm = mk()
    make_due(cm["id"])
    assert client.post(f"/v1/commitments/{cm['id']}/confirm-clean", headers=OWNER).status_code == 403


def test_pass_waits_for_the_deadline_then_records_the_coach():
    hdr = coach_login()
    cm = mk()
    assert client.post(f"/v1/coach/goals/{cm['id']}/pass", headers=hdr).status_code == 409
    make_due(cm["id"])
    r = client.post(f"/v1/coach/goals/{cm['id']}/pass", headers=hdr)
    assert r.status_code == 200
    g = r.json()
    assert g["current_rung"]["awaiting_decision"] and g["history"][-1] == {
        **g["history"][-1], "outcome": "success", "by": "coach"}
    assert client.post(f"/v1/coach/goals/{cm['id']}/pass", headers=hdr).status_code == 409
    assert CHARGES == []
    r = client.post(f"/v1/coach/goals/{cm['id']}/next", headers=hdr, json={"days": 4, "stake": 5})
    assert r.status_code == 200 and r.json()["current_rung"]["days"] == 4


def test_fail_charges_the_same_beeminder_path_and_recommits():
    hdr = coach_login()
    cm = mk(days=3, stake=5)
    r = client.post(f"/v1/coach/goals/{cm['id']}/fail", headers=hdr, json={})
    assert r.status_code == 200
    body = r.json()
    assert CHARGES and CHARGES[0][0] == 5 and "verified by coach" in CHARGES[0][1]
    assert body["recommit"] == {"days": 3, "stake": 6}
    assert body["commitment"]["history"][-1]["outcome"] == "lapse"
    assert body["commitment"]["history"][-1]["by"] == "coach"
    assert client.get("/v1/settings", headers=OWNER).json()["totalCharged"] == 5
    # After the deadline, a fail is recorded as a miss.
    make_due(cm["id"])
    client.post(f"/v1/coach/goals/{cm['id']}/fail", headers=hdr, json={})
    assert store.get_commitment(cm["id"])["history"][-1]["outcome"] == "missed"


def test_next_rung_refused_while_a_rung_is_running():
    hdr = coach_login()
    cm = mk()
    r = client.post(f"/v1/coach/goals/{cm['id']}/next", headers=hdr, json={"days": 1, "stake": 1})
    assert r.status_code == 409


def test_shared_goal_never_auto_charges():
    cm = mk()
    make_due(cm["id"], past_grace=True)
    r = client.post("/v1/tick", headers=OWNER).json()
    assert r["charged_count"] == 0
    client.post(f"/v1/commitments/{cm['id']}/auto-miss", headers=OWNER)
    assert CHARGES == []


# ── sharing + archive ────────────────────────────────────────────────────────
def test_unshare_only_once_paused():
    hdr = coach_login()
    cm = mk()
    r = client.post(f"/v1/commitments/{cm['id']}/coach", headers=OWNER, json={"shared": False})
    assert r.status_code == 409
    make_due(cm["id"])
    client.post(f"/v1/coach/goals/{cm['id']}/pass", headers=hdr)
    r = client.post(f"/v1/commitments/{cm['id']}/coach", headers=OWNER, json={"shared": False})
    assert r.status_code == 200 and "coach" not in r.json()


def test_coach_archive_and_unarchive():
    hdr = coach_login()
    cm = mk()
    assert client.post(f"/v1/coach/goals/{cm['id']}/archive", headers=hdr).status_code == 409
    make_due(cm["id"])
    client.post(f"/v1/coach/goals/{cm['id']}/pass", headers=hdr)
    r = client.post(f"/v1/coach/goals/{cm['id']}/archive", headers=hdr)
    assert r.status_code == 200 and r.json()["archived_at"]
    r = client.post(f"/v1/coach/goals/{cm['id']}/unarchive", headers=hdr)
    assert r.status_code == 200 and "archived_at" not in r.json()


def test_legacy_sessions_table_is_migrated_to_owner(tmp_path):
    import sqlite3
    from app.store import Store
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, email TEXT NOT NULL,"
                " expires_at INTEGER NOT NULL)")
    con.execute("INSERT INTO sessions VALUES ('h', 'owner@example.com', 99999999999999)")
    con.commit()
    con.close()
    assert Store(path).get_session("h")["role"] == "owner"
