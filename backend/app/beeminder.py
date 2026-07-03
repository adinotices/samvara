"""Beeminder charge client.

Wraps POST /charges (https://api.beeminder.com/#charge). Money is charged to
the owner of BEEMINDER_TOKEN and goes to Beeminder. This is the one place in
the system that moves real money, so the safety rails live here:

  * amounts below MIN_STAKE are rejected (Beeminder's own floor),
  * amounts above MAX_CHARGE_USD are rejected (your cap against a bug),
  * BEEMINDER_DRYRUN=true routes every charge through Beeminder's dryrun flag
    so you can exercise the whole flow before arming real charges.
"""
from __future__ import annotations

import httpx

from .config import settings

API_BASE = "https://www.beeminder.com/api/v1/"


class ChargeError(Exception):
    pass


class ChargeResult:
    def __init__(self, charged: bool, amount: float, note: str,
                 beeminder_id: str | None, dryrun: bool):
        self.charged = charged
        self.amount = amount
        self.note = note
        self.beeminder_id = beeminder_id
        self.dryrun = dryrun

    def as_dict(self) -> dict:
        return {
            "charged": self.charged,
            "amount": self.amount,
            "note": self.note,
            "beeminder_id": self.beeminder_id,
            "dryrun": self.dryrun,
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


async def charge(amount: float, note: str) -> ChargeResult:
    """Charge `amount` USD via Beeminder. Honors the global dryrun flag.

    Returns a ChargeResult. Raises ChargeError on validation/API failure so the
    caller can surface it without mutating state.
    """
    _validate(amount)
    if not settings.beeminder_token:
        raise ChargeError("BEEMINDER_TOKEN is not set; cannot charge.")

    params: dict[str, str] = {
        "auth_token": settings.beeminder_token,
        "amount": f"{amount:.2f}",
        "note": note,
    }
    if settings.beeminder_user:
        params["user_id"] = settings.beeminder_user
    if settings.beeminder_dryrun:
        params["dryrun"] = "1"

    url = API_BASE + "charges.json"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, data=params)
    except httpx.HTTPError as e:  # network-level failure
        raise ChargeError(f"Beeminder request failed: {e}") from e

    if resp.status_code >= 400:
        raise ChargeError(f"Beeminder charge failed ({resp.status_code}): {resp.text}")

    body = resp.json() if resp.content else {}
    return ChargeResult(
        charged=not settings.beeminder_dryrun,
        amount=amount,
        note=note,
        beeminder_id=str(body.get("id")) if body.get("id") is not None else None,
        dryrun=settings.beeminder_dryrun,
    )
