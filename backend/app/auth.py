"""Server-side OTP + session management.

Flow:
  1. POST /v1/auth/send-code   — generates a 6-digit OTP, stores its hash,
                                 emails the code to AUTH_EMAIL.
  2. POST /v1/auth/verify-code — checks the OTP, issues a 30-day session token.

The session token is returned to the browser once, stored in localStorage
under 'samvara.apiToken', and sent as  Authorization: Bearer <token>  on every
subsequent request — the same header the static API_TOKEN uses, so require_auth
in security.py just checks both. Only SHA-256 hashes of codes and tokens are
persisted; a stolen database file contains no usable credential.

Abuse limits: one code per SEND_COOLDOWN (repeat sends inside the window keep
the existing code valid rather than re-emailing), and a code dies after
MAX_ATTEMPTS wrong guesses — so its 10-minute lifetime allows at most
MAX_ATTEMPTS guesses out of 1,000,000, and it can't be brute-forced.

The static API_TOKEN still works and is used only by the GitHub Actions cron
tick, which can't go through the OTP flow.
"""
from __future__ import annotations

import hashlib
import secrets
import time

import httpx

from .config import settings
from .store import store

OTP_TTL_MS = 10 * 60 * 1000                  # a code lives 10 minutes
SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000    # a login lasts 30 days
SEND_COOLDOWN_MS = 60 * 1000                 # at most one email per minute
MAX_ATTEMPTS = 5                             # wrong guesses before the code dies


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)


def issue_otp(email: str) -> str | None:
    """Create + store a fresh OTP for `email`, or None while the send cooldown
    is active (the previously issued code remains valid)."""
    now = _now_ms()
    last = store.last_otp_created(email)
    if last is not None and now - last < SEND_COOLDOWN_MS:
        return None
    code = str(secrets.randbelow(1_000_000)).zfill(6)
    store.save_otp(email, sha256(code), now, now + OTP_TTL_MS)
    return code


def verify_and_consume_otp(email: str, code: str) -> bool:
    return store.consume_otp(email, sha256(code), MAX_ATTEMPTS)


def create_session(email: str) -> str:
    token = secrets.token_hex(32)
    store.save_session(sha256(token), email, _now_ms() + SESSION_TTL_MS)
    return token


async def send_otp_email(email: str, code: str) -> None:
    if not settings.resend_api_key:
        raise RuntimeError("RESEND_API_KEY is not configured on the server.")
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.email_from,
                "to": [email],
                "subject": "Your Samvara login code",
                "text": (
                    f"Your Samvara login code is: {code}\n\n"
                    "It expires in 10 minutes. If you didn't request this, ignore it."
                ),
            },
        )
        r.raise_for_status()
