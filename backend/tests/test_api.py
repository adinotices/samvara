"""API surface behaviors that aren't money or auth.

Run from backend/:  python -m pytest -q tests/test_api.py
"""
from __future__ import annotations

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

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.store import store  # noqa: E402

client = TestClient(app)
HDR = {"Authorization": f"Bearer {settings.api_token}"}


@pytest.fixture(autouse=True)
def _clean():
    with store.lock, store._conn:
        store._conn.execute("DELETE FROM commitments")
    yield


def mk(name: str, days: int) -> str:
    r = client.post("/v1/commitments", headers=HDR,
                    json={"name": name, "base_days": days, "base_stake": 5.0})
    assert r.status_code == 200
    return r.json()["id"]


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
