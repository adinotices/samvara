"""Money-path tests at the HTTP layer.

These pin the invariants that make real charges safe to arm:

  * a failed charge leaves stored state completely untouched (402, no ledger
    movement, no history entry),
  * no interleaving of /slip, /miss, /auto-miss and /tick can charge the same
    lapse twice (including a double-clicked confirm),
  * the ledger always balances: sum of charges == totalCharged == sum of
    charged history entries,
  * cap/boundary/garbage-input edges behave predictably.

beeminder.charge is faked in-process, so no network and no money.

Run from backend/:  python -m pytest -q tests/test_money.py
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
import tempfile

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Match test_auth.py exactly: whichever module pytest imports first creates the
# settings/store singletons, so the values must agree for a whole-suite run.
os.environ.setdefault("SAMVARA_DB", os.path.join(tempfile.mkdtemp(), "test-money.db"))
os.environ.setdefault("AUTH_MODE", "token")
os.environ.setdefault("API_TOKEN", "static-cron-token")
os.environ.setdefault("AUTH_EMAIL", "owner@example.com")

from fastapi.testclient import TestClient  # noqa: E402

from app import beeminder, main, ratchet  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.store import store  # noqa: E402

client = TestClient(app)
HDR = {"Authorization": f"Bearer {settings.api_token}"}

CHARGES: list[float] = []  # amounts the fake charge accepted


def _ok_result(amount: float, note: str) -> beeminder.ChargeResult:
    return beeminder.ChargeResult(charged=True, amount=amount, note=note,
                                  beeminder_id="fake", dryrun=False)


def fake_charge(fail_for: set[float] | None = None, delay: float = 0.0):
    """A stand-in for beeminder.charge that records amounts.

    `fail_for`: amounts that raise ChargeError instead (to simulate an outage
    for one commitment but not another). `delay`: widens race windows.
    """
    async def _charge(amount: float, note: str) -> beeminder.ChargeResult:
        if delay:
            await asyncio.sleep(delay)
        if fail_for and amount in fail_for:
            raise beeminder.ChargeError("simulated Beeminder outage")
        CHARGES.append(amount)
        return _ok_result(amount, note)
    return _charge


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    CHARGES.clear()
    main._recent_lapse.clear()
    # asyncio.Lock binds to the first event loop that touches it; each
    # asyncio.run() here is a fresh loop, so give each test a fresh lock.
    monkeypatch.setattr(main, "_charge_lock", asyncio.Lock())
    with store.lock, store._conn:
        store._conn.execute("DELETE FROM commitments")
        store._conn.execute("DELETE FROM metric_days")
        store._conn.execute("DELETE FROM penalty_days")
    store.update_settings({"totalCharged": 0})
    # Debounce off by default so sequential test actions don't trip it; the
    # debounce test switches it back on.
    monkeypatch.setattr(settings, "lapse_debounce_s", 0.0)
    monkeypatch.setattr(settings, "max_charge", 50.0)
    monkeypatch.setattr(settings, "min_stake", 1.0)
    yield


def mk(name="Goal", days=3, stake=5.0) -> dict:
    r = client.post("/v1/commitments", headers=HDR,
                    json={"name": name, "base_days": days, "base_stake": stake})
    assert r.status_code == 200
    return r.json()


def backdate(cid: str) -> None:
    """Rewrite the current rung so its grace window expired an hour ago."""
    cm = store.get_commitment(cid)
    r = cm["current_rung"]
    due = ratchet.now_ms() - settings.grace_ms - ratchet.HOUR_MS
    r["start"] = ratchet.iso_ms(due - r["days"] * ratchet.DAY_MS)
    r["due"] = ratchet.iso_ms(due)
    store.update_commitment(cm)


def total_charged() -> float:
    return client.get("/v1/settings", headers=HDR).json()["totalCharged"]


def snapshot(cid: str) -> dict:
    return client.get(f"/v1/commitments/{cid}", headers=HDR).json()


async def _gather(*reqs):
    """Fire requests concurrently against the app (method, path, json|None)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return await asyncio.gather(
            *(c.request(m, p, json=j, headers=HDR) for m, p, j in reqs))


