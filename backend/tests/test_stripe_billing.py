"""Stripe charge-client tests — the default, consumer-facing money mover.

Mirrors test_beeminder.py's shape: every HTTP call is faked at the httpx
boundary so these run offline; what they pin is the safety rails (floor,
cap, missing key, missing payment method) and that every failure mode
surfaces as ChargeError rather than half-succeeding.

Run from backend/:  python -m pytest -q tests/test_stripe_billing.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SAMVARA_DB", os.path.join(tempfile.mkdtemp(), "test-stripe.db"))

from app import stripe_billing  # noqa: E402
from app.config import settings  # noqa: E402

CALLS: list[dict] = []  # captured (url, data, headers) per outgoing POST


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

    response: FakeResponse = FakeResponse(200, {"id": "pi_1", "status": "succeeded"})
    raise_network = False

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None, auth=None, headers=None):
        if FakeAsyncClient.raise_network:
            raise httpx.ConnectError("boom")
        CALLS.append({"url": url, "data": dict(data or {}), "headers": dict(headers or {})})
        return FakeAsyncClient.response

    async def get(self, url, auth=None):
        if FakeAsyncClient.raise_network:
            raise httpx.ConnectError("boom")
        CALLS.append({"url": url, "data": {}, "headers": {}})
        return FakeAsyncClient.response


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    CALLS.clear()
    FakeAsyncClient.response = FakeResponse(200, {"id": "pi_1", "status": "succeeded"})
    FakeAsyncClient.raise_network = False
    monkeypatch.setattr(stripe_billing.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "min_stake", 1.0)
    monkeypatch.setattr(settings, "max_charge", 50.0)
    yield


def charge(amount, note="test", customer_id="cus_1", pm_id="pm_1", idempotency_key=None):
    return asyncio.run(stripe_billing.charge(customer_id, pm_id, amount, note, idempotency_key))


# ── safety rails: reject before any network I/O ──────────────────────────────
def test_below_floor_refuses_without_calling_out():
    with pytest.raises(stripe_billing.ChargeError, match="below"):
        charge(0.50)
    assert CALLS == []


def test_cap_boundary_exact_amount_allowed_a_cent_over_refused():
    charge(50.00)
    assert len(CALLS) == 1
    with pytest.raises(stripe_billing.ChargeError, match="cap"):
        charge(50.01)
    assert len(CALLS) == 1  # the refusal never reached the wire


def test_missing_secret_key_refuses_without_calling_out(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    with pytest.raises(stripe_billing.ChargeError, match="STRIPE_SECRET_KEY"):
        charge(5.0)
    assert CALLS == []


def test_missing_payment_method_refuses_without_calling_out():
    with pytest.raises(stripe_billing.ChargeError, match="No payment method"):
        charge(5.0, pm_id=None)
    assert CALLS == []
    with pytest.raises(stripe_billing.ChargeError, match="No payment method"):
        charge(5.0, customer_id=None)
    assert CALLS == []


# ── request shape ─────────────────────────────────────────────────────────────
def test_amount_converted_to_cents_and_fields_passed():
    charge(5.5, note="Samvara: missed on 'X' (3-day rung)")
    d = CALLS[-1]["data"]
    assert d["amount"] == "550"
    assert d["currency"] == "usd"
    assert d["customer"] == "cus_1"
    assert d["payment_method"] == "pm_1"
    assert d["off_session"] == "true"
    assert d["confirm"] == "true"
    assert d["description"] == "Samvara: missed on 'X' (3-day rung)"


def test_idempotency_key_sent_as_header():
    charge(5.0, idempotency_key="cid:lapse:0")
    assert CALLS[-1]["headers"]["Idempotency-Key"] == "cid:lapse:0"


def test_provider_charge_id_captured_on_success():
    assert charge(5.0).provider_charge_id == "pi_1"


# ── failure modes all become ChargeError ─────────────────────────────────────
def test_http_error_status_raises_charge_error():
    FakeAsyncClient.response = FakeResponse(
        402, {"error": {"message": "Your card was declined."}}, text="nope")
    with pytest.raises(stripe_billing.ChargeError, match="declined"):
        charge(5.0)


def test_non_succeeded_status_raises_charge_error():
    FakeAsyncClient.response = FakeResponse(200, {"id": "pi_2", "status": "requires_action"})
    with pytest.raises(stripe_billing.ChargeError, match="requires_action"):
        charge(5.0)


def test_network_failure_raises_charge_error():
    FakeAsyncClient.raise_network = True
    with pytest.raises(stripe_billing.ChargeError, match="request failed"):
        charge(5.0)


# ── customer / setup-intent plumbing (card-on-file, not a charge) ────────────
def test_create_customer_posts_email_and_user_id():
    FakeAsyncClient.response = FakeResponse(200, {"id": "cus_42"})
    cid = asyncio.run(stripe_billing.create_customer("a@example.com", "u_1"))
    assert cid == "cus_42"
    assert CALLS[-1]["data"]["email"] == "a@example.com"
    assert CALLS[-1]["data"]["metadata[user_id]"] == "u_1"


def test_create_setup_intent_returns_client_secret():
    FakeAsyncClient.response = FakeResponse(200, {"id": "seti_1", "client_secret": "seti_1_secret"})
    out = asyncio.run(stripe_billing.create_setup_intent("cus_42"))
    assert out == {"clientSecret": "seti_1_secret", "id": "seti_1"}
    assert CALLS[-1]["data"]["customer"] == "cus_42"


def test_set_default_payment_method_posts_invoice_settings():
    asyncio.run(stripe_billing.set_default_payment_method("cus_42", "pm_9"))
    assert CALLS[-1]["url"].endswith("customers/cus_42")
    assert CALLS[-1]["data"]["invoice_settings[default_payment_method]"] == "pm_9"


def test_get_setup_intent_payment_method_returns_attached_pm():
    FakeAsyncClient.response = FakeResponse(200, {"id": "seti_1", "payment_method": "pm_7"})
    pm_id = asyncio.run(stripe_billing.get_setup_intent_payment_method("seti_1"))
    assert pm_id == "pm_7"
    assert CALLS[-1]["url"].endswith("setup_intents/seti_1")


def test_get_setup_intent_payment_method_raises_if_unattached():
    FakeAsyncClient.response = FakeResponse(200, {"id": "seti_1", "payment_method": None})
    with pytest.raises(stripe_billing.ChargeError, match="no attached payment method"):
        asyncio.run(stripe_billing.get_setup_intent_payment_method("seti_1"))
