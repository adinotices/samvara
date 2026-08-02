"""Stripe charge client — the consumer-facing charge provider.

Mirrors beeminder.py's shape deliberately (ChargeError/ChargeResult, the same
_validate floor/cap, the same raw-httpx style instead of the `stripe` SDK, to
keep this dependency-free like the rest of the money paths). The difference
that matters: money charged here is charged to *Samvara's* Stripe account —
the user's card is billed directly and Samvara keeps the funds as the
accountability penalty. This is the only provider ordinary users can select
(see billing.py for the dispatch + the Beeminder-is-owner-only gate).

Handles SCA/3-D Secure: when a charge requires customer authentication
(requires_action status), returns a pending ChargeResult with the
payment_intent_id. The webhook listener (security.py) watches for
payment_intent.succeeded events and commits the charge once authenticated.

STRIPE_SECRET_KEY decides live vs. test mode by which key you set (sk_live_...
vs sk_test_...) — that's Stripe's own equivalent of BEEMINDER_DRYRUN; there is
no separate dryrun flag here because a PaymentIntent created against a test
key already can't move real money.
"""
from __future__ import annotations

import logging

import httpx

from .config import settings

log = logging.getLogger("samvara.stripe")

API_BASE = "https://api.stripe.com/v1/"


class ChargeError(Exception):
    pass


class ChargeResult:
    def __init__(self, charged: bool, amount: float, note: str,
                 provider_charge_id: str | None, status: str = "succeeded"):
        self.charged = charged
        self.amount = amount
        self.note = note
        self.provider_charge_id = provider_charge_id
        self.status = status  # 'succeeded' | 'requires_action'

    def as_dict(self) -> dict:
        return {
            "charged": self.charged,
            "amount": self.amount,
            "note": self.note,
            "provider_charge_id": self.provider_charge_id,
            "status": self.status,
        }


def _validate(amount: float) -> None:
    if amount < settings.min_stake:
        raise ChargeError(
            f"Stake ${amount:.2f} is below the ${settings.min_stake:.2f} minimum."
        )
    if amount > settings.max_charge:
        raise ChargeError(
            f"Stake ${amount:.2f} exceeds the MAX_CHARGE_USD cap of "
            f"${settings.max_charge:.2f}. Refusing to charge."
        )


def _auth() -> tuple[str, str]:
    # Stripe's convention: HTTP Basic auth, secret key as the username, empty
    # password.
    return (settings.stripe_secret_key, "")


async def _post(path: str, data: dict, idempotency_key: str | None = None) -> dict:
    headers = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                API_BASE + path, data=data, auth=_auth(), headers=headers,
            )
    except httpx.HTTPError as e:  # network-level failure
        log.error("stripe request failed", extra={"path": path, "error": str(e)})
        raise ChargeError(f"Stripe request failed: {e}") from e

    return _unwrap(path, resp)


async def _get(path: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(API_BASE + path, auth=_auth())
    except httpx.HTTPError as e:  # network-level failure
        log.error("stripe request failed", extra={"path": path, "error": str(e)})
        raise ChargeError(f"Stripe request failed: {e}") from e

    return _unwrap(path, resp)


def _unwrap(path: str, resp: httpx.Response) -> dict:
    if resp.status_code >= 400:
        body = resp.json() if resp.content else {}
        message = body.get("error", {}).get("message", resp.text)
        log.error("stripe request rejected", extra={
            "path": path, "status": resp.status_code,
        })
        raise ChargeError(f"Stripe request failed ({resp.status_code}): {message}")

    return resp.json() if resp.content else {}


async def create_customer(email: str, user_id: str) -> str:
    """Create a Stripe Customer for a user who has none yet. Idempotent at
    the call site (store.set_stripe_customer_id is only written once — see
    billing.get_or_create_customer_id), not here."""
    if not settings.stripe_secret_key:
        raise ChargeError("STRIPE_SECRET_KEY is not set; cannot create a customer.")
    body = await _post("customers", {
        "email": email,
        "metadata[user_id]": user_id,
    })
    return body["id"]


async def create_setup_intent(customer_id: str) -> dict:
    """A SetupIntent client secret for the mobile client's Stripe SDK to
    collect and confirm a card against, off-session (the card is saved for
    future automatic penalty charges, not charged now)."""
    if not settings.stripe_secret_key:
        raise ChargeError("STRIPE_SECRET_KEY is not set; cannot start card setup.")
    body = await _post("setup_intents", {
        "customer": customer_id,
        "payment_method_types[]": "card",
        "usage": "off_session",
    })
    return {"clientSecret": body["client_secret"], "id": body["id"]}


async def get_setup_intent_payment_method(setup_intent_id: str) -> str:
    """The client's native Stripe SDK confirms a SetupIntent but doesn't
    reliably hand back the raw payment_method id across SDK versions — so
    the server looks it up itself once the client reports the SetupIntent
    id as done. Raises ChargeError if the SetupIntent never actually
    attached a payment method (e.g. the client claims success incorrectly)."""
    if not settings.stripe_secret_key:
        raise ChargeError("STRIPE_SECRET_KEY is not set; cannot look up card setup.")
    body = await _get(f"setup_intents/{setup_intent_id}")
    payment_method_id = body.get("payment_method")
    if not payment_method_id:
        raise ChargeError("SetupIntent has no attached payment method yet.")
    return payment_method_id


async def set_default_payment_method(customer_id: str, payment_method_id: str) -> None:
    await _post(f"customers/{customer_id}", {
        "invoice_settings[default_payment_method]": payment_method_id,
    })


async def charge(customer_id: str, payment_method_id: str, amount: float,
                 note: str, idempotency_key: str | None = None) -> ChargeResult:
    """Charge `amount` USD to the customer's saved card, off-session (no user
    present to authenticate — this fires from a background sweep or a slip/
    miss report, same as beeminder.charge). Returns ChargeResult with status:
      - 'succeeded': charge completed immediately (no auth needed)
      - 'requires_action': customer auth required (3D Secure/SCA); charge is
        pending webhook confirmation
    Raises ChargeError on validation/API failure (decline, network, etc), so
    the caller can surface it without mutating state."""
    _validate(amount)
    if not settings.stripe_secret_key:
        raise ChargeError("STRIPE_SECRET_KEY is not set; cannot charge.")
    if not customer_id or not payment_method_id:
        raise ChargeError(
            "No payment method on file. Add a card in Settings before "
            "recording a lapse/miss."
        )

    body = await _post("payment_intents", {
        "amount": str(int(round(amount * 100))),  # smallest currency unit
        "currency": "usd",
        "customer": customer_id,
        "payment_method": payment_method_id,
        "off_session": "true",
        "confirm": "true",
        "description": note[:500],
    }, idempotency_key=idempotency_key)

    status_ = body.get("status")

    if status_ == "succeeded":
        log.info("stripe charge succeeded", extra={"amount": amount})
        return ChargeResult(charged=True, amount=amount, note=note,
                             provider_charge_id=body.get("id"), status="succeeded")

    elif status_ == "requires_action":
        # Customer auth required (3D Secure/SCA). Charge is pending webhook
        # confirmation. Store payment_intent_id as provider_charge_id; webhook
        # will update the record when customer authenticates.
        log.info("stripe charge requires authentication", extra={
            "amount": amount, "payment_intent_id": body.get("id"),
        })
        return ChargeResult(charged=False, amount=amount, note=note,
                             provider_charge_id=body.get("id"), status="requires_action")

    else:
        log.error("stripe payment_intent did not succeed", extra={
            "amount": amount, "status": status_,
        })
        raise ChargeError(f"Stripe charge did not succeed (status={status_}).")
