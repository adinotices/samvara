"""SQLAlchemy schema + engine factory — the multi-tenant replacement for the
old hand-rolled sqlite3 store.

Design choices, and why:

  * SQLAlchemy Core, not the ORM. store.py's public API is "pass a dict in,
    get a dict out" (Commitment is a plain dict throughout ratchet.py); Core
    tables keep that shape instead of forcing a model-object layer between
    the domain code and persistence, which would be a much bigger diff for
    no behavioral gain here.
  * Postgres in production, SQLite for local dev and tests. DATABASE_URL
    unset -> SQLite at config.db_path, same as before this port. Row-level
    locking on the charge-critical selects (.with_for_update(), used in
    store.py) is a real lock on Postgres and a silent no-op on SQLite —
    correct in prod, and in dev/tests the existing Store.lock
    (threading.RLock) still serializes writes the way it always has, so
    SQLite's lack of real row locking doesn't show up as a correctness gap
    at the scale dev/tests run at.
  * Every tenant-owned table carries user_id and is indexed on it. There is
    no query in store.py that omits a user filter on a user-owned table —
    see the isolation tests in tests/test_isolation.py, which assert that
    directly rather than trusting call sites to remember it.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
)
from sqlalchemy.engine import Engine

from .config import settings

metadata = MetaData()

# ── identity ────────────────────────────────────────────────────────────────
users = Table(
    "users", metadata,
    Column("id", String, primary_key=True),
    Column("email", String, nullable=False, unique=True),
    Column("created_at", BigInteger, nullable=False),
    Column("timezone", String, nullable=False),
    # 'active' | 'deleted'. Deletion is a real row purge (see store.delete_user),
    # not a soft-delete flag — this column exists for the brief accounting
    # window during the delete transaction itself, not as a durable state.
    Column("status", String, nullable=False, server_default="active"),
    Column("deleted_at", BigInteger, nullable=True),
)

# Sign-in allowlist when config.signup_mode == "invite" (the default — money
# is live in this app, so opening signup to the public is a deliberate
# switch, not this port's default). Irrelevant once signup_mode == "open".
invites = Table(
    "invites", metadata,
    Column("email", String, primary_key=True),
    Column("created_at", BigInteger, nullable=False),
    Column("note", String, nullable=True),
)

otp_codes = Table(
    "otp_codes", metadata,
    Column("email", String, primary_key=True),  # pre-auth: keyed by email, not user id
    Column("code_hash", String, nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("created_at", BigInteger, nullable=False),
    Column("expires_at", BigInteger, nullable=False),
)

sessions = Table(
    "sessions", metadata,
    Column("token_hash", String, primary_key=True),
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    Column("expires_at", BigInteger, nullable=False),
    Index("ix_sessions_user_id", "user_id"),
)

# ── access requests (sign-in gate's "request access" form) ──────────────────
# Pre-auth by definition — no user_id.
access_requests = Table(
    "access_requests", metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("email", String, nullable=False),
    Column("message", Text, nullable=False),
    Column("created_at", BigInteger, nullable=False),
)

# ── commitments ───────────────────────────────────────────────────────────────
commitments = Table(
    "commitments", metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("data", Text, nullable=False),  # JSON — the Commitment dict, unchanged shape
    Index("ix_commitments_user_id", "user_id"),
)

# ── daily metric tallies (the Data tab) ──────────────────────────────────────
metric_days = Table(
    "metric_days", metadata,
    Column("user_id", String, ForeignKey("users.id"), primary_key=True),
    Column("metric", String, primary_key=True),
    Column("day", String, primary_key=True),
    Column("count", Integer, nullable=False, server_default="0"),
)

# ── end-of-day Beeminder penalty bookkeeping ─────────────────────────────────
penalty_days = Table(
    "penalty_days", metadata,
    Column("user_id", String, ForeignKey("users.id"), primary_key=True),
    Column("day", String, primary_key=True),
    Column("tz", String, nullable=False),
    Column("charged_count", Integer, nullable=False, server_default="0"),
)

# ── per-user settings (replaces the old single-row global kv) ───────────────
user_settings = Table(
    "user_settings", metadata,
    Column("user_id", String, ForeignKey("users.id"), primary_key=True),
    Column("data", Text, nullable=False),  # JSON — {apiBaseUrl, recipient, totalCharged}
)

# ── charge ledger ─────────────────────────────────────────────────────────────
# Schema lands with the rest of the multi-tenant port (one migration instead
# of two); the ledger-writing application logic (idempotency, the
# pending->committed outbox, aggregate caps) is a separate, later change.
charges = Table(
    "charges", metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    Column("commitment_id", String, nullable=True),
    Column("amount", Float, nullable=False),
    Column("kind", String, nullable=False),       # 'lapse' | 'missed' | 'auto-missed' | 'penalty'
    Column("status", String, nullable=False),      # 'pending' | 'committed' | 'failed'
    Column("provider", String, nullable=False, server_default="beeminder"),
    Column("provider_charge_id", String, nullable=True),
    Column("idempotency_key", String, nullable=True, unique=True),
    Column("note", Text, nullable=True),
    Column("created_at", BigInteger, nullable=False),
    Column("committed_at", BigInteger, nullable=True),
    Index("ix_charges_user_id", "user_id"),
)


def make_engine(url: str | None = None) -> Engine:
    url = url or settings.database_url or f"sqlite:///{settings.db_path}"
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)
