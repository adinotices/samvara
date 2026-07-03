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

    def get_session(self, token_hash: str) -> dict[str, Any] | None:
        now = int(time.time() * 1000)
        with self.lock:
            row = self._conn.execute(
                "SELECT email, expires_at FROM sessions WHERE token_hash=? AND expires_at>?",
                (token_hash, now),
            ).fetchone()
        return {"email": row[0], "expires_at": row[1]} if row else None


store = Store(cfg.db_path)
