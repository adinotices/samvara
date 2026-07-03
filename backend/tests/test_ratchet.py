"""Parity tests: the server ratchet must behave exactly like the frontend mock.

Run with:  cd backend && python -m pytest -q      (or: python tests/test_ratchet.py)

These pin the semantics the UI was built against. If one breaks, the frontend
and backend have diverged and the app will misbehave in a money-moving way.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ratchet  # noqa: E402

DAY_MS = ratchet.DAY_MS


def _base(days=3, stake=5.0):
    cm = ratchet.new_commitment("Test", days, stake)
    return cm


# ── suggestion + clamps ──────────────────────────────────────────────────────
def test_suggest_next_rung_is_plus_one():
    assert ratchet.suggest_next_rung(1) == 2
    assert ratchet.suggest_next_rung(9) == 10


def test_create_clamps_to_minimums():
    cm = ratchet.new_commitment("  ", 0, 0)
    assert cm["base_days"] == 1
    assert cm["base_stake"] == 1.0
    assert cm["name"] == "Untitled commitment"
    assert cm["current_rung"]["days"] == 1


# ── clean success: +1 day, stake held, no charge ─────────────────────────────
def test_confirm_clean_then_choose_next_advances_day_holds_stake():
    cm = _base(3, 5.0)
    ratchet.apply_confirm_clean(cm)
    r = cm["current_rung"]
    assert r["completed"] and r["awaiting_decision"]
    assert cm["history"][-1] == {
        "days": 3, "stake": 5.0, "outcome": "success",
        "settled": cm["history"][-1]["settled"],
    }
    # UI's default next choice is suggestNextRung(days)=days+1 at same stake.
    ratchet.apply_choose_next(cm, ratchet.suggest_next_rung(r["days"]), r["stake"])
    nr = cm["current_rung"]
    assert nr["days"] == 4 and nr["stake"] == 5.0
    assert not nr["completed"] and not nr["awaiting_decision"]


# ── slip: same length, +$1 stake by default; charge == current stake ─────────
def test_slip_holds_length_raises_stake_by_default():
    cm = _base(5, 6.0)
    cur = cm["current_rung"]
    new_days, new_stake = ratchet.resolve_recommit(cur, True, None, None)
    assert new_days == 5 and new_stake == 7.0  # length held, +$1
    charged = cur["stake"]
    ratchet.apply_slip(cm, new_days, new_stake, charged, outcome="lapse")
    assert cm["history"][-1]["outcome"] == "lapse"
    assert cm["history"][-1]["stake"] == 6.0  # charged the OLD stake
    assert cm["current_rung"]["days"] == 5 and cm["current_rung"]["stake"] == 7.0


def test_slip_raise_false_keeps_stake():
    cm = _base(4, 8.0)
    d, s = ratchet.resolve_recommit(cm["current_rung"], False, None, None)
    assert d == 4 and s == 8.0


def test_slip_explicit_overrides():
    cm = _base(4, 8.0)
    d, s = ratchet.resolve_recommit(cm["current_rung"], True, 10, 20)
    assert d == 10 and s == 20.0


def test_miss_outcome_label():
    cm = _base(3, 5.0)
    ratchet.apply_slip(cm, 3, 6.0, 5.0, outcome="missed")
    assert cm["history"][-1]["outcome"] == "missed"


# ── auto-miss: idempotent, parks awaiting recommit, no new rung ──────────────
def test_auto_miss_charges_once_and_parks():
    cm = _base(4, 6.0)
    did = ratchet.apply_auto_miss(cm, 6.0)
    assert did is True
    r = cm["current_rung"]
    assert r["auto_missed"] and r["awaiting_recommit"]
    assert r["charged_amount"] == 6.0
    assert r["days"] == 4  # same rung, not advanced
    assert cm["history"][-1]["outcome"] == "missed"
    # second call is a no-op (no double charge)
    assert ratchet.apply_auto_miss(cm, 6.0) is False
    assert len([h for h in cm["history"] if h["outcome"] == "missed"]) == 1


def test_auto_miss_skips_completed():
    cm = _base(3, 5.0)
    ratchet.apply_confirm_clean(cm)
    assert ratchet.apply_auto_miss(cm, 5.0) is False


# ── grace gate ───────────────────────────────────────────────────────────────
def test_is_past_grace_respects_window_and_flags():
    cm = _base(1, 5.0)
    r = cm["current_rung"]
    due_ms = ratchet.grace_end_ms(r, 0)  # == due
    grace_ms = 24 * 60 * 60 * 1000
    assert ratchet.is_past_grace(cm, grace_ms, at_ms=due_ms + grace_ms - 1) is False
    assert ratchet.is_past_grace(cm, grace_ms, at_ms=due_ms + grace_ms + 1) is True
    # once parked, never past-grace again
    ratchet.apply_auto_miss(cm, 5.0)
    assert ratchet.is_past_grace(cm, grace_ms, at_ms=due_ms + grace_ms + 10**9) is False


# ── ISO formats match JS exactly ─────────────────────────────────────────────
def test_iso_ms_shape():
    s = ratchet.iso_ms(0)
    assert s == "1970-01-01T00:00:00.000Z"


def test_iso_date_shape():
    assert ratchet.iso_date(0) == "1970-01-01"


def test_due_is_start_plus_days():
    r = ratchet.make_rung(3, 5.0, 0)
    assert r["start"] == "1970-01-01T00:00:00.000Z"
    assert r["due"] == ratchet.iso_ms(3 * DAY_MS)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
