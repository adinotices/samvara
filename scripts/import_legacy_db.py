#!/usr/bin/env python3
"""One-time import: the pre-port single-tenant SQLite database -> the
multi-tenant schema, as user #1.

This is NOT an Alembic migration. Alembic manages schema evolution from a
known state going forward (see migrations/versions/..._multi_tenant_schema.py);
the pre-port database was raw sqlite3 with no migration tooling and a
completely different shape (one un-keyed commitments table, a single-row
settings blob, no users table at all) — reading that needs a bespoke script,
not a schema diff.

What it does:
  1. Reads every commitment, metric_days row, penalty_days row, and the
     settings blob out of the OLD database file directly (raw sqlite3 — the
     old schema, not app.db's tables).
  2. Creates (or reuses) one user for --owner-email in the NEW database
     (already migrated to head — run `alembic upgrade head` against it
     first).
  3. Re-inserts every row with that user's id attached.

Safe to re-run: it refuses to import into a target that already has data for
that email (use --force to override, which still won't duplicate rows within
a single run, but WILL duplicate them across two runs against the same
non-empty target — this is an import tool for a one-time cutover, not a sync).

Usage:
    cd backend
    DATABASE_URL=postgresql+psycopg://... python3 ../scripts/import_legacy_db.py \\
        --old-db /path/to/old/samvara.db --owner-email you@example.com

Dry-run first (prints what it would do, touches nothing):
    ... --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from app import db as app_db  # noqa: E402
from app.config import settings  # noqa: E402


def read_old_db(path: str) -> dict:
    conn = sqlite3.connect(path)
    try:
        commitments = [
            json.loads(r[0]) for r in
            conn.execute("SELECT data FROM commitments ORDER BY seq ASC").fetchall()
        ]
        metric_days = conn.execute(
            "SELECT metric, day, count FROM metric_days"
        ).fetchall()
        penalty_days = conn.execute(
            "SELECT day, tz, charged_count FROM penalty_days"
        ).fetchall()
        settings_row = conn.execute("SELECT v FROM kv WHERE k='settings'").fetchone()
        settings_data = json.loads(settings_row[0]) if settings_row else None
        return {
            "commitments": commitments,
            "metric_days": metric_days,
            "penalty_days": penalty_days,
            "settings": settings_data,
        }
    finally:
        conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--old-db", required=True, help="Path to the pre-port SQLite file")
    p.add_argument("--owner-email", required=True, help="Email to create/reuse as user #1")
    p.add_argument("--timezone", default=None, help="Defaults to METRICS_TZ from the environment")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="Import even if this user already has commitments")
    args = p.parse_args()

    if not os.path.exists(args.old_db):
        print(f"error: {args.old_db} does not exist", file=sys.stderr)
        return 1

    old = read_old_db(args.old_db)
    print(f"Read from {args.old_db}:")
    print(f"  {len(old['commitments'])} commitments")
    print(f"  {len(old['metric_days'])} metric_days rows")
    print(f"  {len(old['penalty_days'])} penalty_days rows")
    print(f"  settings: {old['settings']}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    tz = args.timezone or settings.metrics_tz
    engine = app_db.make_engine()
    app_db.metadata.create_all(engine)  # in case `alembic upgrade head` wasn't run first

    with engine.begin() as conn:
        from sqlalchemy import select

        row = conn.execute(
            select(app_db.users).where(app_db.users.c.email == args.owner_email)
        ).mappings().first()
        if row is None:
            import uuid
            uid = "u_" + uuid.uuid4().hex[:12]
            now = int(time.time() * 1000)
            conn.execute(app_db.users.insert().values(
                id=uid, email=args.owner_email, created_at=now,
                timezone=tz, status="active", deleted_at=None,
            ))
            print(f"Created user {uid} ({args.owner_email})")
        else:
            uid = row["id"]
            print(f"Reusing existing user {uid} ({args.owner_email})")

        existing = conn.execute(
            select(app_db.commitments.c.id).where(app_db.commitments.c.user_id == uid)
        ).first()
        if existing and not args.force:
            print(f"error: user {uid} already has commitments in the target database. "
                  "Pass --force to import anyway (this will NOT dedupe against a prior "
                  "run — only run this once per target).", file=sys.stderr)
            return 1

        for seq, cm in enumerate(old["commitments"], start=1):
            conn.execute(app_db.commitments.insert().values(
                id=cm["id"], user_id=uid, seq=seq, data=json.dumps(cm),
            ))
        for metric, day, count in old["metric_days"]:
            conn.execute(app_db.metric_days.insert().values(
                user_id=uid, metric=metric, day=day, count=count,
            ))
        for day, tz_name, charged_count in old["penalty_days"]:
            conn.execute(app_db.penalty_days.insert().values(
                user_id=uid, day=day, tz=tz_name, charged_count=charged_count,
            ))
        settings_data = old["settings"] or {"apiBaseUrl": "", "recipient": "Beeminder", "totalCharged": 0}
        existing_settings = conn.execute(
            select(app_db.user_settings.c.user_id).where(app_db.user_settings.c.user_id == uid)
        ).first()
        if existing_settings:
            from sqlalchemy import update
            conn.execute(
                update(app_db.user_settings).where(app_db.user_settings.c.user_id == uid)
                .values(data=json.dumps(settings_data))
            )
        else:
            conn.execute(app_db.user_settings.insert().values(
                user_id=uid, data=json.dumps(settings_data),
            ))

    print(f"\nImported {len(old['commitments'])} commitments, "
          f"{len(old['metric_days'])} metric_days, {len(old['penalty_days'])} penalty_days "
          f"into user {uid}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