# ── invariant: charge fails ⇒ state untouched ────────────────────────────────
@pytest.mark.parametrize("action", ["slip", "miss"])
def test_failed_charge_leaves_state_untouched(action, monkeypatch):
    cm = mk(stake=5.0)
    before = snapshot(cm["id"])
    monkeypatch.setattr(beeminder, "charge", fake_charge(fail_for={5.0}))
    r = client.post(f"/v1/commitments/{cm['id']}/{action}", headers=HDR, json={})
    assert r.status_code == 402
    assert snapshot(cm["id"]) == before
    assert total_charged() == 0 and CHARGES == []


def test_failed_charge_on_auto_miss_leaves_state_untouched(monkeypatch):
    cm = mk(stake=5.0)
    backdate(cm["id"])
    before = snapshot(cm["id"])
    monkeypatch.setattr(beeminder, "charge", fake_charge(fail_for={5.0}))
    r = client.post(f"/v1/commitments/{cm['id']}/auto-miss", headers=HDR)
    assert r.status_code == 402
    assert snapshot(cm["id"]) == before
    assert total_charged() == 0


def test_tick_reports_error_and_still_processes_others(monkeypatch):
    a = mk("A", stake=7.0)
    b = mk("B", stake=9.0)
    backdate(a["id"])
    backdate(b["id"])
    a_before = snapshot(a["id"])
    monkeypatch.setattr(beeminder, "charge", fake_charge(fail_for={7.0}))
    out = client.post("/v1/tick", headers=HDR).json()
    # A's outage is isolated: reported, untouched, retried by the next tick.
    assert [e["id"] for e in out["errors"]] == [a["id"]]
    assert snapshot(a["id"]) == a_before
    # B charged and parked despite A's failure.
    assert out["charged_count"] == 1 and out["charged"][0]["id"] == b["id"]
    assert snapshot(b["id"])["current_rung"]["awaiting_recommit"] is True
    assert total_charged() == 9.0 and CHARGES == [9.0]


# ── invariant: no interleaving charges twice ─────────────────────────────────
def test_slip_racing_auto_miss_charges_exactly_once(monkeypatch):
    cm = mk(stake=5.0)
    backdate(cm["id"])
    monkeypatch.setattr(beeminder, "charge", fake_charge(delay=0.05))
    rs = asyncio.run(_gather(
        ("POST", f"/v1/commitments/{cm['id']}/slip", {}),
        ("POST", f"/v1/commitments/{cm['id']}/auto-miss", None)))
    # Whichever wins the lock charges; the loser must be a 409 or a no-op —
    # never a second charge and never a 5xx.
    assert len(CHARGES) == 1
    assert all(r.status_code in (200, 409) for r in rs)
    assert total_charged() == 5.0


def test_double_clicked_slip_charges_exactly_once(monkeypatch):
    cm = mk(stake=5.0)
    monkeypatch.setattr(settings, "lapse_debounce_s", 10.0)
    monkeypatch.setattr(beeminder, "charge", fake_charge(delay=0.05))
    rs = asyncio.run(_gather(
        ("POST", f"/v1/commitments/{cm['id']}/slip", {}),
        ("POST", f"/v1/commitments/{cm['id']}/slip", {})))
    assert sorted(r.status_code for r in rs) == [200, 409]
    assert len(CHARGES) == 1 and total_charged() == 5.0


def test_slip_on_parked_rung_is_409_not_second_charge(monkeypatch):
    cm = mk(stake=5.0)
    backdate(cm["id"])
    monkeypatch.setattr(beeminder, "charge", fake_charge())
    assert client.post(f"/v1/commitments/{cm['id']}/auto-miss", headers=HDR).status_code == 200
    r = client.post(f"/v1/commitments/{cm['id']}/slip", headers=HDR, json={})
    assert r.status_code == 409
    assert CHARGES == [5.0] and total_charged() == 5.0


def test_repeated_ticks_charge_once(monkeypatch):
    cm = mk(stake=5.0)
    backdate(cm["id"])
    monkeypatch.setattr(beeminder, "charge", fake_charge())
    first = client.post("/v1/tick", headers=HDR).json()
    second = client.post("/v1/tick", headers=HDR).json()
    assert first["charged_count"] == 1 and second["charged_count"] == 0
    assert CHARGES == [5.0] and total_charged() == 5.0


