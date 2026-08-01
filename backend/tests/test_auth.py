"""Auth-flow tests: OTP issue/verify, brute-force cap, send cooldown,
session tokens, invite gating, admin routes, and health redaction.

Run from backend/:  python -m pytest -q tests/test_auth.py
"""
from __future__ import annotations

import os
import tempfile

import pytest

# Configure BEFORE importing the app: settings and the store singleton read the
# environment at import time. SIGNUP_MODE left at its default ("invite") — this
# file specifically exercises that gate, unlike the other test modules which
# open signup for convenience.
os.environ["SAMVARA_DB"] = os.path.join(tempfile.mkdtemp(), "test-auth.db")
os.environ["AUTH_MODE"] = "token"
os.environ["API_TOKEN"] = "static-cron-token"
os.environ["AUTH_EMAIL"] = "owner@example.com"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app import auth, db  # noqa: E402
from app.main import app  # noqa: E402
from app.store import store  # noqa: E402

client = TestClient(app)
SENT: list[tuple[str, str]] = []  # (email, code) captured instead of emailing


@pytest.fixture(autouse=True)
def _capture_email(monkeypatch):
    SENT.clear()

    async def fake_send(email: str, code: str) -> None:
        SENT.append((email, code))

    monkeypatch.setattr(auth, "send_otp_email", fake_send)
    # Each test starts with no pending OTPs so the send cooldown can't bleed over.
    with store.lock, store.engine.begin() as conn:
        conn.execute(delete(db.otp_codes))
        conn.execute(delete(db.invites))
    yield


def login(email: str = "owner@example.com") -> str:
    assert client.post("/v1/auth/send-code", json={"email": email}).status_code == 204
    sent_email, code = SENT[-1]
    assert sent_email == email
    r = client.post("/v1/auth/verify-code", json={"email": email, "code": code})
    assert r.status_code == 200
    return r.json()["token"]


