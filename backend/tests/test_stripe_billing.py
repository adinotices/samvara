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

    async def delete(self, url, auth=None):
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


def test_requires_action_returns_pending_charge():
    FakeAsyncClient.response = FakeResponse(200, {"id": "pi_2", "status": "requires_action"})
    result = charge(5.0)
    assert result.charged is False
    assert result.status == "requires_action"
    assert result.provider_charge_id == "pi_2"


def test_non_succeeded_non_requires_action_status_raises_charge_error():
    FakeAsyncClient.response = FakeResponse(200, {"id": "pi_3", "status": "processing"})
    with pytest.raises(stripe_billing.ChargeError, match="processing"):
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


# ── refunds ──────────────────────────────────────────────────────────────────
def test_refund_full_charge():
    FakeAsyncClient.response = FakeResponse(200, {"id": "ref_123"})
    refund_id = asyncio.run(stripe_billing.refund_charge("pi_456"))
    assert refund_id == "ref_123"
    assert CALLS[-1]["url"].endswith("refunds")
    assert CALLS[-1]["data"]["payment_intent"] == "pi_456"
    assert "amount" not in CALLS[-1]["data"]


def test_refund_partial_amount():
    FakeAsyncClient.response = FakeResponse(200, {"id": "ref_789"})
    refund_id = asyncio.run(stripe_billing.refund_charge("pi_456", 5.50))
    assert refund_id == "ref_789"
    assert CALLS[-1]["data"]["amount"] == "550"  # in cents


def test_refund_missing_charge_id_raises():
    with pytest.raises(stripe_billing.ChargeError, match="No charge_id"):
        asyncio.run(stripe_billing.refund_charge(""))
    assert CALLS == []


def test_refund_missing_secret_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    with pytest.raises(stripe_billing.ChargeError, match="STRIPE_SECRET_KEY"):
        asyncio.run(stripe_billing.refund_charge("pi_456"))
    assert CALLS == []


def test_refund_network_error_raises():
    FakeAsyncClient.raise_network = True
    with pytest.raises(stripe_billing.ChargeError, match="request failed"):
        asyncio.run(stripe_billing.refund_charge("pi_456"))


def test_refund_stripe_error_raises():
    FakeAsyncClient.response = FakeResponse(400, {"error": {"message": "Invalid charge"}})
    with pytest.raises(stripe_billing.ChargeError, match="Invalid charge"):
        asyncio.run(stripe_billing.refund_charge("pi_456"))


# ── edge cases and boundary conditions ────────────────────────────────────────
def test_charge_at_exact_minimum():
    charge(settings.min_stake)
    assert len(CALLS) == 1  # should succeed


def test_charge_one_cent_below_minimum():
    with pytest.raises(stripe_billing.ChargeError, match="below"):
        charge(settings.min_stake - 0.01)
    assert CALLS == []


def test_charge_at_exact_maximum():
    charge(settings.max_charge)
    assert len(CALLS) == 1  # should succeed


def test_charge_one_cent_above_maximum():
    with pytest.raises(stripe_billing.ChargeError, match="cap"):
        charge(settings.max_charge + 0.01)
    assert CALLS == []


def test_charge_amount_precision_cents():
    """Amounts with multiple decimal places are correctly rounded to cents."""
    charge(5.556)  # 555.6 cents → rounds to 556 cents ($5.56)
    assert CALLS[-1]["data"]["amount"] == "556"


def test_charge_amount_rounds_down():
    charge(5.554)  # 555.4 cents → rounds to 555 cents ($5.55)
    assert CALLS[-1]["data"]["amount"] == "555"


def test_idempotency_key_prevents_double_charge(monkeypatch):
    """Same idempotency key returns the same PaymentIntent id."""
    key = "commitment:slip:abc123"

    # First charge
    result1 = charge(5.0, idempotency_key=key)
    pi_id_1 = result1.provider_charge_id

    # Stripe returns the same PI for the same idempotency key
    FakeAsyncClient.response = FakeResponse(200, {"id": pi_id_1, "status": "succeeded"})
    result2 = charge(5.0, idempotency_key=key)
    pi_id_2 = result2.provider_charge_id

    assert pi_id_1 == pi_id_2
    # Both should have the key header
    assert CALLS[0]["headers"]["Idempotency-Key"] == key
    assert CALLS[1]["headers"]["Idempotency-Key"] == key


