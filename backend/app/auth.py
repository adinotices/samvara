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


def signin_allowed(email: str) -> bool:
    """Gate for completing sign-in, checked AFTER the OTP itself verifies —
    proving control of the address is necessary but, in invite mode, not
    sufficient. In "open" mode everyone who gets this far is allowed. The
    configured AUTH_EMAIL (the app owner) is always allowed regardless of
    mode — they manage the invite list, so they can't be locked out of it."""
    owner = (settings.auth_email or "").strip().lower()
    if owner and email == owner:
        return True
    if settings.signup_mode == "open":
        return True
    return store.is_invited(email)


def create_session(email: str, device_name: str = "Unknown Device",
                   user_agent: str | None = None, ip_address: str | None = None) -> str:
    """Get-or-create the user for this email (first successful sign-in IS
    signup — there's no separate registration step) and issue a session
    token for them. Caller must have already checked signin_allowed()."""
    user = store.get_or_create_user(email, settings.metrics_tz)
    token = secrets.token_hex(32)
    # Create device record for session tracking
    device_id = store.create_device(user["id"], device_name, user_agent, ip_address)
    store.save_session(sha256(token), user["id"], _now_ms() + SESSION_TTL_MS, device_id)
    store.log_audit(user["id"], "signin", ip_address=ip_address, user_agent=user_agent)
    return token


async def send_email(to: str, subject: str, text: str) -> None:
    if not settings.resend_api_key:
        raise RuntimeError("RESEND_API_KEY is not configured on the server.")
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.email_from, "to": [to], "subject": subject, "text": text},
        )
        r.raise_for_status()


async def send_otp_email(email: str, code: str) -> None:
    await send_email(
        email,
        "Your Samvara login code",
        f"Your Samvara login code is: {code}\n\n"
        "It expires in 10 minutes. If you didn't request this, ignore it.",
    )