def test_full_otp_flow_grants_access():
    token = login()
    r = client.get("/v1/commitments", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_first_signin_creates_the_account():
    token = login()
    hdr = {"Authorization": f"Bearer {token}"}
    # Signing in twice doesn't create a second account: same commitments list
    # identity both times (proven by settings staying put across a second login).
    client.patch("/v1/settings", json={"recipient": "Owner Recipient"}, headers=hdr)
    token2 = login()
    hdr2 = {"Authorization": f"Bearer {token2}"}
    assert client.get("/v1/settings", headers=hdr2).json()["recipient"] == "Owner Recipient"


def test_unauthorised_uninvited_email_gets_204_and_no_email():
    r = client.post("/v1/auth/send-code", json={"email": "attacker@example.com"})
    assert r.status_code == 204          # indistinguishable from success…
    assert SENT == []                     # …but nothing was sent


def test_invited_email_can_sign_in():
    store.add_invite("guest@example.com", note="testing")
    token = login("guest@example.com")
    r = client.get("/v1/commitments", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_wrong_code_rejected_and_capped_at_five_attempts():
    client.post("/v1/auth/send-code", json={"email": "owner@example.com"})
    _, code = SENT[-1]
    wrong = "000000" if code != "000000" else "000001"
    for _ in range(5):
        r = client.post("/v1/auth/verify-code",
                        json={"email": "owner@example.com", "code": wrong})
        assert r.status_code == 401
    # The 5 wrong guesses burned the code: even the REAL one is dead now.
    r = client.post("/v1/auth/verify-code",
                    json={"email": "owner@example.com", "code": code})
    assert r.status_code == 401


def test_code_is_single_use():
    token = login()
    email, code = SENT[-1]
    r = client.post("/v1/auth/verify-code", json={"email": email, "code": code})
    assert r.status_code == 401
    assert token  # the first exchange still holds


def test_send_cooldown_keeps_existing_code_valid():
    client.post("/v1/auth/send-code", json={"email": "owner@example.com"})
    client.post("/v1/auth/send-code", json={"email": "owner@example.com"})
    assert len(SENT) == 1                 # second send inside cooldown: no email
    _, code = SENT[-1]
    r = client.post("/v1/auth/verify-code",
                    json={"email": "owner@example.com", "code": code})
    assert r.status_code == 200           # the original code still works


def test_verify_rejects_uninvited_email_even_with_real_code():
    client.post("/v1/auth/send-code", json={"email": "owner@example.com"})
    _, code = SENT[-1]
    r = client.post("/v1/auth/verify-code",
                    json={"email": "other@example.com", "code": code})
    assert r.status_code == 401


def test_static_token_works_on_tick_not_on_user_routes():
    # /v1/tick is a system route: the static cron token is exactly what it's
    # for. /v1/commitments is user data: the static token grants no "current
    # user" to scope it to, so it must be rejected there.
    tick = client.post("/v1/tick",
                       headers={"Authorization": "Bearer static-cron-token"})
    assert tick.status_code == 200
    commitments = client.get("/v1/commitments",
                             headers={"Authorization": "Bearer static-cron-token"})
    assert commitments.status_code == 401
    bad = client.get("/v1/commitments", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    missing = client.get("/v1/commitments")
    assert missing.status_code == 401


def test_health_redacts_config_without_token():
    anon = client.get("/v1/health").json()
    assert anon == {"status": "ok"}
    full = client.get("/v1/health",
                      headers={"Authorization": "Bearer static-cron-token"}).json()
    assert full["status"] == "ok" and "beeminder_dryrun" in full


def test_sign_out_revokes_the_session_server_side():
    token = login()
    hdr = {"Authorization": f"Bearer {token}"}
    assert client.get("/v1/commitments", headers=hdr).status_code == 200
    assert client.post("/v1/auth/sign-out", headers=hdr).status_code == 204
    # The token is dead in the database, not just forgotten by the browser.
    assert client.get("/v1/commitments", headers=hdr).status_code == 401
    # Repeats and garbage are harmless no-ops.
    assert client.post("/v1/auth/sign-out", headers=hdr).status_code == 204
    assert client.post("/v1/auth/sign-out").status_code == 204
    # Signing out a session never kills the static cron token's OWN route.
    assert client.post("/v1/auth/sign-out",
                       headers={"Authorization": "Bearer static-cron-token"}).status_code == 204
    assert client.post("/v1/tick",
                       headers={"Authorization": "Bearer static-cron-token"}).status_code == 200


def test_settings_patch_cannot_touch_total_charged():
    hdr = {"Authorization": f"Bearer {login()}"}
    before = client.get("/v1/settings", headers=hdr).json()
    client.patch("/v1/settings", json={"totalCharged": 9999, "recipient": "X"}, headers=hdr)
    after = client.get("/v1/settings", headers=hdr).json()
    assert after["totalCharged"] == before["totalCharged"]
    assert after["recipient"] == "X"


# ── admin: invites ────────────────────────────────────────────────────────────
def test_admin_invites_require_owner_or_static_token():
    guest_hdr = {"Authorization": f"Bearer {login('owner@example.com')}"}
    # The owner IS allowed (they manage the list).
    r = client.post("/v1/admin/invites", json={"email": "new@example.com"}, headers=guest_hdr)
    assert r.status_code == 200
    # A non-owner signed-in user is not, even though they're authenticated.
    store.add_invite("regular@example.com", note=None)
    regular_hdr = {"Authorization": f"Bearer {login('regular@example.com')}"}
    r = client.post("/v1/admin/invites", json={"email": "another@example.com"}, headers=regular_hdr)
    assert r.status_code == 403
    # The static token can too (it's what the owner would automate with).
    r = client.get("/v1/admin/invites", headers={"Authorization": "Bearer static-cron-token"})
    assert r.status_code == 200
    assert any(i["email"] == "new@example.com" for i in r.json())


# ── account deletion ─────────────────────────────────────────────────────────
def test_delete_account_erases_data_and_kills_the_session():
    hdr = {"Authorization": f"Bearer {login('owner@example.com')}"}
    client.post("/v1/commitments", json={"name": "To be deleted", "base_days": 1, "base_stake": 5.0},
               headers=hdr)
    assert len(client.get("/v1/commitments", headers=hdr).json()) >= 1

    r = client.delete("/v1/account", headers=hdr)
    assert r.status_code == 204
    # The session that just deleted the account is itself gone.
    assert client.get("/v1/commitments", headers=hdr).status_code == 401
    # A fresh sign-in for the same (owner) email creates a NEW, empty account —
    # deletion didn't just hide the data, and re-signing in as the owner still
    # works (owner status isn't itself deleted by this).
    new_hdr = {"Authorization": f"Bearer {login('owner@example.com')}"}
    assert client.get("/v1/commitments", headers=new_hdr).json() == []
