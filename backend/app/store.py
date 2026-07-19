"""Persistence.

A tiny store behind a narrow interface so you can swap SQLite for Postgres or
anything else later without touching route or domain code. SQLite is the
default: zero-infrastructure, durable, handles its own locking, trivial to
back up (copy the file), and portable to any host with a writable volume.

Each commitment is stored as one row with JSON blobs for the rung and history;
settings live in a single-row JSON document. A process-level lock serializes
read-modify-write cycles so a user action and the scheduled /tick can't clobber
each other. Run the API with a single worker (see the Dockerfile CMD).
"""
from __future__ import annotations

import hmac
import json
import sqlite3
import threading
import time
from typing import Any

from .config import settings as cfg
from .ratchet import Commitment

DEFAULT_SETTINGS = {"apiBaseUrl": "", "recipient": "Beeminder", "totalCharged": 0}


class Store:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.lock, self._conn:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS commitments (
                       id        TEXT PRIMARY KEY,
                       seq       INTEGER,
                       data      TEXT NOT NULL
                   )"""
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)"
            )
            # OTPs and session tokens are stored as SHA-256 hashes so a copied
            # database file doesn't hand out live credentials.
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS otp_codes (
                       email      TEXT PRIMARY KEY,
                       code_hash  TEXT NOT NULL,
                       attempts   INTEGER NOT NULL DEFAULT 0,
                       created_at INTEGER NOT NULL,
                       expires_at INTEGER NOT NULL
                   )"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS sessions (
                       token_hash TEXT PRIMARY KEY,
                       email      TEXT NOT NULL,
                       expires_at INTEGER NOT NULL
                   )"""
            )
            # Daily tally per tracked metric (the Data tab). One row per
            # metric per local day; day is YYYY-MM-DD in the configured tz.
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS metric_days (
                       metric TEXT NOT NULL,
                       day    TEXT NOT NULL,
                       count  INTEGER NOT NULL DEFAULT 0,
                       PRIMARY KEY (metric, day)
                   )"""
            )
            # End-of-day Beeminder penalty bookkeeping for the "goal broken"
            # tally. One row per day: which tz decides when that day closes,
            # and how much of that day's count has already been charged (so
            # the tick sweep only ever bills the *new* delta).
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS penalty_days (
                       day           TEXT PRIMARY KEY,
                       tz            TEXT NOT NULL,
                       charged_count INTEGER NOT NULL DEFAULT 0
                   )"""
            )
            row = self._conn.execute("SELECT v FROM kv WHERE k='settings'").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO kv (k, v) VALUES ('settings', ?)",
                    (json.dumps(DEFAULT_SETTINGS),),
                )

    # ── commitments ──────────────────────────────────────────────────────
    def list_commitments(self) -> list[Commitment]:
        with self.lock:
            rows = self._conn.execute(
                "SELECT data FROM commitments ORDER BY seq ASC"
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get_commitment(self, cid: str) -> Commitment | None:
        with self.lock:
            row = self._conn.execute(
                "SELECT data FROM commitments WHERE id=?", (cid,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def insert_commitment(self, cm: Commitment) -> None:
        with self.lock, self._conn:
            seq = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM commitments"
            ).fetchone()[0]
            self._conn.execute(
                "INSERT INTO commitments (id, seq, data) VALUES (?, ?, ?)",
                (cm["id"], seq, json.dumps(cm)),
            )

    def update_commitment(self, cm: Commitment) -> None:
        with self.lock, self._conn:
            self._conn.execute(
                "UPDATE commitments SET data=? WHERE id=?",
                (json.dumps(cm), cm["id"]),
            )

    # ── settings ─────────────────────────────────────────────────────────
    def get_settings(self) -> dict[str, Any]:
        with self.lock:
            row = self._conn.execute("SELECT v FROM kv WHERE k='settings'").fetchone()
        return json.loads(row[0]) if row else dict(DEFAULT_SETTINGS)

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self.lock, self._conn:
            cur = self.get_settings()
            cur.update({k: v for k, v in patch.items() if v is not None})
            self._conn.execute(
                "UPDATE kv SET v=? WHERE k='settings'", (json.dumps(cur),)
            )
        return cur

    def add_total_charged(self, amount: float) -> None:
        with self.lock, self._conn:
            cur = self.get_settings()
            cur["totalCharged"] = round(cur.get("totalCharged", 0) + amount, 2)
            self._conn.execute(
                "UPDATE kv SET v=? WHERE k='settings'", (json.dumps(cur),)
            )

    # ── daily metric tallies (the Data tab) ──────────────────────────────
    def bump_metric(self, metric: str, day: str, delta: int) -> int:
        """Add `delta` to a metric's tally for `day`, floored at 0.

        Returns the new count. The floor means a stray −1 on an empty day
        stays 0 rather than going negative."""
        with self.lock, self._conn:
            row = self._conn.execute(
                "SELECT count FROM metric_days WHERE metric=? AND day=?",
                (metric, day),
            ).fetchone()
            new = max(0, (row[0] if row else 0) + delta)
            self._conn.execute(
                "INSERT OR REPLACE INTO metric_days (metric, day, count) VALUES (?, ?, ?)",
                (metric, day, new),
            )
        return new

    def metric_series(self) -> dict[str, dict[str, int]]:
        """{metric: {day: count}} for every recorded day (zeros included)."""
        with self.lock:
            rows = self._conn.execute(
                "SELECT metric, day, count FROM metric_days ORDER BY day ASC"
            ).fetchall()
        out: dict[str, dict[str, int]] = {}
        for metric, day, count in rows:
            out.setdefault(metric, {})[day] = count
        return out

    def metric_count(self, metric: str, day: str) -> int:
        with self.lock:
            row = self._conn.execute(
                "SELECT count FROM metric_days WHERE metric=? AND day=?", (metric, day)
            ).fetchone()
        return row[0] if row else 0

    # ── end-of-day penalty bookkeeping ────────────────────────────────────
    def upsert_penalty_tz(self, day: str, tz: str) -> None:
        """Record which tz's midnight should close out `day`'s penalty.

        Last write wins: if the device's tz changes mid-day (e.g. travel),
        the most recent tap decides when the day closes."""
        with self.lock, self._conn:
            self._conn.execute(
                """INSERT INTO penalty_days (day, tz, charged_count) VALUES (?, ?, 0)
                   ON CONFLICT(day) DO UPDATE SET tz=excluded.tz""",
                (day, tz),
            )

    def get_penalty_day(self, day: str) -> dict[str, Any] | None:
        with self.lock:
            row = self._conn.execute(
                "SELECT tz, charged_count FROM penalty_days WHERE day=?", (day,)
            ).fetchone()
        return {"tz": row[0], "charged_count": row[1]} if row else None

    def mark_penalty_charged(self, day: str, charged_count: int) -> None:
        with self.lock, self._conn:
            self._conn.execute(
                "UPDATE penalty_days SET charged_count=? WHERE day=?",
                (charged_count, day),
            )

    def pending_penalties(self, metric: str, since: str) -> list[dict[str, Any]]:
        """Days on/after `since` where `metric`'s tally exceeds what's already
        been charged.

        The `since` floor matters for any metric that was tracked before it
        started carrying a financial penalty: those older days have a
        metric_days row but no penalty_days row (nothing ever charged them),
        so COALESCE(pd.charged_count, 0) reads as 0 and — without the floor —
        they'd look identical to genuine new backlog and get billed in full
        the moment the sweep first runs.
        """
        with self.lock:
            rows = self._conn.execute(
                """SELECT md.day, md.count, pd.tz, COALESCE(pd.charged_count, 0)
                       FROM metric_days md LEFT JOIN penalty_days pd ON pd.day = md.day
                       WHERE md.metric = ? AND md.day >= ?
                         AND md.count > COALESCE(pd.charged_count, 0)""",
                (metric, since),
            ).fetchall()
        return [
            {"day": day, "count": count, "tz": tz, "charged_count": charged}
            for day, count, tz, charged in rows
        ]

    # ── OTP codes (hashed; one active code per email) ─────────────────────
    def last_otp_created(self, email: str) -> int | None:
        """When the current code for this email was issued (for send cooldown)."""
        with self.lock:
            row = self._conn.execute(
                "SELECT created_at FROM otp_codes WHERE email=?", (email,)
            ).fetchone()
        return row[0] if row else None

    def save_otp(self, email: str, code_hash: str, created_at: int, expires_at: int) -> None:
        with self.lock, self._conn:
            self._conn.execute("DELETE FROM otp_codes WHERE expires_at<=?", (created_at,))
            self._conn.execute(
                "INSERT OR REPLACE INTO otp_codes (email, code_hash, attempts, created_at, expires_at)"
                " VALUES (?, ?, 0, ?, ?)",
                (email, code_hash, created_at, expires_at),
            )

    def consume_otp(self, email: str, code_hash: str, max_attempts: int) -> bool:
        """True and delete on a correct code. A wrong guess burns an attempt;
        the code is deleted outright once max_attempts is reached, so a
        6-digit code can never be brute-forced within its lifetime."""
        now = int(time.time() * 1000)
        with self.lock, self._conn:
            row = self._conn.execute(
                "SELECT code_hash, attempts FROM otp_codes WHERE email=? AND expires_at>?",
                (email, now),
            ).fetchone()
            if row is None:
                return False
            stored_hash, attempts = row
            if hmac.compare_digest(stored_hash, code_hash):
                self._conn.execute("DELETE FROM otp_codes WHERE email=?", (email,))
                return True
            if attempts + 1 >= max_attempts:
                self._conn.execute("DELETE FROM otp_codes WHERE email=?", (email,))
            else:
                self._conn.execute(
                    "UPDATE otp_codes SET attempts=attempts+1 WHERE email=?", (email,)
                )
            return False

    # ── sessions (token stored hashed) ────────────────────────────────────
    def save_session(self, token_hash: str, email: str, expires_at: int) -> None:
        now = int(time.time() * 1000)
        with self.lock, self._conn:
            self._conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            self._conn.execute(
                "INSERT INTO sessions (token_hash, email, expires_at) VALUES (?, ?, ?)",
                (token_hash, email, expires_at),
            )

    def delete_session(self, token_hash: str) -> None:
        with self.lock, self._conn:
            self._conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    def get_session(self, token_hash: str) -> dict[str, Any] | None:
        now = int(time.time() * 1000)
        with self.lock:
            row = self._conn.execute(
                "SELECT email, expires_at FROM sessions WHERE token_hash=? AND expires_at>?",
                (token_hash, now),
            ).fetchone()
        return {"email": row[0], "expires_at": row[1]} if row else None


store = Store(cfg.db_path)
