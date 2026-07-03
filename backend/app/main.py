"""Samvara API — HTTP surface.

This is the only layer that knows about HTTP. It wires three collaborators that
each stay ignorant of the others:

  * ratchet.py  — pure state transitions (no I/O),
  * beeminder.py — the one place money moves,
  * store.py    — persistence.

Every mutating endpoint follows the same discipline: compute the transition,
charge Beeminder FIRST when money is owed, and only persist once the charge
succeeds. A charge failure therefore leaves stored state untouched — you are
never charged without the ledger reflecting it, and never advanced without the
charge landing.

The response shapes are byte-for-byte what the frontend's reference mock
returned, so frontend/api-client.js can pass them straight through with no
reshaping.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware

from . import auth, beeminder, ratchet
from .config import settings
from .security import (
    ChooseNextBody,
    CreateBody,
    LapseBody,
    SendCodeBody,
    SettingsPatch,
    VerifyCodeBody,
    require_auth,
    token_is_valid,
)
from .store import store

log = logging.getLogger("samvara")

app = FastAPI(title="Samvara API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── helpers ───────────────────────────────────────────────────────────────────
def _require(cid: str) -> dict[str, Any]:
    cm = store.get_commitment(cid)
    if cm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No commitment {cid!r}.")
    return cm


def _note(cm: dict[str, Any], outcome: str) -> str:
    r = cm["current_rung"]
    return f"Samvara: {outcome} on {cm['name']!r} ({r['days']}-day rung)"


# ── email OTP login (no auth required — these are how you get auth) ──────────
# No return annotation: fastapi 0.115 reads `-> None` as a response model and
# refuses it on a 204 route.
@app.post("/v1/auth/send-code", status_code=204, response_class=Response)
async def send_code(body: SendCodeBody):
    """Email a 6-digit OTP to the configured AUTH_EMAIL.

    Always returns 204: an unauthorised address, an active send-cooldown, and a
    delivery failure are all indistinguishable from success, so the response
    can't be used to probe which address is allowed. Problems are logged
    server-side instead.
    """
    if settings.auth_mode == "none":
        return  # dev: the gate accepts anything, no email needed
    if not settings.auth_email:
        log.warning("send-code requested but AUTH_EMAIL is not configured")
        return
    email = body.email.strip().lower()
    if email != settings.auth_email.strip().lower():
        log.info("send-code for unauthorised address ignored")
        return
    code = auth.issue_otp(email)
    if code is None:
        log.info("send-code inside cooldown; previous code still valid")
        return
    try:
        await auth.send_otp_email(email, code)
    except Exception:
        log.exception("OTP email delivery failed")


@app.post("/v1/auth/verify-code")
async def verify_code(body: VerifyCodeBody) -> dict[str, str]:
    """Verify an OTP and return a 30-day session token."""
    if settings.auth_mode == "none":
        return {"token": "dev"}  # auth is off; any bearer value is accepted
    email = body.email.strip().lower()
    # Belt and braces: only the configured address can ever hold a valid OTP.
    if not settings.auth_email or email != settings.auth_email.strip().lower():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired code.")
    if not auth.verify_and_consume_otp(email, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired code.")
    return {"token": auth.create_session(email)}


# ── health (no auth — lets a load balancer / cron probe cheaply) ──────────────
@app.get("/v1/health")
async def health(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Anonymous callers get liveness only; the effective config (whether real
    charges are armed, the cap) is visible only with a valid token."""
    out: dict[str, Any] = {"status": "ok"}
    if token_is_valid(authorization):
        out.update({
            "auth_mode": settings.auth_mode,
            "beeminder_dryrun": settings.beeminder_dryrun,
            "beeminder_configured": bool(settings.beeminder_token),
            "max_charge_usd": settings.max_charge,
        })
    return out


# ── reads ─────────────────────────────────────────────────────────────────────
@app.get("/v1/commitments", dependencies=[Depends(require_auth)])
async def list_commitments() -> list[dict[str, Any]]:
    return store.list_commitments()


@app.get("/v1/commitments/{cid}", dependencies=[Depends(require_auth)])
async def get_commitment(cid: str) -> dict[str, Any]:
    return _require(cid)


@app.get("/v1/settings", dependencies=[Depends(require_auth)])
async def get_settings() -> dict[str, Any]:
    return store.get_settings()


# ── writes that never charge ─────────────────────────────────────────────────
@app.post("/v1/commitments", dependencies=[Depends(require_auth)])
async def create_commitment(body: CreateBody) -> dict[str, Any]:
    cm = ratchet.new_commitment(body.name, body.base_days, body.base_stake)
    with store.lock:
        store.insert_commitment(cm)
    return cm


@app.post("/v1/commitments/{cid}/confirm-clean", dependencies=[Depends(require_auth)])
async def confirm_clean(cid: str) -> dict[str, Any]:
    with store.lock:
        cm = _require(cid)
        ratchet.apply_confirm_clean(cm)
        store.update_commitment(cm)
    return cm


@app.post("/v1/commitments/{cid}/choose-next", dependencies=[Depends(require_auth)])
async def choose_next(cid: str, body: ChooseNextBody) -> dict[str, Any]:
    with store.lock:
        cm = _require(cid)
        ratchet.apply_choose_next(cm, body.days, body.stake)
        store.update_commitment(cm)
    return cm


