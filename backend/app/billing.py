"""Charge dispatch — picks the provider and hides it from main.py.

Two providers exist:
  * 'samvara' — Stripe, billed straight to Samvara's own account. This is the
    ONLY option ordinary users can select; it's what a freshly signed-up user
    gets by default (see store.DEFAULT_USER_SETTINGS).
  * 'beeminder' — the original personal integration (money charged via
    Beeminder's API, to whichever Beeminder account BEEMINDER_TOKEN belongs
    to). Kept working, but hidden: only the app owner's account (AUTH_EMAIL)
    can select it. There is no UI for this for anyone else, and this module
    enforces it server-side too — not just at the settings-patch endpoint —
    because this is the one place money actually moves, and that's the wrong
    place to trust a client-side toggle that was never shown to begin with.

Callers (main.py) never call beeminder.charge or stripe_billing.charge
directly for a user-facing charge; they call resolve_provider() before
opening the outbox record (so the ledger row's `provider` column is right)
and charge_for_user() to actually move the money.
"""
from __future__ import annotations

from typing import Any

from . import beeminder, stripe_billing
from .config import is_owner
from .store import store

VALID_PROVIDERS = {"samvara", "beeminder"}


class ChargeError(Exception):
    pass


class ChargeResult:
    def __init__(self, charged: bool, amount: float, note: str,
                 provider: str, provider_charge_id: str | None):
        self.charged = charged
        self.amount = amount
        self.note = note
        self.provider = provider
        self.provider_charge_id = provider_charge_id

    def as_dict(self) -> dict:
        return {
            "charged": self.charged,
            "amount": self.amount,
            "note": self.note,
            "provider": self.provider,
            "provider_charge_id": self.provider_charge_id,
        }


def resolve_provider(user: dict[str, Any]) -> str:
    """The provider that will actually be used for this user's next charge.
    'beeminder' silently downgrades to 'samvara' for anyone but the owner —
    see the module docstring for why this is enforced here, not just at the
    settings-patch boundary."""
    requested = store.get_settings(user["id"]).get("chargeProvider", "samvara")
    if requested == "beeminder" and is_owner(user["email"]):
        return "beeminder"
    return "samvara"


def validate_provider_choice(user: dict[str, Any], provider: str) -> None:
    """Used by PATCH /v1/settings: reject a chargeProvider patch outright
    (400/403) instead of silently downgrading it, so a client that tries to
    set 'beeminder' gets a clear answer rather than a setting that looks
    saved but never takes effect."""
    if provider not in VALID_PROVIDERS:
        raise ChargeError(f"Unknown chargeProvider {provider!r}.")
    if provider == "beeminder" and not is_owner(user["email"]):
        raise PermissionError("The Beeminder charge provider is not available on this account.")


async def get_or_create_customer_id(user: dict[str, Any]) -> str:
    existing = user.get("stripe_customer_id")
    if existing:
        return existing
    customer_id = await stripe_billing.create_customer(user["email"], user["id"])
    store.set_stripe_customer_id(user["id"], customer_id)
    return customer_id


async def charge_for_user(user: dict[str, Any], amount: float, note: str,
                          idempotency_key: str | None = None) -> ChargeResult:
    """Charge `amount` USD to whichever provider resolve_provider() picks for
    this user. Raises ChargeError on validation/API failure, same contract as
    beeminder.charge/stripe_billing.charge — the caller (main.py) fails the
    pending ledger row and surfaces this without mutating commitment state."""
    provider = resolve_provider(user)
    if provider == "beeminder":
        try:
            result = await beeminder.charge(amount, note)
        except beeminder.ChargeError as e:
            raise ChargeError(str(e)) from e
        return ChargeResult(charged=result.charged, amount=result.amount,
                            note=result.note, provider="beeminder",
                            provider_charge_id=result.beeminder_id)

    settings_row = store.get_settings(user["id"])
    payment_method_id = settings_row.get("stripePaymentMethodId")
    try:
        customer_id = await get_or_create_customer_id(user)
        result = await stripe_billing.charge(
            customer_id, payment_method_id, amount, note,
            idempotency_key=idempotency_key,
        )
    except stripe_billing.ChargeError as e:
        raise ChargeError(str(e)) from e
    return ChargeResult(charged=result.charged, amount=result.amount,
                        note=result.note, provider="samvara",
                        provider_charge_id=result.provider_charge_id)
