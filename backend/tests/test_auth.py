"""Auth-flow tests: OTP issue/verify, brute-force cap, send cooldown,
session tokens, static-token acceptance, and health redaction.

Run from backend/:  python -m pytest -q tests/test_auth.py
"""
from __future__ import annotations

import os
import tempfile

import pytest

# Configure BEFORE importing the app: settings and the store singleton read the
# environment at import time.
os.environ["SAMVARA_DB"] = os.path.join(tempfile.mkdtemp(), "test-auth.db")
os.environ["AUTH_MODE"] = "token"
os.environ["API_TOKEN"] = "static-cron-token"
os.environ["AUTH_EMAIL"] = "owner@example.com"

from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
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
    with store.lock, store._conn:
        store._conn.execute("DELETE FROM otp_codes")
    yield


def login() -> str:
    assert client.post("/v1/auth/send-code", json={"email": "owner@example.com"}).status_code == 204
    email, code = SENT[-1]
    r = client.post("/v1/auth/verify-code", json={"email": email, "code": code})
    assert r.status_code == 200
    return r.json()["token"]


def test_full_otp_flow_grants_access():
    token = login()
    r = client.get("/v1/commitments", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_unauthorised_email_gets_204_and_no_email():
    r = client.post("/v1/auth/send-code", json={"email": "attacker@example.com"})
    assert r.status_code == 204          # indistinguishable from success…
    assert SENT == []                     # …but nothing was sent


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


def test_verify_rejects_non_auth_email_even_with_real_code():
    client.post("/v1/auth/send-code", json={"email": "owner@example.com"})
    _, code = SENT[-1]
    r = client.post("/v1/auth/verify-code",
                    json={"email": "other@example.com", "code": code})
    assert r.status_code == 401


def test_static_token_and_garbage_token():
    ok = client.get("/v1/commitments",
                    headers={"Authorization": "Bearer static-cron-token"})
    assert ok.status_code == 200
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


def test_settings_patch_cannot_touch_total_charged():
    before = client.get("/v1/settings",
                        headers={"Authorization": "Bearer static-cron-token"}).json()
    client.patch("/v1/settings", json={"totalCharged": 9999, "recipient": "X"},
                 headers={"Authorization": "Bearer static-cron-token"})
    after = client.get("/v1/settings",
                       headers={"Authorization": "Bearer static-cron-token"}).json()
    assert after["totalCharged"] == before["totalCharged"]
    assert after["recipient"] == "X"
