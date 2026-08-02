"""Persistence — multi-tenant, on SQLAlchemy Core (see db.py for the schema
and the reasoning behind Core-over-ORM and Postgres-in-prod/SQLite-in-dev).

Every table that belongs to a tenant carries user_id, and every method here
that touches one takes a user_id and filters on it — there is no method that
can return or mutate another user's row by construction, not by caller
discipline. See tests/test_isolation.py, which asserts exactly that.

Locking has two layers, for two different failure modes:
  * self.lock (a process-level threading.RLock, as before this port) still
    serializes writes within one process — the cheap, always-available layer,
    and the only one that does anything on SQLite.
  * commitment_lock() below opens a real transaction and SELECTs the
    commitment row FOR UPDATE — a real lock on Postgres, so two workers (or
    two processes) racing a charge on the same commitment can't both pass the
    "is this rung already resolved" check. This is what makes running more
    than one worker (the Dockerfile is pinned to --workers 1 today) possible
    once you're actually running against Postgres — see main.py's charge
    paths, which now open one of these instead of read-then-write.
"""
from __future__ import annotations

import hmac
import json
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Connection, Engine

from . import db
from .config import settings as cfg
from .ratchet import Commitment

DEFAULT_USER_SETTINGS = {
    "apiBaseUrl": "", "recipient": "Saṃvara", "totalCharged": 0,
    # 'samvara' (Stripe-backed, the only choice ordinary users can set) or
    # 'beeminder' (hidden, owner-only — see billing.py). stripePaymentMethodId
    # is the Stripe PaymentMethod id attached as the customer's default, set
    # by POST /v1/billing/payment-method once the client confirms a SetupIntent.
    "chargeProvider": "samvara",
    "stripePaymentMethodId": None,
}


def new_user_id() -> str:
    return "u_" + uuid.uuid4().hex[:12]


