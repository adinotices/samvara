"""Charge-client tests: the one module that moves real money.

Every HTTP call is faked at the httpx boundary so these run offline; what they
pin is the safety rails (floor, cap, missing token), the dryrun plumbing, and
that every failure mode surfaces as ChargeError rather than half-succeeding.

Run from backend/:  python -m pytest -q tests/test_beeminder.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SAMVARA_DB", os.path.join(tempfile.mkdtemp(), "test-bm.db"))

from app import beeminder  # noqa: E402
from app.config import settings  # noqa: E402

CALLS: list[dict] = []  # captured (url, data) per outgoing POST


class FakeResponse:
    def __init__(self, status_code=200, body: dict | None = None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text
        self.content = b"x" if body is not None else b""

    def json(self):
        return self._body


class FakeAsyncClient:
    """Stands in for httpx.AsyncClient; behavior driven by module globals."""

    response: FakeResponse = FakeResponse(200, {"id": 42})
    raise_network = False

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None):
        if FakeAsyncClient.raise_network:
            raise httpx.ConnectError("boom")
        CALLS.append({"url": url, "data": dict(data or {})})
        return FakeAsyncClient.response


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    CALLS.clear()
    FakeAsyncClient.response = FakeResponse(200, {"id": 42})
    FakeAsyncClient.raise_network = False
    monkeypatch.setattr(beeminder.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(settings, "beeminder_token", "tok")
    monkeypatch.setattr(settings, "beeminder_user", "")
    monkeypatch.setattr(settings, "beeminder_dryrun", False)
    monkeypatch.setattr(settings, "min_stake", 1.0)
    monkeypatch.setattr(settings, "max_charge", 50.0)
    yield


def charge(amount, note="test"):
    return asyncio.run(beeminder.charge(amount, note))


# ── safety rails: reject before any network I/O ──────────────────────────────
def test_below_floor_refuses_without_calling_out():
    with pytest.raises(beeminder.ChargeError, match="below"):
        charge(0.50)
    assert CALLS == []


def test_cap_boundary_exact_amount_allowed_a_cent_over_refused():
    charge(50.00)
    assert len(CALLS) == 1
    with pytest.raises(beeminder.ChargeError, match="cap"):
        charge(50.01)
    assert len(CALLS) == 1  # the refusal never reached the wire


def test_missing_token_refuses_without_calling_out(monkeypatch):
    monkeypatch.setattr(settings, "beeminder_token", "")
    with pytest.raises(beeminder.ChargeError, match="BEEMINDER_TOKEN"):
        charge(5.0)
    assert CALLS == []


# ── dryrun plumbing ───────────────────────────────────────────────────────────
def test_dryrun_flag_reaches_beeminder_and_marks_result(monkeypatch):
    monkeypatch.setattr(settings, "beeminder_dryrun", True)
    res = charge(5.0)
    assert CALLS[-1]["data"].get("dryrun") == "1"
    assert res.dryrun is True and res.charged is False


def test_live_run_omits_dryrun_and_marks_charged():
    res = charge(5.0)
    assert "dryrun" not in CALLS[-1]["data"]
    assert res.dryrun is False and res.charged is True


# ── request shape ─────────────────────────────────────────────────────────────
def test_amount_formatted_to_cents_and_note_passed():
    charge(5.5, note="Samvara: missed on 'X' (3-day rung)")
    d = CALLS[-1]["data"]
    assert d["amount"] == "5.50"
    assert d["note"] == "Samvara: missed on 'X' (3-day rung)"
    assert d["auth_token"] == "tok"


def test_user_id_included_only_when_configured(monkeypatch):
    charge(5.0)
    assert "user_id" not in CALLS[-1]["data"]
    monkeypatch.setattr(settings, "beeminder_user", "alice")
    charge(5.0)
    assert CALLS[-1]["data"]["user_id"] == "alice"


def test_beeminder_id_captured_and_absent_body_tolerated():
    assert charge(5.0).beeminder_id == "42"
    FakeAsyncClient.response = FakeResponse(200, None)  # empty 200 body
    assert charge(5.0).beeminder_id is None


# ── failure modes all become ChargeError ─────────────────────────────────────
def test_http_error_status_raises_charge_error():
    FakeAsyncClient.response = FakeResponse(500, {"error": "nope"}, text="nope")
    with pytest.raises(beeminder.ChargeError, match="500"):
        charge(5.0)


def test_network_failure_raises_charge_error():
    FakeAsyncClient.raise_network = True
    with pytest.raises(beeminder.ChargeError, match="request failed"):
        charge(5.0)
