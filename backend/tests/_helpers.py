"""Shared test helpers for the multi-tenant API.

signin() bypasses email delivery (it calls auth.issue_otp directly, the same
function send-code would call) but otherwise goes through the real
verify-code endpoint, so it exercises actual session creation — this isn't a
backdoor, it's "skip the email, keep everything after that real."
"""
from __future__ import annotations

from app import auth


def signin(client, email: str) -> dict[str, str]:
    code = auth.issue_otp(email)
    assert code is not None, f"could not issue an OTP for {email} (cooldown active?)"
    r = client.post("/v1/auth/verify-code", json={"email": email, "code": code})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}"}
