""""Request access" endpoint: persists the submission and best-effort emails
the owner. The persistence is the point — it's what makes the frontend's
"I'll reply soon" true even when the notification email fails.

Run from backend/:  python -m pytest -q tests/test_access_requests.py
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Match the other test modules: first import wins for the singletons.
os.environ.setdefault("SAMVARA_DB", os.path.join(tempfile.mkdtemp(), "test-access.db"))
os.environ.setdefault("AUTH_MODE", "token")
os.environ.setdefault("API_TOKEN", "static-cron-token")
os.environ.setdefault("AUTH_EMAIL", "owner@example.com")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app import auth, db, main  # noqa: E402
from app.store import store  # noqa: E402

client = TestClient(main.app)
SENT: list[tuple[str, str, str]] = []  # (to, subject, text)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    SENT.clear()

    async def fake_send(to: str, subject: str, text: str) -> None:
        SENT.append((to, subject, text))

    monkeypatch.setattr(auth, "send_email", fake_send)
    with store.lock, store.engine.begin() as conn:
        conn.execute(delete(db.access_requests))
    yield


def test_request_is_persisted_and_notifies_owner():
    res = client.post("/v1/access-requests", json={
        "name": "Jane Doe", "email": "jane@example.com", "message": "I'd love to try this.",
    })
    assert res.status_code == 204
    rows = store.list_access_requests()
    assert len(rows) == 1
    assert rows[0]["name"] == "Jane Doe"
    assert rows[0]["email"] == "jane@example.com"
    assert rows[0]["message"] == "I'd love to try this."
    assert len(SENT) == 1
    assert SENT[0][0] == "owner@example.com"
    assert "Jane Doe" in SENT[0][2]


def test_request_persists_even_if_notification_email_fails(monkeypatch):
    async def boom(to, subject, text):
        raise RuntimeError("Resend is down")
    monkeypatch.setattr(auth, "send_email", boom)

    res = client.post("/v1/access-requests", json={
        "name": "Bo", "email": "bo@example.com", "message": "Hi.",
    })
    assert res.status_code == 204  # the promise to the user still holds
    assert len(store.list_access_requests()) == 1


def test_missing_fields_rejected():
    res = client.post("/v1/access-requests", json={"name": "", "email": "x@example.com", "message": "hi"})
    assert res.status_code == 422
    assert store.list_access_requests() == []


def test_no_auth_required():
    # A denied sign-in has no bearer token by definition; the route must not
    # require one.
    res = client.post("/v1/access-requests", json={
        "name": "Anon", "email": "a@example.com", "message": "no token sent",
    }, headers={})
    assert res.status_code == 204
