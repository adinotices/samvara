"""Dispatch tests for billing.py — provider resolution and the owner-only
Beeminder gate.

The invariant these pin: 'beeminder' as a charge provider is reachable ONLY
by the account whose email matches AUTH_EMAIL, no matter what a client sends
in a settings patch or what's already saved in a user's settings row (e.g. if
AUTH_EMAIL is reassigned after a user's settings were saved as 'beeminder').
Every other account gets 'samvara' (Stripe), silently and without a 500.

Run from backend/:  python -m pytest -q tests/test_billing.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SAMVARA_DB", os.path.join(tempfile.mkdtemp(), "test-billing.db"))
os.environ.setdefault("AUTH_MODE", "token")
os.environ.setdefault("API_TOKEN", "static-cron-token")
os.environ.setdefault("AUTH_EMAIL", "owner@example.com")

from app import beeminder, billing, stripe_billing  # noqa: E402
from app.config import settings  # noqa: E402
from app.store import store  # noqa: E402

OWNER_EMAIL = "owner@example.com"
OTHER_EMAIL = "billing-tests@example.com"


def _user(email: str) -> dict:
    return store.get_or_create_user(email, "UTC")


@pytest.fixture(autouse=True)
def _clean():
    yield
    # owner@example.com is shared across test modules (AUTH_EMAIL is the same
    # literal in each); don't leak a 'beeminder' selection into a module that
    # runs after this one.
    owner = store.get_user_by_email(OWNER_EMAIL)
    if owner:
        store.update_settings(owner["id"], {"chargeProvider": "samvara"})


# ── resolve_provider: the owner-only gate ────────────────────────────────────
def test_default_provider_is_samvara_for_everyone():
    u = _user(OTHER_EMAIL)
    assert billing.resolve_provider(u) == "samvara"


def test_owner_can_resolve_to_beeminder_after_opting_in():
    owner = _user(OWNER_EMAIL)
    store.update_settings(owner["id"], {"chargeProvider": "beeminder"})
    assert billing.resolve_provider(owner) == "beeminder"


def test_non_owner_beeminder_setting_is_silently_downgraded():
    """Defense in depth: even if 'beeminder' somehow landed in a non-owner's
    settings row (bypassing validate_provider_choice, e.g. a direct DB edit
    or an AUTH_EMAIL reassignment after the fact), the money-moving
    chokepoint refuses to honor it."""
    u = _user(OTHER_EMAIL)
    store.update_settings(u["id"], {"chargeProvider": "beeminder"})
    assert billing.resolve_provider(u) == "samvara"


# ── validate_provider_choice: what PATCH /v1/settings enforces up front ─────
def test_validate_provider_choice_rejects_beeminder_for_non_owner():
    u = _user(OTHER_EMAIL)
    with pytest.raises(PermissionError):
        billing.validate_provider_choice(u, "beeminder")


def test_validate_provider_choice_allows_beeminder_for_owner():
    owner = _user(OWNER_EMAIL)
    billing.validate_provider_choice(owner, "beeminder")  # must not raise


def test_validate_provider_choice_rejects_unknown_provider():
    u = _user(OTHER_EMAIL)
    with pytest.raises(billing.ChargeError):
        billing.validate_provider_choice(u, "paypal")


# ── charge_for_user: dispatch actually calls the resolved provider ──────────
def test_charge_for_user_dispatches_to_stripe_by_default(monkeypatch):
    u = _user(OTHER_EMAIL)
    store.set_stripe_customer_id(u["id"], "cus_1")
    store.update_settings(u["id"], {"stripePaymentMethodId": "pm_1"})

    calls = []

    async def fake_stripe_charge(customer_id, pm_id, amount, note, idempotency_key=None):
        calls.append((customer_id, pm_id, amount))
        return stripe_billing.ChargeResult(charged=True, amount=amount, note=note,
                                           provider_charge_id="pi_fake")

    monkeypatch.setattr(stripe_billing, "charge", fake_stripe_charge)
    u = store.get_user(u["id"])  # refresh: pick up stripe_customer_id
    result = asyncio.run(billing.charge_for_user(u, 5.0, "note"))
    assert calls == [("cus_1", "pm_1", 5.0)]
    assert result.provider == "samvara"
    assert result.provider_charge_id == "pi_fake"


def test_charge_for_user_missing_payment_method_raises_billing_error(monkeypatch):
    u = _user("billing-tests-nocard@example.com")

    async def fake_create_customer(email, user_id):
        return "cus_new"

    monkeypatch.setattr(stripe_billing, "create_customer", fake_create_customer)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    with pytest.raises(billing.ChargeError, match="No payment method"):
        asyncio.run(billing.charge_for_user(u, 5.0, "note"))


def test_charge_for_user_dispatches_to_beeminder_for_owner_opted_in(monkeypatch):
    owner = _user(OWNER_EMAIL)
    store.update_settings(owner["id"], {"chargeProvider": "beeminder"})

    calls = []

    async def fake_beeminder_charge(amount, note):
        calls.append((amount, note))
        return beeminder.ChargeResult(charged=True, amount=amount, note=note,
                                      beeminder_id="bm_fake", dryrun=False)

    monkeypatch.setattr(beeminder, "charge", fake_beeminder_charge)
    result = asyncio.run(billing.charge_for_user(owner, 5.0, "note"))
    assert calls == [(5.0, "note")]
    assert result.provider == "beeminder"
    assert result.provider_charge_id == "bm_fake"


def test_charge_for_user_wraps_stripe_error_as_billing_error(monkeypatch):
    u = _user(OTHER_EMAIL)
    store.set_stripe_customer_id(u["id"], "cus_1")
    store.update_settings(u["id"], {"stripePaymentMethodId": "pm_1"})
    u = store.get_user(u["id"])

    async def fail(*a, **kw):
        raise stripe_billing.ChargeError("card declined")

    monkeypatch.setattr(stripe_billing, "charge", fail)
    with pytest.raises(billing.ChargeError, match="declined"):
        asyncio.run(billing.charge_for_user(u, 5.0, "note"))


def test_charge_for_user_wraps_beeminder_error_as_billing_error(monkeypatch):
    owner = _user(OWNER_EMAIL)
    store.update_settings(owner["id"], {"chargeProvider": "beeminder"})

    async def fail(amount, note):
        raise beeminder.ChargeError("beeminder outage")

    monkeypatch.setattr(beeminder, "charge", fail)
    with pytest.raises(billing.ChargeError, match="outage"):
        asyncio.run(billing.charge_for_user(owner, 5.0, "note"))
