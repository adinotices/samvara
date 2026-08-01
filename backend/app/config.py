"""Runtime configuration, read from environment.

Everything hosting-specific lives here so moving between GitHub-Pages+API,
DigitalOcean, Fly, Render, or a laptop is a matter of env vars, never code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: list[str]) -> list[str]:
    v = os.environ.get(name)
    if not v:
        return default
    return [item.strip() for item in v.split(",") if item.strip()]


@dataclass
class Settings:
    # ── persistence ──────────────────────────────────────────────────────
    # SQLite file, used only when DATABASE_URL is unset (local dev / tests).
    # Put it on a persistent volume if you deploy on SQLite anyway.
    db_path: str = os.environ.get("SAMVARA_DB", "samvara.db")
    # A SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@host/db. This is
    # what production should set — SQLite's single-writer model doesn't hold
    # up multi-tenant, and the row-level locking the money paths need
    # (SELECT ... FOR UPDATE) is a Postgres feature, not a SQLite one; SQLite
    # here degrades to the same coarse table lock the old single-user store
    # used; it's shared to keep local dev and tests dependency-free.
    database_url: str = os.environ.get("DATABASE_URL", "")

    # ── logging ──────────────────────────────────────────────────────────
    # Standard level names (DEBUG/INFO/WARNING/ERROR/CRITICAL). JSON lines to
    # stdout — see logging_config.py — so a hosting platform's log collector
    # can parse fields (request_id, path, status) instead of grepping text.
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")

    # ── auth ─────────────────────────────────────────────────────────────
    # "none"  -> no auth (local dev only).
    # "token" -> every request must send  Authorization: Bearer <API_TOKEN>.
    auth_mode: str = os.environ.get("AUTH_MODE", "token")
    api_token: str = os.environ.get("API_TOKEN", "")

    # ── CORS ─────────────────────────────────────────────────────────────
    # The exact origin(s) your frontend is served from, e.g.
    #   https://samvara.app , https://<user>.github.io
    # Unset: wide open in AUTH_MODE=none (local dev), browsers blocked
    # otherwise — a forgotten var should fail loudly, not fall open.
    allowed_origins: list[str] = field(
        default_factory=lambda: _list("ALLOWED_ORIGINS", [])
    )

    # ── Beeminder ────────────────────────────────────────────────────────
    beeminder_user: str = os.environ.get("BEEMINDER_USER", "")
    beeminder_token: str = os.environ.get("BEEMINDER_TOKEN", "")
    # When true, Beeminder is hit in *its* dryrun mode: the call is made and
    # validated but no money moves. Leave true until you have verified the
    # whole flow end to end, then flip to false to arm real charges.
    beeminder_dryrun: bool = _bool("BEEMINDER_DRYRUN", True)

    # ── money safety rails ───────────────────────────────────────────────
    min_stake: float = float(os.environ.get("MIN_STAKE", "1.00"))   # Beeminder floor
    max_charge: float = float(os.environ.get("MAX_CHARGE_USD", "50.00"))
    # A second live slip/miss on the same commitment inside this window is
    # rejected as a duplicate (a double-clicked confirm would otherwise charge
    # the freshly re-rung stake too).
    lapse_debounce_s: float = float(os.environ.get("LAPSE_DEBOUNCE_S", "10"))

    # ── email / OTP auth ────────────────────────────────────────────────────
    # Resend (https://resend.com) API key for sending OTP emails.
    resend_api_key: str = os.environ.get("RESEND_API_KEY", "")
    # The app owner's address: where "request access" notifications go, and
    # who a legacy single-tenant database is attributed to on import. No
    # longer the sign-in allowlist itself — see signup_mode/invites below.
    auth_email: str = os.environ.get("AUTH_EMAIL", "")
    # From address shown in the login email. Must be a verified Resend domain.
    email_from: str = os.environ.get("EMAIL_FROM", "Samvara <noreply@samvara.app>")
    # "invite" -> only emails in the invites table (POST /v1/admin/invites,
    #             owner-only) can complete sign-in; a first-time verify for
    #             any other address is rejected before a session is issued.
    # "open"   -> any address that completes the OTP flow gets an account.
    # Defaults to invite: money is live in this app, so opening signup to the
    # public is a deliberate switch to flip, not this port's default.
    signup_mode: str = os.environ.get("SIGNUP_MODE", "invite")

    # ── daily metrics (the Data tab) ─────────────────────────────────────
    # Default timezone for a NEW user's account (set once, at signup — see
    # store.get_or_create_user) and the fallback when a client bump omits a
    # tz. Each user's own `timezone` column is what actually decides "today"
    # for them day to day; this is just where that column starts out.
    metrics_tz: str = os.environ.get("METRICS_TZ", "America/New_York")

    # ── ratchet timing ───────────────────────────────────────────────────
    # Grace window after a deadline before an unanswered rung auto-charges.
    # Keep in sync with GRACE_MS in frontend/api-client.js (24h there).
    grace_hours: float = float(os.environ.get("GRACE_HOURS", "24"))

    @property
    def grace_ms(self) -> int:
        return int(self.grace_hours * 60 * 60 * 1000)


settings = Settings()
