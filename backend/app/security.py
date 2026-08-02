"""Auth + request/response schemas.

Three dependencies, for three different callers:
  * current_user   — a session token ONLY, resolved to the signed-in user's
    row. Every user-data route (commitments, settings, metrics, ...) depends
    on this, not on a bearer check that also accepts the static token — the
    static API_TOKEN grants no "current user" (there isn't one to be), so it
    can no longer read or write anyone's data. That's deliberate: the old
    single-tenant require_auth accepted the static token everywhere, which
    made it a god-token; multi-tenant, that's no longer acceptable.
  * require_auth   — session OR the static API_TOKEN. Kept only for /v1/tick,
    the one place a system credential (the cron trigger, not a user) needs in.
  * require_admin  — the static API_TOKEN, or a session belonging to the
    configured AUTH_EMAIL (the app owner). Used for invite management.

AUTH_MODE=none disables all of this for local dev — current_user resolves to
a fixed dev user instead of requiring a real sign-in.
"""
from __future__ import annotations

import secrets as _secrets
from typing import Annotated, Any

from fastapi import Header, HTTPException, status
from pydantic import BaseModel, Field

from .auth import sha256
from .config import is_owner, settings
from .store import store

DEV_USER_EMAIL = "dev@localhost"


def token_is_valid(authorization: str | None) -> bool:
    if settings.auth_mode == "none":
        return True
    if not authorization:
        return False
    scheme, _, token_value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token_value:
        return False
    # Static API token — cron tick only.
    if settings.api_token and _secrets.compare_digest(token_value, settings.api_token):
        return True
    # Session token — issued by the OTP flow; stored hashed.
    return store.get_session(sha256(token_value)) is not None


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    """Session OR the static token. Use ONLY for system-level routes
    (/v1/tick) — never for anything that reads or writes a specific user's
    data. See current_user for that."""
    if not token_is_valid(authorization):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing token.")


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token_value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token_value:
        return None
    return token_value


async def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Resolve the signed-in user from a session token. The static API_TOKEN
    is deliberately not accepted here — see the module docstring."""
    if settings.auth_mode == "none":
        return store.get_or_create_user(DEV_USER_EMAIL, settings.metrics_tz)
    token_value = _bearer_token(authorization)
    if not token_value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing token.")
    session = store.get_session(sha256(token_value))
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing token.")
    user = store.get_user(session["user_id"])
    if user is None or user["status"] != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing token.")
    return user


async def require_admin(authorization: str | None = Header(default=None)) -> None:
    """Static API_TOKEN, or a session belonging to AUTH_EMAIL (the app
    owner). Deliberately not "any signed-in user" — this gates invite
    management, not ordinary app usage."""
    if settings.auth_mode == "none":
        return
    token_value = _bearer_token(authorization)
    if not token_value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing token.")
    if settings.api_token and _secrets.compare_digest(token_value, settings.api_token):
        return
    session = store.get_session(sha256(token_value))
    if session:
        user = store.get_user(session["user_id"])
        if user and is_owner(user["email"]):
            return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required.")


class SendCodeBody(BaseModel):
    email: str


class AccessRequestBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    message: str = Field(min_length=1, max_length=4000)


class VerifyCodeBody(BaseModel):
    email: str
    code: str


class CreateBody(BaseModel):
    name: str
    base_days: int = Field(ge=1)
    base_stake: float = Field(ge=1)


class ChooseNextBody(BaseModel):
    days: int = Field(ge=1)
    stake: float = Field(ge=1)


class LapseBody(BaseModel):
    # Mirrors reportSlip/reportMiss options in the frontend mock.
    dryRun: bool = False
    raise_: Annotated[bool, Field(alias="raise")] = True
    days: int | None = None
    stake: float | None = None

    model_config = {"populate_by_name": True}


class BumpBody(BaseModel):
    # +1 / -1 on a daily metric tally; anything else is rejected in the route.
    delta: int
    # Client's IANA timezone (Intl.DateTimeFormat().resolvedOptions().timeZone),
    # best-effort. Used only to decide when a penalty day's end-of-day sweep
    # fires; falls back to METRICS_TZ server-side if absent or unrecognized.
    tz: str | None = None


class InviteBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    note: str | None = Field(default=None, max_length=500)


class SettingsPatch(BaseModel):
    # totalCharged is deliberately absent: the charge ledger is written only by
    # the charging paths, never by a client patch.
    apiBaseUrl: str | None = None
    recipient: str | None = None
    # 'samvara' (default, Stripe-backed, the only option offered to ordinary
    # users) or 'beeminder' (hidden legacy path — the endpoint handler in
    # main.py rejects this for anyone but the app owner). stripePaymentMethodId
    # is deliberately absent: it's written only by POST /v1/billing/payment-method,
    # never by a client patch, same reasoning as totalCharged above.
    chargeProvider: str | None = None


def error(detail: str, code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(code, detail)
