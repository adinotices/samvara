"""Pure ratchet domain logic.

This is a faithful server-side port of the semantics in
frontend/api-client.js (the reference mock the UI was built against). The
rules are deliberately identical so the real backend is a drop-in:

  * A CLEAN success advances the rung length by +1 day and holds the stake.
  * A SLIP / MISS keeps the same length and raises the stake by $1 (default,
    overridable). It NEVER shortens the rung.
  * suggestNextRung(days) == days + 1.
  * When the grace window expires with no response, the stake is auto-charged
    and the commitment is PARKED awaiting a deliberate recommit. It never
    recommits on its own.

Nothing here performs I/O. Charging and persistence are wired in main.py so
this module stays trivially testable.
"""
from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Any

DAY_MS = 24 * 60 * 60 * 1000
HOUR_MS = 60 * 60 * 1000

Commitment = dict[str, Any]
Rung = dict[str, Any]


# ── time helpers (match JS Date.toISOString / .slice(0,10)) ───────────────────
def now_ms() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)


def iso_ms(ms: int) -> str:
    """ISO-8601 with milliseconds and a trailing Z, e.g. 2024-05-01T12:00:00.000Z.

    Matches JavaScript's Date.prototype.toISOString so both sides parse
    identically.
    """
    d = dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(d.microsecond / 1000):03d}Z"


def iso_date(ms: int) -> str:
    """Date-only string YYYY-MM-DD (matches the mock's `settled` field)."""
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).date().isoformat()


def new_id() -> str:
    return "c_" + uuid.uuid4().hex[:7]


# ── construction ──────────────────────────────────────────────────────────────
def make_rung(days: int, stake: float, start_ms: int, **opts: Any) -> Rung:
    return {
        "days": days,
        "stake": stake,
        "start": iso_ms(start_ms),
        "due": iso_ms(start_ms + days * DAY_MS),
        "completed": opts.get("completed", False),
        "awaiting_decision": opts.get("awaiting_decision", False),
        "awaiting_recommit": opts.get("awaiting_recommit", False),
        "auto_missed": opts.get("auto_missed", False),
        "charged_amount": opts.get("charged_amount", 0),
    }


def clamp_days(v: Any, default: int = 1) -> int:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    # Infinity/NaN survive float() and would poison due-date arithmetic.
    if not math.isfinite(f):
        return default
    return max(1, round(f))


def clamp_stake(v: Any, default: float = 1.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return max(1.0, f)


def new_commitment(name: str, base_days: Any, base_stake: Any) -> Commitment:
    bd = clamp_days(base_days)
    bs = clamp_stake(base_stake)
    return {
        "id": new_id(),
        "name": (str(name).strip() or "Untitled commitment"),
        "base_days": bd,
        "base_stake": bs,
        "current_rung": make_rung(bd, bs, now_ms()),
        "history": [],
    }


# ── pure suggestion / grace (kept identical to the client so both agree) ──────
def suggest_next_rung(days: int) -> int:
    return days + 1


def grace_end_ms(rung: Rung, grace_ms: int) -> int:
    return int(dt.datetime.fromisoformat(rung["due"].replace("Z", "+00:00")).timestamp() * 1000) + grace_ms


# ── recommit-target resolution (slip / miss) ─────────────────────────────────
def resolve_recommit(cur: Rung, raise_: bool, days: Any, stake: Any) -> tuple[int, float]:
    new_days = clamp_days(days) if days is not None else cur["days"]
    if stake is not None:
        new_stake = clamp_stake(stake)
    else:
        new_stake = cur["stake"] + 1 if raise_ else cur["stake"]
    return new_days, new_stake


# ── state transitions (no I/O — caller persists + charges) ────────────────────
def apply_slip(cm: Commitment, new_days: int, new_stake: float, charged: float,
               outcome: str = "lapse", at_ms: int | None = None) -> None:
    """Record a slip/miss and recommit to a fresh rung. Mutates `cm` in place.

    `charged` is the amount actually charged (the *current* rung's stake).
    `outcome` is 'lapse' (slip) or 'missed' (miss).
    """
    at = at_ms if at_ms is not None else now_ms()
    cur = cm["current_rung"]
    cm["history"].append({
        "days": cur["days"], "stake": charged, "outcome": outcome, "settled": iso_date(at),
    })
    cm["current_rung"] = make_rung(new_days, new_stake, at)


def apply_auto_miss(cm: Commitment, charged: float, at_ms: int | None = None) -> bool:
    """Grace expired: record a miss, park awaiting recommit. Idempotent.

    Returns True if it charged (i.e. state actually changed), False if the
    commitment was already resolved/parked (no-op, do not charge again).
    """
    r = cm["current_rung"]
    if r["auto_missed"] or r["awaiting_recommit"] or r["awaiting_decision"] or r["completed"]:
        return False
    at = at_ms if at_ms is not None else now_ms()
    cm["history"].append({
        "days": r["days"], "stake": charged, "outcome": "missed", "settled": iso_date(at),
    })
    r["auto_missed"] = True
    r["awaiting_recommit"] = True
    r["charged_amount"] = charged
    return True


def apply_confirm_clean(cm: Commitment, at_ms: int | None = None) -> None:
    """Confirm the rung completed clean: record success, await decision. No charge."""
    at = at_ms if at_ms is not None else now_ms()
    r = cm["current_rung"]
    cm["history"].append({
        "days": r["days"], "stake": r["stake"], "outcome": "success", "settled": iso_date(at),
    })
    r["completed"] = True
    r["awaiting_decision"] = True


def apply_choose_next(cm: Commitment, days: Any, stake: Any, at_ms: int | None = None) -> None:
    """Deliberately start the next rung (always a human action)."""
    at = at_ms if at_ms is not None else now_ms()
    cm["current_rung"] = make_rung(clamp_days(days), clamp_stake(stake), at)


def is_past_grace(cm: Commitment, grace_ms: int, at_ms: int | None = None) -> bool:
    at = at_ms if at_ms is not None else now_ms()
    r = cm["current_rung"]
    if r["completed"] or r["awaiting_decision"] or r["awaiting_recommit"] or r["auto_missed"]:
        return False
    return at > grace_end_ms(r, grace_ms)