def test_empty_string_customer_id_refuses():
    with pytest.raises(stripe_billing.ChargeError, match="payment method"):
        charge(5.0, customer_id="")
    assert CALLS == []


def test_empty_string_payment_method_refuses():
    with pytest.raises(stripe_billing.ChargeError, match="payment method"):
        charge(5.0, pm_id="")
    assert CALLS == []


def test_description_truncated_to_500_chars():
    """Stripe API has a 500-char limit on description."""
    long_note = "x" * 600
    charge(5.0, note=long_note)
    desc = CALLS[-1]["data"]["description"]
    assert len(desc) == 500
    assert desc == "x" * 500


def test_stripe_api_error_500_raises():
    FakeAsyncClient.response = FakeResponse(500, {"error": {"message": "Server error"}})
    with pytest.raises(stripe_billing.ChargeError, match="Server error"):
        charge(5.0)


def test_stripe_api_error_503_raises():
    FakeAsyncClient.response = FakeResponse(503, {"error": {"message": "Service unavailable"}})
    with pytest.raises(stripe_billing.ChargeError, match="Service unavailable"):
        charge(5.0)


def test_stripe_api_empty_response_body():
    """Some errors return empty body; message comes from text instead."""
    FakeAsyncClient.response = FakeResponse(402, {}, text="Card declined")
    with pytest.raises(stripe_billing.ChargeError, match="Card declined"):
        charge(5.0)


def test_create_customer_idempotency():
    """Multiple calls to create_customer should eventually succeed."""
    FakeAsyncClient.response = FakeResponse(200, {"id": "cus_1"})
    cid1 = asyncio.run(stripe_billing.create_customer("a@test.com", "u_1"))
    cid2 = asyncio.run(stripe_billing.create_customer("a@test.com", "u_1"))
    assert cid1 == cid2 == "cus_1"


def test_refund_amount_precision():
    """Refund amount is correctly converted to cents."""
    FakeAsyncClient.response = FakeResponse(200, {"id": "ref_1"})
    asyncio.run(stripe_billing.refund_charge("pi_1", 10.556))  # 1055.6 → 1056
    assert CALLS[-1]["data"]["amount"] == "1056"


def test_refund_zero_amount_fails():
    """Cannot refund zero amount."""
    FakeAsyncClient.response = FakeResponse(400, {"error": {"message": "Amount must be positive"}})
    with pytest.raises(stripe_billing.ChargeError):
        asyncio.run(stripe_billing.refund_charge("pi_1", 0.00))


def test_get_payment_method_details_handles_missing_card():
    """Payment method without card object returns nulls."""
    FakeAsyncClient.response = FakeResponse(200, {"id": "pm_1", "card": None})
    details = asyncio.run(stripe_billing.get_payment_method_details("pm_1"))
    assert details == {"brand": None, "last4": None}


def test_get_payment_method_details_partial_card_info():
    """Handles card object with partial information."""
    FakeAsyncClient.response = FakeResponse(200, {
        "id": "pm_1",
        "card": {"brand": "visa"}  # no last4
    })
    details = asyncio.run(stripe_billing.get_payment_method_details("pm_1"))
    assert details["brand"] == "visa"
    assert details["last4"] is None


def test_delete_payment_method_404_logs_but_succeeds():
    """Deleting nonexistent payment method logs error but doesn't raise."""
    FakeAsyncClient.response = FakeResponse(404, {})
    asyncio.run(stripe_billing.delete_payment_method("pm_nonexistent"))
    # Should complete without raising


def test_delete_customer_404_logs_but_succeeds():
    """Deleting nonexistent customer logs error but doesn't raise."""
    FakeAsyncClient.response = FakeResponse(404, {})
    asyncio.run(stripe_billing.delete_customer("cus_nonexistent"))
    # Should complete without raising


def test_charge_with_none_customer_id():
    with pytest.raises(stripe_billing.ChargeError, match="payment method"):
        charge(5.0, customer_id=None)
    assert CALLS == []


def test_charge_with_none_payment_method_id():
    with pytest.raises(stripe_billing.ChargeError, match="payment method"):
        charge(5.0, pm_id=None)
    assert CALLS == []
