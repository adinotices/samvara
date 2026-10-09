"""Auth + request/response schemas.

Two valid Bearer tokens are accepted on the owner routes when AUTH_MODE=token:
  1. An owner session token issued by POST /v1/auth/verify-code (browser OTP flow).
  2. The static API_TOKEN env var (used only by the GitHub Actions cron tick).

The coach routes (/v1/coach/*) accept ONLY a coach session token issued by
POST /v1/coach/auth/verify-code. The two roles never cross: a coach token is
rejected everywhere else, and an owner token is rejected on the coach routes.

The static token never needs to be put in config.js — the browser always gets
a session token via OTP. AUTH_MODE=none disables all auth for local dev.
"""
from __future__ import annotations

import secrets as _secrets
from typing import Annotated, Any

from fastapi import Header, HTTPException, status
from pydantic import BaseModel, Field

from .auth import sha256
from .config import settings
from .store import store


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
    # Owner session token — issued by the OTP flow; stored hashed. A coach
    # session is deliberately NOT valid here.
    sess = store.get_session(sha256(token_value))
    return sess is not None and sess.get("role", "owner") == "owner"


def coach_token_is_valid(authorization: str | None) -> bool:
    if settings.auth_mode == "none":
        return True
    if not authorization:
        return False
    scheme, _, token_value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token_value:
        return False
    sess = store.get_session(sha256(token_value))
    return sess is not None and sess.get("role") == "coach"


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    if not token_is_valid(authorization):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing token.")


async def require_coach(authorization: str | None = Header(default=None)) -> None:
    if not coach_token_is_valid(authorization):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing coach token.")


class SendCodeBody(BaseModel):
    email: str


class VerifyCodeBody(BaseModel):
    email: str
    code: str


# NOTE: stake is deliberately NOT capped at MAX_CHARGE_USD here. The cap is a
# charge-time rail, not a schema rule: it is runtime-configurable, so lowering
# it must leave already-stored commitments tolerable rather than invalid. An
# over-cap rung refuses to charge (402, state untouched) and is recovered with
# an explicit choose-next — see test_stake_over_cap_gets_402_and_explicit_
# recommit_recovers. What the ratchet must never do is walk itself over the cap
# on its own; that clamp lives in ratchet.resolve_recommit.
class CreateBody(BaseModel):
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=2000)
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


class CoachShareBody(BaseModel):
    shared: bool


class CoachEditBody(BaseModel):
    # Either or both; an omitted field is left as it is.
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class CoachFailBody(BaseModel):
    # Optional override of the recommit rung; default is the ratchet's own
    # (same length, +$1, held under MAX_CHARGE_USD).
    days: int | None = Field(default=None, ge=1)
    stake: float | None = Field(default=None, ge=1)


class SettingsPatch(BaseModel):
    # totalCharged is deliberately absent: the charge ledger is written only by
    # the charging paths, never by a client patch.
    apiBaseUrl: str | None = None
    recipient: str | None = None


def error(detail: str, code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(code, detail)