class Store:
    def __init__(self, engine: Engine):
        self.engine = engine
        # See module docstring: this is the SQLite-safety / same-process layer,
        # not the cross-process one.
        import threading
        self.lock = threading.RLock()
        db.metadata.create_all(engine)

    def ping(self) -> bool:
        try:
            with self.lock, self.engine.connect() as conn:
                conn.execute(select(1))
            return True
        except Exception:
            return False

    # ── users ────────────────────────────────────────────────────────────
    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(db.users).where(db.users.c.id == user_id)
            ).mappings().first()
        return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(db.users).where(db.users.c.email == email)
            ).mappings().first()
        return dict(row) if row else None

    def get_or_create_user(self, email: str, default_tz: str) -> dict[str, Any]:
        """Idempotent: returns the existing user for this email, or creates
        one. Called from the OTP verify path, so "first successful sign-in
        creates the account" — there's no separate registration step."""
        with self.lock, self.engine.begin() as conn:
            row = conn.execute(
                select(db.users).where(db.users.c.email == email)
            ).mappings().first()
            if row:
                return dict(row)
            uid = new_user_id()
            now = int(time.time() * 1000)
            conn.execute(db.users.insert().values(
                id=uid, email=email, created_at=now, timezone=default_tz,
                status="active", deleted_at=None,
            ))
            conn.execute(db.user_settings.insert().values(
                user_id=uid, data=json.dumps(DEFAULT_USER_SETTINGS),
            ))
            return {"id": uid, "email": email, "created_at": now,
                    "timezone": default_tz, "status": "active", "deleted_at": None}

    def set_stripe_customer_id(self, user_id: str, customer_id: str) -> None:
        with self.lock, self.engine.begin() as conn:
            conn.execute(
                update(db.users).where(db.users.c.id == user_id)
                .values(stripe_customer_id=customer_id)
            )

    def list_users(self) -> list[dict[str, Any]]:
        """Active users only — for the tick sweep to iterate. A deleted
        user's rows are gone (see delete_user), so this is also just "every
        user with data left to sweep"."""
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(
                select(db.users).where(db.users.c.status == "active")
            ).mappings().all()
        return [dict(r) for r in rows]

    def delete_user(self, user_id: str) -> None:
        """Hard delete: every row this user owns, gone, in one transaction.
        Not a soft-delete flag — GDPR erasure means the data stops existing,
        not that it's hidden behind a status column. Charges are the one
        exception: they're a financial record, kept but with the user_id
        retained (the row still exists; nothing here scrubs it) — deleting a
        user does not currently erase their charge history. Revisit this
        before relying on it for a real erasure request; it's flagged in
        the project plan (1C) as a compliance item, not fully closed here."""
        with self.lock, self.engine.begin() as conn:
            conn.execute(delete(db.commitments).where(db.commitments.c.user_id == user_id))
            conn.execute(delete(db.metric_days).where(db.metric_days.c.user_id == user_id))
            conn.execute(delete(db.penalty_days).where(db.penalty_days.c.user_id == user_id))
            conn.execute(delete(db.user_settings).where(db.user_settings.c.user_id == user_id))
            conn.execute(delete(db.sessions).where(db.sessions.c.user_id == user_id))
            conn.execute(delete(db.users).where(db.users.c.id == user_id))

    # ── invites (signup_mode == "invite") ───────────────────────────────────
    def is_invited(self, email: str) -> bool:
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(db.invites.c.email).where(db.invites.c.email == email)
            ).first()
        return row is not None

    def add_invite(self, email: str, note: str | None) -> None:
        with self.lock, self.engine.begin() as conn:
            now = int(time.time() * 1000)
            if conn.dialect.name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                stmt = pg_insert(db.invites).values(email=email, created_at=now, note=note)
                stmt = stmt.on_conflict_do_nothing(index_elements=["email"])
                conn.execute(stmt)
            else:
                existing = conn.execute(
                    select(db.invites.c.email).where(db.invites.c.email == email)
                ).first()
                if not existing:
                    conn.execute(db.invites.insert().values(email=email, created_at=now, note=note))

    def list_invites(self) -> list[dict[str, Any]]:
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(select(db.invites).order_by(db.invites.c.created_at.desc())).mappings().all()
        return [dict(r) for r in rows]

    # ── commitments ──────────────────────────────────────────────────────
    def list_commitments(self, user_id: str) -> list[Commitment]:
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(
                select(db.commitments.c.data)
                .where(db.commitments.c.user_id == user_id)
                .order_by(db.commitments.c.seq.asc())
            ).all()
        return [json.loads(r[0]) for r in rows]

    def get_commitment(self, user_id: str, cid: str) -> Commitment | None:
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(db.commitments.c.data)
                .where(db.commitments.c.id == cid, db.commitments.c.user_id == user_id)
            ).first()
        return json.loads(row[0]) if row else None

    def insert_commitment(self, user_id: str, cm: Commitment) -> None:
        with self.lock, self.engine.begin() as conn:
            seq = conn.execute(
                select(func.coalesce(func.max(db.commitments.c.seq), 0) + 1)
                .where(db.commitments.c.user_id == user_id)
            ).scalar_one()
            conn.execute(db.commitments.insert().values(
                id=cm["id"], user_id=user_id, seq=seq, data=json.dumps(cm),
            ))

    def update_commitment(self, user_id: str, cm: Commitment) -> None:
        with self.lock, self.engine.begin() as conn:
            conn.execute(
                update(db.commitments)
                .where(db.commitments.c.id == cm["id"], db.commitments.c.user_id == user_id)
                .values(data=json.dumps(cm))
            )

    @contextmanager
    def commitment_lock(self, user_id: str, cid: str) -> Iterator[tuple[Connection, Commitment | None]]:
        """Open a transaction and SELECT the commitment FOR UPDATE — see the
        module docstring. Yields (conn, commitment-or-None); the caller does
        its read-check-charge-write sequence using conn (via
        save_commitment_in / add_total_charged_in below) and the transaction
        commits when the `with` block exits, releasing the lock.

        Deliberately does NOT take self.lock (unlike every other method here):
        callers hold this open across an `await beeminder.charge(...)`, and
        self.lock is a plain threading.RLock — held across an await inside a
        single-threaded event loop it would block every OTHER store call in
        the whole process (any user's read or write) for the duration of one
        user's network round-trip to Beeminder, not just serialize charges
        against each other. Same-process charge serialization is
        main.py's _charge_lock (an asyncio.Lock, which behaves correctly
        across awaits); this transaction's FOR UPDATE is what serializes
        charges across processes/workers on Postgres."""
        with self.engine.begin() as conn:
            row = conn.execute(
                select(db.commitments.c.data)
                .where(db.commitments.c.id == cid, db.commitments.c.user_id == user_id)
                .with_for_update()
            ).first()
            cm = json.loads(row[0]) if row else None
            yield conn, cm

    def save_commitment_in(self, conn: Connection, user_id: str, cm: Commitment) -> None:
        """Write a commitment inside an existing transaction (see commitment_lock)."""
        conn.execute(
            update(db.commitments)
            .where(db.commitments.c.id == cm["id"], db.commitments.c.user_id == user_id)
            .values(data=json.dumps(cm))
        )

    # ── settings ─────────────────────────────────────────────────────────
    def get_settings(self, user_id: str) -> dict[str, Any]:
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(db.user_settings.c.data).where(db.user_settings.c.user_id == user_id)
            ).first()
        return json.loads(row[0]) if row else dict(DEFAULT_USER_SETTINGS)

    def update_settings(self, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self.lock, self.engine.begin() as conn:
            cur = self._get_settings_in(conn, user_id)
            cur.update({k: v for k, v in patch.items() if v is not None})
            conn.execute(
                update(db.user_settings)
                .where(db.user_settings.c.user_id == user_id)
                .values(data=json.dumps(cur))
            )
        return cur

    def _get_settings_in(self, conn: Connection, user_id: str) -> dict[str, Any]:
        row = conn.execute(
            select(db.user_settings.c.data).where(db.user_settings.c.user_id == user_id)
        ).first()
        return json.loads(row[0]) if row else dict(DEFAULT_USER_SETTINGS)

    def add_total_charged_in(self, conn: Connection, user_id: str, amount: float) -> None:
        """Bump totalCharged inside an existing transaction (see commitment_lock)."""
        cur = self._get_settings_in(conn, user_id)
        cur["totalCharged"] = round(cur.get("totalCharged", 0) + amount, 2)
        conn.execute(
            update(db.user_settings)
            .where(db.user_settings.c.user_id == user_id)
            .values(data=json.dumps(cur))
        )

    def add_total_charged(self, user_id: str, amount: float) -> None:
        with self.lock, self.engine.begin() as conn:
            self.add_total_charged_in(conn, user_id, amount)

    # ── daily metric tallies (the Data tab) ──────────────────────────────
    def bump_metric(self, user_id: str, metric: str, day: str, delta: int) -> int:
        """Add `delta` to a metric's tally for `day`, floored at 0."""
        with self.lock, self.engine.begin() as conn:
            row = conn.execute(
                select(db.metric_days.c.count)
                .where(db.metric_days.c.user_id == user_id,
                       db.metric_days.c.metric == metric, db.metric_days.c.day == day)
            ).first()
            new = max(0, (row[0] if row else 0) + delta)
            if row is None:
                conn.execute(db.metric_days.insert().values(
                    user_id=user_id, metric=metric, day=day, count=new,
                ))
            else:
                conn.execute(
                    update(db.metric_days)
                    .where(db.metric_days.c.user_id == user_id,
                           db.metric_days.c.metric == metric, db.metric_days.c.day == day)
                    .values(count=new)
                )
        return new

    def metric_series(self, user_id: str) -> dict[str, dict[str, int]]:
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(
                select(db.metric_days.c.metric, db.metric_days.c.day, db.metric_days.c.count)
                .where(db.metric_days.c.user_id == user_id)
                .order_by(db.metric_days.c.day.asc())
            ).all()
        out: dict[str, dict[str, int]] = {}
        for metric, day, count in rows:
            out.setdefault(metric, {})[day] = count
        return out

    def metric_count(self, user_id: str, metric: str, day: str) -> int:
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(db.metric_days.c.count)
                .where(db.metric_days.c.user_id == user_id,
                       db.metric_days.c.metric == metric, db.metric_days.c.day == day)
            ).first()
        return row[0] if row else 0

    # ── end-of-day penalty bookkeeping ────────────────────────────────────
    def upsert_penalty_tz(self, user_id: str, day: str, tz: str) -> None:
        with self.lock, self.engine.begin() as conn:
            existing = conn.execute(
                select(db.penalty_days.c.day)
                .where(db.penalty_days.c.user_id == user_id, db.penalty_days.c.day == day)
            ).first()
            if existing:
                conn.execute(
                    update(db.penalty_days)
                    .where(db.penalty_days.c.user_id == user_id, db.penalty_days.c.day == day)
                    .values(tz=tz)
                )
            else:
                conn.execute(db.penalty_days.insert().values(
                    user_id=user_id, day=day, tz=tz, charged_count=0,
                ))

    def get_penalty_day(self, user_id: str, day: str) -> dict[str, Any] | None:
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(db.penalty_days.c.tz, db.penalty_days.c.charged_count)
                .where(db.penalty_days.c.user_id == user_id, db.penalty_days.c.day == day)
            ).first()
        return {"tz": row[0], "charged_count": row[1]} if row else None

    def mark_penalty_charged(self, user_id: str, day: str, charged_count: int) -> None:
        with self.lock, self.engine.begin() as conn:
            conn.execute(
                update(db.penalty_days)
                .where(db.penalty_days.c.user_id == user_id, db.penalty_days.c.day == day)
                .values(charged_count=charged_count)
            )

    def pending_penalties(self, user_id: str, metric: str, since: str) -> list[dict[str, Any]]:
        """Days on/after `since` where `metric`'s tally exceeds what's already
        been charged, for one user. See the old single-tenant docstring (git
        history) for why `since` matters — unbilled pre-feature backlog."""
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    db.metric_days.c.day, db.metric_days.c.count,
                    db.penalty_days.c.tz,
                    func.coalesce(db.penalty_days.c.charged_count, 0),
                )
                .select_from(
                    db.metric_days.outerjoin(
                        db.penalty_days,
                        (db.penalty_days.c.day == db.metric_days.c.day)
                        & (db.penalty_days.c.user_id == db.metric_days.c.user_id),
                    )
                )
                .where(
                    db.metric_days.c.user_id == user_id,
                    db.metric_days.c.metric == metric,
                    db.metric_days.c.day >= since,
                    db.metric_days.c.count > func.coalesce(db.penalty_days.c.charged_count, 0),
                )
            ).all()
        return [
            {"day": day, "count": count, "tz": tz, "charged_count": charged}
            for day, count, tz, charged in rows
        ]

    # ── access requests (sign-in gate's "request access" form; pre-auth) ──
    def save_access_request(self, rid: str, name: str, email: str, message: str,
                             created_at: int) -> None:
        with self.lock, self.engine.begin() as conn:
            conn.execute(db.access_requests.insert().values(
                id=rid, name=name, email=email, message=message, created_at=created_at,
            ))

    def list_access_requests(self) -> list[dict[str, Any]]:
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(
                select(db.access_requests).order_by(db.access_requests.c.created_at.desc())
            ).mappings().all()
        return [dict(r) for r in rows]

    # ── OTP codes (hashed; one active code per email — pre-auth) ──────────
    def last_otp_created(self, email: str) -> int | None:
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(db.otp_codes.c.created_at).where(db.otp_codes.c.email == email)
            ).first()
        return row[0] if row else None

    def save_otp(self, email: str, code_hash: str, created_at: int, expires_at: int) -> None:
        with self.lock, self.engine.begin() as conn:
            conn.execute(delete(db.otp_codes).where(db.otp_codes.c.expires_at <= created_at))
            conn.execute(delete(db.otp_codes).where(db.otp_codes.c.email == email))
            conn.execute(db.otp_codes.insert().values(
                email=email, code_hash=code_hash, attempts=0,
                created_at=created_at, expires_at=expires_at,
            ))

    def consume_otp(self, email: str, code_hash: str, max_attempts: int) -> bool:
        """True and delete on a correct code. A wrong guess burns an attempt;
        the code is deleted outright once max_attempts is reached."""
        now = int(time.time() * 1000)
        with self.lock, self.engine.begin() as conn:
            row = conn.execute(
                select(db.otp_codes.c.code_hash, db.otp_codes.c.attempts)
                .where(db.otp_codes.c.email == email, db.otp_codes.c.expires_at > now)
            ).first()
            if row is None:
                return False
            stored_hash, attempts = row
            if hmac.compare_digest(stored_hash, code_hash):
                conn.execute(delete(db.otp_codes).where(db.otp_codes.c.email == email))
                return True
            if attempts + 1 >= max_attempts:
                conn.execute(delete(db.otp_codes).where(db.otp_codes.c.email == email))
            else:
                conn.execute(
                    update(db.otp_codes)
                    .where(db.otp_codes.c.email == email)
                    .values(attempts=attempts + 1)
                )
            return False

    # ── sessions (token stored hashed; point at a user, not an email) ─────
    def save_session(self, token_hash: str, user_id: str, expires_at: int,
                     device_id: str | None = None) -> None:
        now = int(time.time() * 1000)
        with self.lock, self.engine.begin() as conn:
            conn.execute(delete(db.sessions).where(db.sessions.c.expires_at <= now))
            conn.execute(db.sessions.insert().values(
                token_hash=token_hash, user_id=user_id, expires_at=expires_at,
                device_id=device_id, created_at=now,
            ))

    def delete_session(self, token_hash: str) -> None:
        with self.lock, self.engine.begin() as conn:
            conn.execute(delete(db.sessions).where(db.sessions.c.token_hash == token_hash))

    def get_session(self, token_hash: str) -> dict[str, Any] | None:
        now = int(time.time() * 1000)
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(db.sessions.c.user_id, db.sessions.c.expires_at)
                .where(db.sessions.c.token_hash == token_hash, db.sessions.c.expires_at > now)
            ).first()
        return {"user_id": row[0], "expires_at": row[1]} if row else None

    # ── device tracking ──────────────────────────────────────────────────
    def create_device(self, user_id: str, name: str, user_agent: str | None = None,
                      ip_address: str | None = None) -> str:
        device_id = "d_" + uuid.uuid4().hex[:12]
        now = int(time.time() * 1000)
        with self.lock, self.engine.connect() as conn:
            conn.execute(
                db.devices.insert().values(
                    id=device_id, user_id=user_id, name=name,
                    user_agent=user_agent, ip_address=ip_address,
                    created_at=now, last_seen_at=now
                )
            )
            conn.commit()
        return device_id

    def list_devices(self, user_id: str) -> list[dict[str, Any]]:
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(
                select(db.devices.c.id, db.devices.c.name, db.devices.c.user_agent,
                       db.devices.c.ip_address, db.devices.c.created_at, db.devices.c.last_seen_at)
                .where(db.devices.c.user_id == user_id)
                .order_by(db.devices.c.last_seen_at.desc())
            ).all()
        return [{"id": r[0], "name": r[1], "user_agent": r[2], "ip_address": r[3],
                 "created_at": r[4], "last_seen_at": r[5]} for r in rows]

    def delete_device(self, user_id: str, device_id: str) -> bool:
        with self.lock, self.engine.connect() as conn:
            result = conn.execute(
                delete(db.devices).where(
                    db.devices.c.user_id == user_id, db.devices.c.id == device_id
                )
            )
            conn.commit()
        return result.rowcount > 0

    def delete_all_devices(self, user_id: str) -> int:
        with self.lock, self.engine.connect() as conn:
            result = conn.execute(
                delete(db.devices).where(db.devices.c.user_id == user_id)
            )
            conn.commit()
        return result.rowcount

    def update_device_last_seen(self, device_id: str) -> None:
        now = int(time.time() * 1000)
        with self.lock, self.engine.connect() as conn:
            conn.execute(
                update(db.devices).where(db.devices.c.id == device_id)
                .values(last_seen_at=now)
            )
            conn.commit()

    # ── audit logging ────────────────────────────────────────────────────
    def log_audit(self, user_id: str, action: str, resource_type: str | None = None,
                  resource_id: str | None = None, details: dict | None = None,
                  ip_address: str | None = None, user_agent: str | None = None) -> None:
        log_id = "al_" + uuid.uuid4().hex[:12]
        now = int(time.time() * 1000)
        with self.lock, self.engine.connect() as conn:
            conn.execute(
                db.audit_logs.insert().values(
                    id=log_id, user_id=user_id, action=action,
                    resource_type=resource_type, resource_id=resource_id,
                    details=json.dumps(details) if details else None,
                    ip_address=ip_address, user_agent=user_agent,
                    created_at=now
                )
            )
            conn.commit()

    def list_audit_logs(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(
                select(db.audit_logs.c.id, db.audit_logs.c.action,
                       db.audit_logs.c.resource_type, db.audit_logs.c.resource_id,
                       db.audit_logs.c.details, db.audit_logs.c.created_at)
                .where(db.audit_logs.c.user_id == user_id)
                .order_by(db.audit_logs.c.created_at.desc())
                .limit(limit)
            ).all()
        return [{"id": r[0], "action": r[1], "resource_type": r[2], "resource_id": r[3],
                 "details": json.loads(r[4]) if r[4] else None, "created_at": r[5]} for r in rows]

    # ── data export (compliance) ─────────────────────────────────────────
    def export_user_data(self, user_id: str) -> dict[str, Any]:
        with self.lock, self.engine.connect() as conn:
            user_row = conn.execute(
                select(db.users.c.id, db.users.c.email, db.users.c.timezone,
                       db.users.c.created_at)
                .where(db.users.c.id == user_id)
            ).first()
            if not user_row:
                return {}

            commitments = conn.execute(
                select(db.commitments.c.data)
                .where(db.commitments.c.user_id == user_id)
            ).all()

            metric_days = conn.execute(
                select(db.metric_days.c.metric, db.metric_days.c.day, db.metric_days.c.count)
                .where(db.metric_days.c.user_id == user_id)
            ).all()

            charges = conn.execute(
                select(db.charges.c.id, db.charges.c.commitment_id, db.charges.c.amount,
                       db.charges.c.kind, db.charges.c.status, db.charges.c.created_at)
                .where(db.charges.c.user_id == user_id)
            ).all()

            settings = conn.execute(
                select(db.user_settings.c.data)
                .where(db.user_settings.c.user_id == user_id)
            ).first()

        return {
            "user": {
                "id": user_row[0],
                "email": user_row[1],
                "timezone": user_row[2],
                "created_at": user_row[3],
                "exported_at": int(time.time() * 1000),
            },
            "commitments": [json.loads(c[0]) for c in commitments],
            "metrics": [{"metric": m[0], "day": m[1], "count": m[2]} for m in metric_days],
            "charges": [{"id": c[0], "commitment_id": c[1], "amount": c[2],
                        "kind": c[3], "status": c[4], "created_at": c[5]} for c in charges],
            "settings": json.loads(settings[0]) if settings else DEFAULT_USER_SETTINGS,
        }

    # ── charge ledger (outbox pattern) ───────────────────────────────────────
    def create_pending_charge(self, user_id: str, amount: float, kind: str,
                              commitment_id: str | None = None,
                              idempotency_key: str | None = None,
                              note: str | None = None,
                              provider: str = "samvara") -> str:
        """Create a pending charge (outbox pattern: write before external call).
        Idempotent: returns existing charge_id if idempotency_key already exists."""
        # Check per-charge cap before creation
        if amount > cfg.max_charge:
            raise ValueError(
                f"Charge ${amount:.2f} exceeds cap ${cfg.max_charge:.2f}"
            )

        if idempotency_key:
            # Idempotency: return existing charge if key exists
            with self.lock, self.engine.connect() as conn:
                row = conn.execute(
                    select(db.charges.c.id).where(
                        db.charges.c.idempotency_key == idempotency_key
                    )
                ).first()
                if row:
                    return row[0]

        charge_id = "ch_" + uuid.uuid4().hex[:12]
        now = int(time.time() * 1000)
        with self.lock, self.engine.connect() as conn:
            conn.execute(
                db.charges.insert().values(
                    id=charge_id, user_id=user_id, amount=amount, kind=kind,
                    commitment_id=commitment_id, status="pending",
                    provider=provider,
                    idempotency_key=idempotency_key, note=note,
                    created_at=now
                )
            )
            conn.commit()
        return charge_id

    def commit_charge(self, charge_id: str, provider_charge_id: str | None = None) -> None:
        """Move charge from pending to committed (after Beeminder call succeeds)."""
        now = int(time.time() * 1000)
        with self.lock, self.engine.connect() as conn:
            conn.execute(
                update(db.charges).where(db.charges.c.id == charge_id).values(
                    status="committed", provider_charge_id=provider_charge_id,
                    committed_at=now
                )
            )
            conn.commit()

    def set_charge_provider_id(self, charge_id: str, provider_charge_id: str) -> None:
        """Update provider_charge_id without changing status (e.g. for requires_action
        pending charges where webhook will later confirm)."""
        with self.lock, self.engine.connect() as conn:
            conn.execute(
                update(db.charges).where(db.charges.c.id == charge_id).values(
                    provider_charge_id=provider_charge_id
                )
            )
            conn.commit()

    def fail_charge(self, charge_id: str, error_details: str | None = None) -> None:
        """Move charge from pending to failed."""
        with self.lock, self.engine.connect() as conn:
            conn.execute(
                update(db.charges).where(db.charges.c.id == charge_id).values(
                    status="failed", note=error_details
                )
            )
            conn.commit()

    def get_committed_total(self, user_id: str) -> float:
        """Sum of all committed charges for this user."""
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(func.coalesce(func.sum(db.charges.c.amount), 0.0))
                .where(db.charges.c.user_id == user_id,
                       db.charges.c.status == "committed")
            ).first()
        return float(row[0]) if row else 0.0

    def check_aggregate_cap(self, user_id: str, additional_amount: float = 0.0) -> bool:
        """Return True if (existing committed + additional_amount) would exceed cap.
        Used for enforcement: reject if would exceed limit."""
        # For now, no aggregate cap (only per-charge cap). Can add configurable
        # limit later if needed (e.g., "max $X per day/month").
        return False

    def get_pending_charges(self, user_id: str) -> list[dict[str, Any]]:
        """Return all pending charges for retry/recovery."""
        with self.lock, self.engine.connect() as conn:
            rows = conn.execute(
                select(db.charges.c.id, db.charges.c.commitment_id, db.charges.c.amount,
                       db.charges.c.kind, db.charges.c.idempotency_key, db.charges.c.created_at)
                .where(db.charges.c.user_id == user_id, db.charges.c.status == "pending")
                .order_by(db.charges.c.created_at.asc())
            ).all()
        return [{"id": r[0], "commitment_id": r[1], "amount": r[2],
                 "kind": r[3], "idempotency_key": r[4], "created_at": r[5]} for r in rows]

    def get_charge_by_provider_id(self, provider_charge_id: str,
                                   provider: str = "samvara") -> dict[str, Any] | None:
        """Look up a pending charge by payment_intent_id (used for webhook)."""
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(db.charges.c.id, db.charges.c.user_id, db.charges.c.amount,
                       db.charges.c.status, db.charges.c.created_at)
                .where(db.charges.c.provider_charge_id == provider_charge_id,
                       db.charges.c.provider == provider,
                       db.charges.c.status == "pending")
            ).first()
        if not row:
            return None
        return {
            "id": row[0], "user_id": row[1], "amount": row[2],
            "status": row[3], "created_at": row[4]
        }

    def create_notification(self, user_id: str, notif_type: str, title: str, message: str,
                           data: dict[str, Any] | None = None) -> str:
        """Create a notification for the user."""
        nid = "n_" + uuid.uuid4().hex[:12]
        now = int(time.time() * 1000)
        with self.lock, self.engine.begin() as conn:
            conn.execute(
                db.notifications.insert().values(
                    id=nid,
                    user_id=user_id,
                    type=notif_type,
                    title=title,
                    message=message,
                    read=False,
                    data=json.dumps(data) if data else None,
                    created_at=now
                )
            )
        return nid

    def list_notifications(self, user_id: str, unread_only: bool = False,
                          limit: int = 50) -> list[dict[str, Any]]:
        """List notifications for a user, newest first."""
        with self.lock, self.engine.connect() as conn:
            q = select(db.notifications).where(db.notifications.c.user_id == user_id)
            if unread_only:
                q = q.where(db.notifications.c.read == False)
            rows = conn.execute(
                q.order_by(db.notifications.c.created_at.desc()).limit(limit)
            ).all()
        return [{"id": r[0], "type": r[2], "title": r[3], "message": r[4],
                 "read": r[5], "data": json.loads(r[6]) if r[6] else None,
                 "created_at": r[7]} for r in rows]

    def get_notification(self, user_id: str, notification_id: str) -> dict[str, Any] | None:
        """Get a single notification by id."""
        with self.lock, self.engine.connect() as conn:
            row = conn.execute(
                select(db.notifications).where(
                    db.notifications.c.id == notification_id,
                    db.notifications.c.user_id == user_id
                )
            ).first()
        if not row:
            return None
        return {"id": row[0], "type": row[2], "title": row[3], "message": row[4],
                "read": row[5], "data": json.loads(row[6]) if row[6] else None,
                "created_at": row[7]}

    def mark_notification_read(self, user_id: str, notification_id: str) -> bool:
        """Mark a notification as read. Returns True if found, False otherwise."""
        with self.lock, self.engine.begin() as conn:
            result = conn.execute(
                update(db.notifications)
                .where(db.notifications.c.id == notification_id,
                       db.notifications.c.user_id == user_id)
                .values(read=True)
            )
        return result.rowcount > 0

    def mark_all_notifications_read(self, user_id: str) -> int:
        """Mark all notifications for a user as read. Returns count of updated rows."""
        with self.lock, self.engine.begin() as conn:
            result = conn.execute(
                update(db.notifications)
                .where(db.notifications.c.user_id == user_id, db.notifications.c.read == False)
                .values(read=True)
            )
        return result.rowcount


store = Store(db.make_engine())
