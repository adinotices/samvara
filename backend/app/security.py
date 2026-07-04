"""Auth + request/response schemas.

Two valid Bearer tokens are accepted when AUTH_MODE=token:
  1. A session token issued by POST /v1/auth/verify-code (browser OTP flow).
  2. The static API_TOKEN env var (used only by the GitHub Actions cron tick).

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
    # Session token — issued by the OTP flow; stored hashed.
    return store.get_session(sha256(token_value)) is not None


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    if not token_is_valid(authorization):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing token.")


class SendCodeBody(BaseModel):
    email: str


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


class SettingsPatch(BaseModel):
    # totalCharged is deliberately absent: the charge ledger is written only by
    # the charging paths, never by a client patch.
    apiBaseUrl: str | None = None
    recipient: str | None = None


def error(detail: str, code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(code, detail)