@app.patch("/v1/settings", dependencies=[Depends(require_auth)])
async def update_settings(patch: SettingsPatch) -> dict[str, Any]:
    return store.update_settings(patch.model_dump(exclude_none=True))


# ── writes that charge ───────────────────────────────────────────────────────
# One lock serializes every check-charge-persist sequence. Without it, a user
# action and the scheduled /tick could BOTH pass the idempotency check, charge
# Beeminder twice, and record once. Charges are rare, so contention is nil.
# (Process-level, like store.lock — hence the single-worker Dockerfile CMD.)
_charge_lock = asyncio.Lock()


async def _slip_or_miss(cid: str, body: LapseBody, outcome: str) -> dict[str, Any]:
    """Shared body for slip ('lapse') and miss ('missed').

    Charge order matters: on a live (non-dry) run we charge Beeminder before
    mutating or persisting, so a failed charge leaves state untouched.
    """
    cm = _require(cid)
    cur = cm["current_rung"]
    charged = cur["stake"]
    new_days, new_stake = ratchet.resolve_recommit(cur, body.raise_, body.days, body.stake)
    result: dict[str, Any] = {
        "charged": charged,
        "recommit": {"days": new_days, "stake": new_stake},
        "dryRun": body.dryRun,
    }
    if body.dryRun:
        # Preview only: no money, no mutation. Mirrors the mock exactly.
        return result

    async with _charge_lock:
        # Recompute from fresh state: /tick may have charged and re-rung this
        # commitment while we waited on the lock.
        cm = _require(cid)
        cur = cm["current_rung"]
        charged = cur["stake"]
        new_days, new_stake = ratchet.resolve_recommit(cur, body.raise_, body.days, body.stake)
        result["charged"] = charged
        result["recommit"] = {"days": new_days, "stake": new_stake}

        try:
            charge = await beeminder.charge(charged, _note(cm, outcome))
        except beeminder.ChargeError as e:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(e)) from e

        with store.lock:
            ratchet.apply_slip(cm, new_days, new_stake, charged, outcome=outcome)
            store.add_total_charged(charged)
            store.update_commitment(cm)

    result["commitment"] = cm
    result["charge"] = charge.as_dict()
    return result


@app.post("/v1/commitments/{cid}/slip", dependencies=[Depends(require_auth)])
async def slip(cid: str, body: LapseBody) -> dict[str, Any]:
    return await _slip_or_miss(cid, body, "lapse")


@app.post("/v1/commitments/{cid}/miss", dependencies=[Depends(require_auth)])
async def miss(cid: str, body: LapseBody) -> dict[str, Any]:
    return await _slip_or_miss(cid, body, "missed")


@app.post("/v1/commitments/{cid}/auto-miss", dependencies=[Depends(require_auth)])
async def auto_miss(cid: str) -> dict[str, Any]:
    """Idempotent: charge + park awaiting recommit, but only if not already
    resolved. Returns the commitment unchanged when it's a no-op."""
    async with _charge_lock:
        # The idempotency check must sit inside the lock, before the charge —
        # otherwise a concurrent /tick could also pass it and charge again.
        cm = _require(cid)
        r = cm["current_rung"]
        already = (r["auto_missed"] or r["awaiting_recommit"]
                   or r["awaiting_decision"] or r["completed"])
        if already:
            return cm

        charged = r["stake"]
        try:
            charge = await beeminder.charge(charged, _note(cm, "auto-missed"))
        except beeminder.ChargeError as e:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(e)) from e

        with store.lock:
            ratchet.apply_auto_miss(cm, charged)
            store.add_total_charged(charged)
            store.update_commitment(cm)
    cm["_charge"] = charge.as_dict()
    return cm


# ── scheduled sweep (cron / GitHub Actions call this) ────────────────────────
@app.post("/v1/tick", dependencies=[Depends(require_auth)])
async def tick() -> dict[str, Any]:
    """Headless equivalent of the app's per-second checkAutoMiss.

    Charges and parks every commitment whose grace window has elapsed with no
    response. Safe to call as often as you like — commitments already resolved
    are skipped, so repeated ticks don't double-charge.
    """
    charged_list: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    # Snapshot candidate ids only; each is re-read and re-checked under the
    # charge lock so a user action landing mid-sweep can't be double-charged.
    candidate_ids = [
        cm["id"] for cm in store.list_commitments()
        if ratchet.is_past_grace(cm, settings.grace_ms)
    ]

    for cid in candidate_ids:
        async with _charge_lock:
            cm = store.get_commitment(cid)
            if cm is None or not ratchet.is_past_grace(cm, settings.grace_ms):
                continue
            amount = cm["current_rung"]["stake"]
            try:
                charge = await beeminder.charge(amount, _note(cm, "auto-missed (tick)"))
            except beeminder.ChargeError as e:
                errors.append({"id": cid, "error": str(e)})
                continue
            with store.lock:
                ratchet.apply_auto_miss(cm, amount)
                store.add_total_charged(amount)
                store.update_commitment(cm)
            charged_list.append({
                "id": cid, "amount": amount, "charge": charge.as_dict(),
            })

    return {"charged": charged_list, "charged_count": len(charged_list), "errors": errors}