def test_auto_miss_before_grace_expiry_is_a_noop(monkeypatch):
    """The client polls /auto-miss on its own clock; the server's clock rules."""
    cm = mk(stake=5.0)  # fresh rung, due days away
    monkeypatch.setattr(beeminder, "charge", fake_charge())
    r = client.post(f"/v1/commitments/{cm['id']}/auto-miss", headers=HDR)
    assert r.status_code == 200
    assert r.json()["current_rung"]["awaiting_recommit"] is False
    assert CHARGES == [] and total_charged() == 0


# ── invariant: the ledger balances ───────────────────────────────────────────
def test_ledger_balances_across_mixed_activity(monkeypatch):
    monkeypatch.setattr(beeminder, "charge", fake_charge())
    a = mk("A", days=3, stake=5.0)
    b = mk("B", days=2, stake=3.0)

    # A: slip ($5, re-rung at $6), then miss with raise=false ($6, re-rung at $6)
    assert client.post(f"/v1/commitments/{a['id']}/slip", headers=HDR,
                       json={}).status_code == 200
    assert client.post(f"/v1/commitments/{a['id']}/miss", headers=HDR,
                       json={"raise": False}).status_code == 200
    # B: clean success (no charge), deliberate next rung, then auto-missed ($3)
    client.post(f"/v1/commitments/{b['id']}/confirm-clean", headers=HDR)
    client.post(f"/v1/commitments/{b['id']}/choose-next", headers=HDR,
                json={"days": 3, "stake": 3.0})
    backdate(b["id"])
    client.post("/v1/tick", headers=HDR)
    # A dry-run preview must move nothing.
    client.post(f"/v1/commitments/{a['id']}/slip", headers=HDR, json={"dryRun": True})

    charged_history = [
        h["stake"]
        for cm in client.get("/v1/commitments", headers=HDR).json()
        for h in cm["history"] if h["outcome"] in ("lapse", "missed")
    ]
    assert sum(CHARGES) == total_charged() == sum(charged_history) == 5.0 + 6.0 + 3.0


# ── edges: cap, boundary, garbage input ──────────────────────────────────────
def test_stake_over_cap_gets_402_and_explicit_recommit_recovers():
    # No fake: the real beeminder.charge must refuse at validation, before any
    # network I/O, so this runs offline.
    cm = mk(stake=60.0)  # above the $50 cap
    r = client.post(f"/v1/commitments/{cm['id']}/slip", headers=HDR, json={})
    assert r.status_code == 402 and "cap" in r.json()["detail"]
    assert snapshot(cm["id"])["history"] == [] and total_charged() == 0
    # The escape hatch: deliberately re-rung at a chargeable stake.
    r = client.post(f"/v1/commitments/{cm['id']}/choose-next", headers=HDR,
                    json={"days": 3, "stake": 10.0})
    assert r.status_code == 200
    assert snapshot(cm["id"])["current_rung"]["stake"] == 10.0


def test_non_finite_stake_never_reaches_state():
    r = client.post("/v1/commitments", headers=HDR,
                    json={"name": "Inf", "base_days": 1, "base_stake": "Infinity"})
    if r.status_code == 200:  # coerced: the clamp must have made it finite
        assert math.isfinite(r.json()["current_rung"]["stake"])
    else:
        assert r.status_code == 422  # or rejected outright at the schema
    cm = mk()
    r = client.post(f"/v1/commitments/{cm['id']}/slip", headers=HDR,
                    json={"dryRun": True, "stake": "Infinity"})
    if r.status_code == 200:
        assert math.isfinite(r.json()["recommit"]["stake"])
    else:
        assert r.status_code == 422


def test_is_past_grace_exact_boundary_is_not_past():
    cm = ratchet.new_commitment("X", 1, 5.0)
    end = ratchet.grace_end_ms(cm["current_rung"], settings.grace_ms)
    assert ratchet.is_past_grace(cm, settings.grace_ms, at_ms=end) is False
    assert ratchet.is_past_grace(cm, settings.grace_ms, at_ms=end + 1) is True


# ── end-of-day "goal broken" penalty (deferred Beeminder charge) ─────────────
# The tally is keyed to *today* (the server clock rules, per metrics_today),
# so to simulate a day that has closed these tests relabel the bookkeeping
# rows onto a day far enough in the past that its tz's midnight has passed —
# the same trick backdate() plays for commitment grace windows.
def backdate_penalty_day(new_day="2000-01-01") -> str:
    today = main.metrics_today()
    with store.lock, store._conn:
        store._conn.execute(
            "UPDATE metric_days SET day=? WHERE metric='gaze_goal_broken' AND day=?",
            (new_day, today))
        store._conn.execute(
            "UPDATE penalty_days SET day=? WHERE day=?", (new_day, today))
    return new_day


