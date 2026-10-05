"""API surface behaviors that aren't money or auth.

Run from backend/:  python -m pytest -q tests/test_api.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Match the other test modules: first import wins for the singletons.
os.environ.setdefault("SAMVARA_DB", os.path.join(tempfile.mkdtemp(), "test-api.db"))
os.environ.setdefault("AUTH_MODE", "token")
os.environ.setdefault("API_TOKEN", "static-cron-token")
os.environ.setdefault("AUTH_EMAIL", "owner@example.com")

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.store import store  # noqa: E402

client = TestClient(app)
HDR = {"Authorization": f"Bearer {settings.api_token}"}


@pytest.fixture(autouse=True)
def _clean():
    with store.lock, store._conn:
        store._conn.execute("DELETE FROM commitments")
        store._conn.execute("DELETE FROM metric_days")
    yield


def mk(name: str, days: int) -> str:
    r = client.post("/v1/commitments", headers=HDR,
                    json={"name": name, "base_days": days, "base_stake": 5.0})
    assert r.status_code == 200
    return r.json()["id"]


# ── daily metrics (the Data tab) ─────────────────────────────────────────────
def test_metrics_vocabulary_and_empty_series():
    out = client.get("/v1/metrics", headers=HDR).json()
    keys = [m["key"] for m in out["metrics"]]
    # Archived metrics (eating_animal_body_parts, looking_with_sexual_desire)
    # are left out of the payload entirely.
    assert keys == ["porn_viewed", "sexual_content_viewed", "masturbation",
                    "gaze_goal_set", "gaze_goal_broken"]
    # The ratio-tracked metrics lead the list; the two gaze rows trail it.
    # Ratios and Streaks render exactly this subset, so keep them contiguous.
    assert [m["key"] for m in out["metrics"] if m["ratio"]] == keys[:3]
    assert out["series"] == {}
    assert out["today"] == main.metrics_today()


def test_bump_increments_today_and_decrement_floors_at_zero():
    r = client.post("/v1/metrics/masturbation/bump", headers=HDR, json={"delta": 1})
    today = r.json()["today"]
    assert r.json()["series"]["masturbation"][today] == 1
    client.post("/v1/metrics/masturbation/bump", headers=HDR, json={"delta": 1})
    r = client.post("/v1/metrics/masturbation/bump", headers=HDR, json={"delta": -1})
    assert r.json()["series"]["masturbation"][today] == 1
    # Two more decrements: 0, then floored at 0 — never negative.
    client.post("/v1/metrics/masturbation/bump", headers=HDR, json={"delta": -1})
    r = client.post("/v1/metrics/masturbation/bump", headers=HDR, json={"delta": -1})
    assert r.json()["series"]["masturbation"][today] == 0


def test_archived_metric_is_hidden_and_unbumpable_but_keeps_its_history():
    today = main.metrics_today()
    with store.lock, store._conn:
        store._conn.execute(
            "INSERT INTO metric_days (metric, day, count) VALUES (?, ?, ?)",
            ("eating_animal_body_parts", today, 1))
    r = client.post("/v1/metrics/eating_animal_body_parts/bump", headers=HDR, json={"delta": 1})
    assert r.status_code == 409
    out = client.get("/v1/metrics", headers=HDR).json()
    assert "eating_animal_body_parts" not in out["series"]
    assert "eating_animal_body_parts" not in out["stats"]
    assert store.metric_count("eating_animal_body_parts", today) == 1


def test_clean_runs_cover_gaps_between_occurrences():
    runs = main._clean_runs(["2026-07-05", "2026-07-06", "2026-07-10"],
                            "2026-07-01", "2026-07-15")
    assert runs == [
        {"start": "2026-07-01", "end": "2026-07-04", "days": 4, "current": False},
        # 07-05 → 07-06 back to back: no run between them.
        {"start": "2026-07-07", "end": "2026-07-09", "days": 3, "current": False},
        {"start": "2026-07-11", "end": "2026-07-15", "days": 5, "current": True},
    ]


def test_clean_runs_current_is_zero_when_it_happened_today_and_full_span_when_never():
    assert main._clean_runs(["2026-07-15"], "2026-07-15", "2026-07-15") == [
        {"start": "2026-07-16", "end": "2026-07-15", "days": 0, "current": True}]
    assert main._clean_runs([], "2026-07-01", "2026-07-03") == [
        {"start": "2026-07-01", "end": "2026-07-03", "days": 3, "current": True}]


def test_metrics_payload_carries_runs_for_ratio_metrics_only():
    client.post("/v1/metrics/masturbation/bump", headers=HDR, json={"delta": 1})
    stats = client.get("/v1/metrics", headers=HDR).json()["stats"]
    assert stats["masturbation"]["runs"][-1] == {
        "start": stats["masturbation"]["runs"][-1]["start"],
        "end": main.metrics_today(), "days": 0, "current": True}
    assert "runs" not in stats["gaze_goal_set"]


def test_bump_rejects_unknown_metric_and_bad_delta():
    assert client.post("/v1/metrics/nonsense/bump", headers=HDR,
                       json={"delta": 1}).status_code == 404
    assert client.post("/v1/metrics/masturbation/bump", headers=HDR,
                       json={"delta": 0}).status_code == 400
    assert client.post("/v1/metrics/masturbation/bump", headers=HDR,
                       json={"delta": 5}).status_code == 400
    assert client.get("/v1/metrics", headers=HDR).json()["series"] == {}


def test_metrics_day_boundary_is_new_york():
    import datetime as dt
    utc = dt.timezone.utc
    # 23:30 EDT on July 3 is 03:30 UTC July 4 — still July 3 in New York.
    assert main.metrics_today(dt.datetime(2026, 7, 4, 3, 30, tzinfo=utc)) == "2026-07-03"
    assert main.metrics_today(dt.datetime(2026, 7, 4, 4, 30, tzinfo=utc)) == "2026-07-04"
    # Winter (EST, UTC-5): the boundary moves an hour.
    assert main.metrics_today(dt.datetime(2026, 1, 10, 4, 30, tzinfo=utc)) == "2026-01-09"


def test_metrics_require_auth():
    assert client.get("/v1/metrics").status_code == 401
    assert client.post("/v1/metrics/masturbation/bump",
                       json={"delta": 1}).status_code == 401


def test_create_survives_an_id_collision(monkeypatch):
    from app import ratchet
    taken = mk("First", days=3)
    real_new_id = ratchet.new_id
    ids = iter([taken, real_new_id()])  # collide once, then a fresh id
    monkeypatch.setattr(ratchet, "new_id", lambda: next(ids))
    r = client.post("/v1/commitments", headers=HDR,
                    json={"name": "Second", "base_days": 1, "base_stake": 5.0})
    assert r.status_code == 200
    assert r.json()["id"] != taken


def test_commitments_listed_closest_deadline_first():
    # Created in the opposite order to their deadlines, so insertion order
    # (the old behavior) would fail this.
    far = mk("Far", days=9)
    near = mk("Near", days=1)
    mid = mk("Mid", days=4)
    names = [c["name"] for c in client.get("/v1/commitments", headers=HDR).json()]
    assert names == ["Near", "Mid", "Far"]
    # An overdue/parked rung has the oldest due date, so it surfaces on top.
    cm = store.get_commitment(near)
    cm["current_rung"]["due"] = "2000-01-01T00:00:00.000Z"
    store.update_commitment(cm)
    names = [c["name"] for c in client.get("/v1/commitments", headers=HDR).json()]
    assert names[0] == "Near"
    assert far and mid  # ids used; silence linters


# ── payload aggregates (keep the client off lifetime day-by-day history) ─────
def test_metrics_stats_carry_ratio_and_last_day(monkeypatch):
    """The ratio's numerator/denominator and the streak's anchor are computed
    server-side, so the series payload can stay bounded to the graph window."""
    monkeypatch.setattr(main, "METRICS", main.METRICS + [
        {"key": "late_starter", "label": "Late starter", "ratio": True, "start_day": "2026-08-08"},
    ])
    today = main.metrics_today()
    old = "2020-01-01"          # far outside any graph window
    with store.lock, store._conn:
        store._conn.execute(
            "INSERT OR REPLACE INTO metric_days (metric, day, count) VALUES (?,?,?)",
            ("porn_viewed", old, 2))
    out = client.get("/v1/metrics", headers=HDR).json()

    st = out["stats"]["porn_viewed"]
    assert st["last_day"] == old          # survives the series bound
    assert st["start"] == main.TRACKING_START_DAY
    assert st["ratio_days"] == 0          # before tracking began: not counted
    assert st["tracked_days"] >= 1
    # A metric with its own start_day gets its own, later denominator.
    late = out["stats"]["late_starter"]
    assert late["start"] == "2026-08-08"
    assert late["tracked_days"] < st["tracked_days"]
    assert out["trackingStart"] == main.TRACKING_START_DAY
    assert out["graphWindowDays"] == main.GRAPH_WINDOW_DAYS

    # The day itself is far too old to be shipped day-by-day.
    assert old not in out["series"].get("porn_viewed", {})
    assert today == out["today"]


def test_metrics_series_is_bounded_to_the_graph_window():
    today = dt.date.fromisoformat(main.metrics_today())
    inside = (today - dt.timedelta(days=main.GRAPH_WINDOW_DAYS - 1)).isoformat()
    outside = (today - dt.timedelta(days=main.GRAPH_WINDOW_DAYS + 5)).isoformat()
    with store.lock, store._conn:
        for day in (inside, outside):
            store._conn.execute(
                "INSERT OR REPLACE INTO metric_days (metric, day, count) VALUES (?,?,?)",
                ("masturbation", day, 1))
    series = client.get("/v1/metrics", headers=HDR).json()["series"]["masturbation"]
    assert inside in series
    assert outside not in series


def test_metric_stats_tolerate_a_future_start_day(monkeypatch):
    """A start_day set ahead of today must not yield a zero denominator (the
    client rendered that as a literal "NaN")."""
    future = (dt.date.fromisoformat(main.metrics_today()) + dt.timedelta(days=30)).isoformat()
    monkeypatch.setattr(main, "METRICS", [
        {"key": "porn_viewed", "label": "Porn viewed", "ratio": True, "start_day": future},
    ])
    st = main._metric_stats(main.metrics_today())["porn_viewed"]
    assert st["tracked_days"] == 1
    assert st["start"] == main.metrics_today()


# ── archiving paused goals ───────────────────────────────────────────────────
def test_only_a_paused_goal_can_be_archived():
    cid = mk("running", 3)
    r = client.post(f"/v1/commitments/{cid}/archive", headers=HDR)
    assert r.status_code == 409          # a deadline is running
    assert not client.get(f"/v1/commitments/{cid}", headers=HDR).json().get("archived_at")


def test_archive_and_unarchive_round_trip_leaves_the_rung_untouched():
    cid = mk("paused", 3)
    client.post(f"/v1/commitments/{cid}/confirm-clean", headers=HDR)
    before = client.get(f"/v1/commitments/{cid}", headers=HDR).json()

    r = client.post(f"/v1/commitments/{cid}/archive", headers=HDR)
    assert r.status_code == 200 and r.json()["archived_at"]
    # Archived goals can't be advanced until they're brought back.
    assert client.post(f"/v1/commitments/{cid}/choose-next", headers=HDR,
                       json={"days": 4, "stake": 5}).status_code == 409
    assert client.post(f"/v1/commitments/{cid}/confirm-clean", headers=HDR).status_code == 409

    r = client.post(f"/v1/commitments/{cid}/unarchive", headers=HDR)
    assert r.status_code == 200
    after = r.json()
    assert "archived_at" not in after
    assert after["current_rung"] == before["current_rung"]
    assert after["history"] == before["history"]
    assert client.post(f"/v1/commitments/{cid}/choose-next", headers=HDR,
                       json={"days": 4, "stake": 5}).status_code == 200


def test_archive_is_idempotent():
    cid = mk("paused", 3)
    client.post(f"/v1/commitments/{cid}/confirm-clean", headers=HDR)
    first = client.post(f"/v1/commitments/{cid}/archive", headers=HDR).json()["archived_at"]
    again = client.post(f"/v1/commitments/{cid}/archive", headers=HDR)
    assert again.status_code == 200 and again.json()["archived_at"] == first
