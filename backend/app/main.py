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
import datetime as dt
import logging
import secrets
import sqlite3
import time
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from . import auth, beeminder, logging_config, ratchet
from .config import settings
from .security import (
    AccessRequestBody,
    BumpBody,
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

logging_config.setup(settings.log_level)
log = logging.getLogger("samvara")

app = FastAPI(title="Samvara API", version="1.0.0")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Every log line emitted while handling this request carries this id
    (see logging_config._RequestIdFilter), and it's echoed back in the
    response so a client-reported bug can be grepped straight out of logs.

    Also emits the access-log line itself (method, path, status, duration) —
    uvicorn's own access log runs outside this middleware and can't carry the
    request id, so it's disabled in logging_config.setup() in favor of this."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = logging_config.request_id_ctx.set(rid)
    start = time.monotonic()
    try:
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        log.info("request", extra={
            "method": request.method, "path": request.url.path,
            "status": response.status_code, "duration_ms": duration_ms,
        })
        response.headers["X-Request-Id"] = rid
        return response
    except Exception:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        log.exception("request raised", extra={
            "method": request.method, "path": request.url.path,
            "duration_ms": duration_ms,
        })
        raise
    finally:
        logging_config.request_id_ctx.reset(token)

_origins = settings.allowed_origins
if not _origins:
    if settings.auth_mode == "none":
        _origins = ["*"]  # local dev: no auth, no fixed frontend origin
    else:
        log.warning("ALLOWED_ORIGINS is not set — browsers will be blocked by "
                    "CORS. Set it to your frontend origin(s).")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
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


@app.post("/v1/auth/sign-out", status_code=204, response_class=Response)
async def sign_out(authorization: str | None = Header(default=None)):
    """Revoke the presented session token server-side.

    Without this, signing out only clears the browser's copy while the 30-day
    session stays valid in the database. No auth dependency: revoking an
    unknown or expired token is a harmless no-op, and always answering 204
    means the endpoint can't be used to probe which tokens exist.
    """
    if authorization:
        scheme, _, token_value = authorization.partition(" ")
        if scheme.lower() == "bearer" and token_value:
            store.delete_session(auth.sha256(token_value))


@app.post("/v1/access-requests", status_code=204, response_class=Response)
async def request_access(body: AccessRequestBody):
    """"Request access" from the sign-in gate's denied path.

    No auth (the requester by definition doesn't have any yet). The request is
    persisted first — that's the durable record, and it's what makes the UI's
    "I'll reply soon" true — then a best-effort notification email goes to
    AUTH_EMAIL. A failed email never loses the request; it's still in the table.
    """
    rid = "req_" + secrets.token_hex(6)
    now = int(time.time() * 1000)
    name = body.name.strip()
    email = body.email.strip()
    message = body.message.strip()
    store.save_access_request(rid, name, email, message, now)
    if settings.auth_email:
        try:
            await auth.send_email(
                settings.auth_email,
                f"Samvara access request from {name}",
                f"Name: {name}\nEmail: {email}\n\n{message}",
            )
        except Exception:
            log.exception("access-request notification email failed (request %s persisted)", rid)


# ── health (no auth — lets a load balancer / cron probe cheaply) ──────────────
@app.get("/v1/health")
async def health(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Liveness only: is the process up and answering HTTP at all. Deliberately
    does not touch the database — a health check that depends on the thing it's
    supposed to detect the failure of is a bad health check. See /v1/health/ready
    for "can this instance actually serve traffic". Anonymous callers get
    liveness only; the effective config (whether real charges are armed, the
    cap) is visible only with a valid token."""
    out: dict[str, Any] = {"status": "ok"}
    if token_is_valid(authorization):
        out.update({
            "auth_mode": settings.auth_mode,
            "beeminder_dryrun": settings.beeminder_dryrun,
            "beeminder_configured": bool(settings.beeminder_token),
            "max_charge_usd": settings.max_charge,
        })
    return out


@app.get("/v1/health/ready")
async def readiness(response: Response) -> dict[str, Any]:
    """Readiness: can this instance actually serve traffic right now.

    Liveness answers "is the process up"; this answers "is the database it
    depends on reachable" — a locked WAL file, a full disk, or an unmounted
    volume all leave the process alive but unable to do anything useful.
    No auth: this is meant for a load balancer or orchestrator, which won't
    have a token, and "the DB is unreachable" isn't sensitive on its own.
    """
    db_ok = store.ping()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if db_ok else "unavailable", "checks": {"db": db_ok}}


# ── reads ─────────────────────────────────────────────────────────────────────
@app.get("/v1/commitments", dependencies=[Depends(require_auth)])
async def list_commitments() -> list[dict[str, Any]]:
    # Closest deadline first — the dashboard renders cards in this order. The
    # due strings are uniform ISO-8601 UTC, so they sort lexicographically.
    return sorted(store.list_commitments(), key=lambda cm: cm["current_rung"]["due"])


@app.get("/v1/commitments/{cid}", dependencies=[Depends(require_auth)])
async def get_commitment(cid: str) -> dict[str, Any]:
    return _require(cid)


@app.get("/v1/settings", dependencies=[Depends(require_auth)])
async def get_settings() -> dict[str, Any]:
    return store.get_settings()


# ── writes that never charge ─────────────────────────────────────────────────
@app.post("/v1/commitments", dependencies=[Depends(require_auth)])
async def create_commitment(body: CreateBody) -> dict[str, Any]:
    # The 7-hex-char id can collide (~1 in 268M); regenerate rather than 500.
    for _ in range(3):
        cm = ratchet.new_commitment(body.name, body.base_days, body.base_stake)
        try:
            with store.lock:
                store.insert_commitment(cm)
            return cm
        except sqlite3.IntegrityError:
            continue
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "Could not allocate a commitment id.")


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

# monotonic timestamp of the last live lapse charge per commitment, for the
# duplicate-report debounce below. In-memory is enough: single worker, and the
# window is seconds.
_recent_lapse: dict[str, float] = {}


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
        if (cur["completed"] or cur["awaiting_decision"]
                or cur["awaiting_recommit"] or cur["auto_missed"]):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This rung is already resolved (it may have just auto-charged); "
                "recommit instead of reporting a lapse.")
        last = _recent_lapse.get(cid)
        if last is not None and time.monotonic() - last < settings.lapse_debounce_s:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Duplicate lapse report: a charge for this commitment just landed.")
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
        now_mono = time.monotonic()
        _recent_lapse[cid] = now_mono
        # Prune entries past the window so the dict can't grow forever.
        cutoff = now_mono - settings.lapse_debounce_s
        for k in [k for k, v in _recent_lapse.items() if v < cutoff]:
            del _recent_lapse[k]

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
        # is_past_grace covers both the resolved flags AND the time window, so
        # a rung freshly re-rung by a racing /slip (its due date now days away)
        # is a no-op here rather than a second charge.
        cm = _require(cid)
        if not ratchet.is_past_grace(cm, settings.grace_ms):
            return cm
        r = cm["current_rung"]

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


# ── daily metrics (the Data tab) ─────────────────────────────────────────────
# Fixed vocabulary: the tracked metrics, in display order. `ratio: True` marks
# the ones whose days-with-data ratio the Ratios subtab shows. The frontend
# renders whatever this returns, so adding a metric here is the whole change.
METRICS: list[dict[str, Any]] = [
    {"key": "porn_viewed", "label": "Porn viewed", "ratio": True},
    {"key": "sexual_content_viewed", "label": "Non-porn sexual content viewed", "ratio": True},
    {"key": "masturbation", "label": "Masturbations", "ratio": True},
    {"key": "gaze_goal_set", "label": "Goal set: not looking at women with sexual desire", "ratio": False},
    {"key": "gaze_goal_broken", "label": "That goal broken", "ratio": False},
]
_METRIC_KEYS = {m["key"] for m in METRICS}

# ── end-of-day Beeminder penalty on the "goal broken" tally ──────────────────
# Every +1 here is $1 at stake, but not charged the moment it's tapped: it's
# deferred until the day closes (device tz if the client sent one, else
# METRICS_TZ), so an accidental tap can still be undone with -1 before the
# sweep fires. /v1/tick — already polled every 15 min — is what closes it,
# the same mechanism that already charges auto-missed commitments.
PENALTY_METRIC = "gaze_goal_broken"

# gaze_goal_broken was already being tallied in the Data tab (since
# 2026-07-03, well before this charging feature existed) with no financial
# consequence. Without this floor, the first tick sweep after deploy treats
# every pre-existing day's count as unbilled backlog — since old days have a
# metric_days row but no penalty_days row, count > charged_count(=0) for all
# of them — and charges the entire historical tally at once. Keep this at
# the date the feature shipped; never move it earlier.
PENALTY_START_DAY = "2026-07-18"


def metrics_today(now: dt.datetime | None = None) -> str:
    """The current calendar day (YYYY-MM-DD) in the configured metrics tz."""
    at = now if now is not None else dt.datetime.now(dt.timezone.utc)
    return at.astimezone(ZoneInfo(settings.metrics_tz)).date().isoformat()


def _day_end_utc(day: str, tz_name: str | None) -> dt.datetime:
    """The instant `day` (YYYY-MM-DD) closes — i.e. its next midnight in `tz_name`.

    Falls back to METRICS_TZ if `tz_name` is missing or not a tz the server
    recognizes (e.g. a client sent garbage or nothing at all).
    """
    try:
        zone = ZoneInfo(tz_name) if tz_name else ZoneInfo(settings.metrics_tz)
    except Exception:
        zone = ZoneInfo(settings.metrics_tz)
    d = dt.date.fromisoformat(day)
    midnight = dt.datetime(d.year, d.month, d.day, tzinfo=zone)
    return midnight + dt.timedelta(days=1)


def _penalty_note(count: int, day: str) -> str:
    return f"Samvara: penalty for looking at women with sexual desire ({count}x on {day})"


def _metrics_payload() -> dict[str, Any]:
    today = metrics_today()
    series = store.metric_series()
    count = series.get(PENALTY_METRIC, {}).get(today, 0)
    penalty_row = store.get_penalty_day(today)
    charged = penalty_row["charged_count"] if penalty_row else 0
    return {
        "metrics": METRICS,
        "series": series,
        "today": today,
        "pendingPenalty": {"amount": max(0, count - charged)},
    }


@app.get("/v1/metrics", dependencies=[Depends(require_auth)])
async def get_metrics() -> dict[str, Any]:
    return _metrics_payload()


@app.post("/v1/metrics/{key}/bump", dependencies=[Depends(require_auth)])
async def bump_metric(key: str, body: BumpBody) -> dict[str, Any]:
    if key not in _METRIC_KEYS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No metric {key!r}.")
    if body.delta not in (1, -1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "delta must be 1 or -1.")
    today = metrics_today()
    store.bump_metric(key, today, body.delta)
    if key == PENALTY_METRIC:
        store.upsert_penalty_tz(today, body.tz or settings.metrics_tz)
    return _metrics_payload()


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

    # Penalty sweep: charge the "goal broken" tally for any day that has
    # closed (past midnight in its recorded tz) and isn't fully billed yet.
    penalties_charged: list[dict[str, Any]] = []
    penalty_errors: list[dict[str, Any]] = []
    now = dt.datetime.now(dt.timezone.utc)

    for pending in store.pending_penalties(PENALTY_METRIC, since=PENALTY_START_DAY):
        day = pending["day"]
        async with _charge_lock:
            # Recompute from fresh state: a concurrent tick or a same-day tap
            # may have changed the count or charged_count while we waited.
            row = store.get_penalty_day(day)
            tz = (row["tz"] if row else None) or pending["tz"]
            charged = row["charged_count"] if row else 0
            count = store.metric_count(PENALTY_METRIC, day)
            if count <= charged or now < _day_end_utc(day, tz):
                continue
            amount = count - charged
            try:
                charge = await beeminder.charge(amount, _penalty_note(count, day))
            except beeminder.ChargeError as e:
                penalty_errors.append({"day": day, "error": str(e)})
                continue
            with store.lock:
                store.mark_penalty_charged(day, count)
                store.add_total_charged(amount)
            penalties_charged.append({
                "day": day, "amount": amount, "charge": charge.as_dict(),
            })

    return {
        "charged": charged_list, "charged_count": len(charged_list), "errors": errors,
        "penalties_charged": penalties_charged,
        "penalties_charged_count": len(penalties_charged),
        "penalty_errors": penalty_errors,
    }