def test_goal_broken_bump_does_not_charge_immediately(monkeypatch):
    monkeypatch.setattr(beeminder, "charge", fake_charge())
    r = client.post("/v1/metrics/gaze_goal_broken/bump", headers=HDR,
                    json={"delta": 1, "tz": "UTC"})
    assert r.status_code == 200
    assert CHARGES == []
    assert r.json()["pendingPenalty"]["amount"] == 1
    assert total_charged() == 0


def test_goal_broken_bump_without_tz_falls_back_to_metrics_tz():
    client.post("/v1/metrics/gaze_goal_broken/bump", headers=HDR, json={"delta": 1})
    row = store.get_penalty_day(main.metrics_today())
    assert row["tz"] == settings.metrics_tz


def test_goal_broken_not_charged_until_day_closes(monkeypatch):
    monkeypatch.setattr(beeminder, "charge", fake_charge())
    client.post("/v1/metrics/gaze_goal_broken/bump", headers=HDR,
                json={"delta": 1, "tz": "UTC"})
    # Relabel onto a day far in the future so its midnight can't have passed
    # regardless of what time this test happens to run.
    backdate_penalty_day("2099-01-01")
    out = client.post("/v1/tick", headers=HDR).json()
    assert out["penalties_charged_count"] == 0
    assert CHARGES == []


def test_goal_broken_charges_net_count_once_day_closes(monkeypatch):
    monkeypatch.setattr(beeminder, "charge", fake_charge())
    for _ in range(3):
        client.post("/v1/metrics/gaze_goal_broken/bump", headers=HDR,
                    json={"delta": 1, "tz": "UTC"})
    day = backdate_penalty_day()
    out = client.post("/v1/tick", headers=HDR).json()
    assert out["penalties_charged_count"] == 1
    entry = out["penalties_charged"][0]
    assert entry["day"] == day and entry["amount"] == 3
    assert "looking at women with sexual desire" in entry["charge"]["note"]
    assert CHARGES == [3.0] and total_charged() == 3.0
    # Idempotent: a repeated tick doesn't charge the same day twice.
    out2 = client.post("/v1/tick", headers=HDR).json()
    assert out2["penalties_charged_count"] == 0
    assert CHARGES == [3.0]


def test_goal_broken_undo_before_close_reduces_the_charge(monkeypatch):
    monkeypatch.setattr(beeminder, "charge", fake_charge())
    client.post("/v1/metrics/gaze_goal_broken/bump", headers=HDR, json={"delta": 1, "tz": "UTC"})
    client.post("/v1/metrics/gaze_goal_broken/bump", headers=HDR, json={"delta": 1, "tz": "UTC"})
    client.post("/v1/metrics/gaze_goal_broken/bump", headers=HDR, json={"delta": -1, "tz": "UTC"})
    backdate_penalty_day()
    out = client.post("/v1/tick", headers=HDR).json()
    assert out["penalties_charged"][0]["amount"] == 1
    assert CHARGES == [1.0]


def test_goal_broken_failed_charge_leaves_state_untouched(monkeypatch):
    client.post("/v1/metrics/gaze_goal_broken/bump", headers=HDR, json={"delta": 1, "tz": "UTC"})
    day = backdate_penalty_day()
    monkeypatch.setattr(beeminder, "charge", fake_charge(fail_for={1.0}))
    out = client.post("/v1/tick", headers=HDR).json()
    assert out["penalty_errors"] == [{"day": day, "error": "simulated Beeminder outage"}]
    assert total_charged() == 0
    assert store.get_penalty_day(day)["charged_count"] == 0


def test_day_end_utc_falls_back_on_missing_or_bogus_tz():
    ny = main._day_end_utc("2026-07-18", "America/New_York")
    assert main._day_end_utc("2026-07-18", None) == ny
    assert main._day_end_utc("2026-07-18", "not-a-real-tz") == ny
    assert ny == main._day_end_utc("2026-07-18", settings.metrics_tz)
