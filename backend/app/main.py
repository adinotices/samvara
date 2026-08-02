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

Multi-tenant: every user-data route depends on current_user (a session token
resolved to a user row — see security.py) and passes that user's id into every
store call. There is no route left that can read or write another user's data
by forgetting a filter; the store methods themselves require the id.

The response shapes are byte-for-byte what the frontend's reference mock
returned, so frontend/api-client.js can pass them straight through with no
reshaping.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import secrets
import time
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from . import auth, beeminder, db, logging_config, ratchet
from .config import settings
from .security import (
    AccessRequestBody,
    BumpBody,
    ChooseNextBody,
    CreateBody,
    InviteBody,
    LapseBody,
    SendCodeBody,
    SettingsPatch,
    VerifyCodeBody,
    current_user,
    require_admin,
    require_auth,
    token_is_valid,
)
from .store import store

logging_config.setup(settings.log_level)
log = logging.getLogger("samvara")

def _parse_device_name(user_agent: str) -> str:
    """Parse a friendly device name from the user-agent string."""
    if not user_agent:
        return "Unknown Device"
    ua = user_agent.lower()
    if "chrome" in ua:
        if "mobile" in ua or "android" in ua:
            return "Chrome Mobile"
        return "Chrome"
    if "firefox" in ua:
        if "mobile" in ua:
            return "Firefox Mobile"
        return "Firefox"
    if "safari" in ua:
        if "mobile" in ua or "iphone" in ua:
            return "Mobile Safari"
        return "Safari"
    if "edg" in ua:
        return "Edge"
    if "android" in ua:
        return "Android Browser"
    return "Unknown Device"

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
def _require(user_id: str, cid: str) -> dict[str, Any]:
    cm = store.get_commitment(user_id, cid)
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
    """Email a 6-digit OTP to the given address, IF that address is allowed to
    sign in (the app owner, always; anyone else only in signup_mode=="open" or
    if invited — see auth.signin_allowed).

    Always returns 204: an unauthorised address, an active send-cooldown, and a
    delivery failure are all indistinguishable from success, so the response
    can't be used to probe which address is allowed or invited. Problems are
    logged server-side instead. Note: the OTP is emailed to the address the
    caller supplied — there's no fixed owner inbox to fall back to anymore,
    since anyone permitted to sign in needs their own code.
    """
    if settings.auth_mode == "none":
        return  # dev: the gate accepts anything, no email needed
    email = body.email.strip().lower()
    if not auth.signin_allowed(email):
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
async def verify_code(body: VerifyCodeBody, request: Request) -> dict[str, str]:
    """Verify an OTP and return a 30-day session token. First successful
    verify for a new address creates the account (see auth.create_session)."""
    if settings.auth_mode == "none":
        return {"token": "dev"}  # auth is off; any bearer value is accepted
    email = body.email.strip().lower()
    if not auth.signin_allowed(email):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired code.")
    if not auth.verify_and_consume_otp(email, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired code.")
    user_agent = request.headers.get("user-agent", "")
    ip_address = request.client.host if request.client else None
    device_name = _parse_device_name(user_agent)
    return {"token": auth.create_session(email, device_name, user_agent, ip_address)}


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


@app.delete("/v1/account", dependencies=[])
async def delete_account(user: dict[str, Any] = Depends(current_user)) -> Response:
    """Erase this account: every commitment, tally, and setting, gone, in one
    transaction (see Store.delete_user). No confirmation step or grace period
    here — 1C is where the account-deletion UX (confirmation, a recovery
    window, an in-app path per the store requirements) gets built; this is the
    underlying primitive it calls. Charge history is the one thing NOT erased
    by this today — see the caveat on Store.delete_user."""
    store.delete_user(user["id"])
    store.log_audit(user["id"], "account_deleted")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── session management ───────────────────────────────────────────────────
@app.get("/v1/sessions")
async def list_sessions(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """List all active devices/sessions for this account with creation and
    last-seen timestamps. Used by the account settings page to show login
    locations and allow revoking specific sessions."""
    devices = store.list_devices(user["id"])
    return {"devices": devices}


@app.delete("/v1/sessions/{device_id}", status_code=204, response_class=Response)
async def revoke_device(device_id: str, user: dict[str, Any] = Depends(current_user)):
    """Revoke all sessions associated with a specific device, immediately
    logging the user out on that device."""
    store.delete_device(user["id"], device_id)
    # Delete all sessions for this device
    with store.engine.connect() as conn:
        conn.execute(
            delete(db.sessions).where(db.sessions.c.device_id == device_id)
        )
        conn.commit()
    store.log_audit(user["id"], "session_revoked", resource_type="device",
                   resource_id=device_id)


@app.delete("/v1/sessions", status_code=204, response_class=Response)
async def revoke_all_sessions(user: dict[str, Any] = Depends(current_user)):
    """Revoke all sessions across all devices, immediately logging out
    everywhere."""
    store.delete_all_devices(user["id"])
    with store.engine.connect() as conn:
        conn.execute(
            delete(db.sessions).where(db.sessions.c.user_id == user["id"])
        )
        conn.commit()
    store.log_audit(user["id"], "all_sessions_revoked")


# ── data export (compliance) ───────────────────────────────────────────────
@app.get("/v1/data-export")
async def export_user_data(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """Export all user data as JSON (commitments, metrics, charges, settings).
    Supports GDPR and app store privacy requirements for data download/portability."""
    data = store.export_user_data(user["id"])
    store.log_audit(user["id"], "data_export")
    return data


# ── audit log ───────────────────────────────────────────────────────────────
@app.get("/v1/audit-log")
async def get_audit_log(user: dict[str, Any] = Depends(current_user),
                        limit: int = 50) -> dict[str, Any]:
    """Retrieve audit log for compliance: list of user actions with timestamps,
    IP addresses, and user agents. Supports store privacy requirements for
    showing user activity history."""
    logs = store.list_audit_logs(user["id"], limit=min(limit, 500))
    return {"audit_logs": logs}


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


# ── invites (owner-only; see security.require_admin) ─────────────────────────
@app.post("/v1/admin/invites", dependencies=[Depends(require_admin)])
async def add_invite(body: InviteBody) -> dict[str, Any]:
    email = body.email.strip().lower()
    store.add_invite(email, body.note)
    return {"email": email, "note": body.note}


@app.get("/v1/admin/invites", dependencies=[Depends(require_admin)])
async def list_invites() -> list[dict[str, Any]]:
    return store.list_invites()


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
@app.get("/v1/commitments")
async def list_commitments(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    # Closest deadline first — the dashboard renders cards in this order. The
    # due strings are uniform ISO-8601 UTC, so they sort lexicographically.
    return sorted(store.list_commitments(user["id"]), key=lambda cm: cm["current_rung"]["due"])


@app.get("/v1/commitments/{cid}")
async def get_commitment(cid: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return _require(user["id"], cid)


@app.get("/v1/settings")
async def get_settings(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return store.get_settings(user["id"])


# ── writes that never charge ─────────────────────────────────────────────────
@app.post("/v1/commitments")
async def create_commitment(body: CreateBody, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    # The 7-hex-char id can collide (~1 in 268M); regenerate rather than 500.
    for _ in range(3):
        cm = ratchet.new_commitment(body.name, body.base_days, body.base_stake)
        try:
            store.insert_commitment(user["id"], cm)
            return cm
        except IntegrityError:
            continue
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "Could not allocate a commitment id.")


@app.post("/v1/commitments/{cid}/confirm-clean")
async def confirm_clean(cid: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    cm = _require(user["id"], cid)
    ratchet.apply_confirm_clean(cm)
    store.update_commitment(user["id"], cm)
    return cm


@app.post("/v1/commitments/{cid}/choose-next")
async def choose_next(cid: str, body: ChooseNextBody, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    cm = _require(user["id"], cid)
    ratchet.apply_choose_next(cm, body.days, body.stake)
    store.update_commitment(user["id"], cm)
    return cm


@app.patch("/v1/settings")
async def update_settings(patch: SettingsPatch, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return store.update_settings(user["id"], patch.model_dump(exclude_none=True))


# ── writes that charge ───────────────────────────────────────────────────────
# Two layers, deliberately not one:
#   * _charge_lock (asyncio.Lock) serializes every charge sequence WITHIN this
#     process, including the `await beeminder.charge(...)` in the middle of
#     it. This is the layer that's load-bearing on SQLite (and hence in the
#     test suite): store.commitment_lock()'s SELECT ... FOR UPDATE is a
#     real lock on Postgres but a silent no-op on SQLite, and — this is the
#     part worth spelling out — store.lock (a threading.RLock) held across an
#     await does NOT serialize concurrent asyncio tasks the way it looks like
#     it should: RLock tracks the OWNING THREAD, not the owning task, and a
#     single-threaded event loop means every task IS that thread, so a second
#     task can re-enter a lock the first task is "holding" while it's
#     suspended on an await. Coarse and global (not per-commitment) — charges
#     are rare, so contention is nil.
#   * store.commitment_lock() (store.py) opens a real DB transaction and
#     SELECTs the commitment FOR UPDATE — the layer that's load-bearing across
#     multiple PROCESSES/workers once this is actually running on Postgres,
#     which asyncio.Lock can't provide (it's one process's lock).
_charge_lock = asyncio.Lock()

_recent_lapse: dict[str, float] = {}


async def _slip_or_miss(user_id: str, cid: str, body: LapseBody, outcome: str) -> dict[str, Any]:
    """Shared body for slip ('lapse') and miss ('missed').

    Charge order matters: on a live (non-dry) run we charge Beeminder before
    mutating or persisting, so a failed charge leaves state untouched.
    """
    cm = _require(user_id, cid)
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
        with store.commitment_lock(user_id, cid) as (conn, cm):
            if cm is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"No commitment {cid!r}.")
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

            ratchet.apply_slip(cm, new_days, new_stake, charged, outcome=outcome)
            store.save_commitment_in(conn, user_id, cm)
            store.add_total_charged_in(conn, user_id, charged)
            now_mono = time.monotonic()
            _recent_lapse[cid] = now_mono
            cutoff = now_mono - settings.lapse_debounce_s
            for k in [k for k, v in _recent_lapse.items() if v < cutoff]:
                del _recent_lapse[k]

    result["commitment"] = cm
    result["charge"] = charge.as_dict()
    return result


@app.post("/v1/commitments/{cid}/slip")
async def slip(cid: str, body: LapseBody, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await _slip_or_miss(user["id"], cid, body, "lapse")


@app.post("/v1/commitments/{cid}/miss")
async def miss(cid: str, body: LapseBody, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await _slip_or_miss(user["id"], cid, body, "missed")


@app.post("/v1/commitments/{cid}/auto-miss")
async def auto_miss(cid: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """Idempotent: charge + park awaiting recommit, but only if not already
    resolved. Returns the commitment unchanged when it's a no-op."""
    async with _charge_lock:
        with store.commitment_lock(user["id"], cid) as (conn, cm):
            if cm is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"No commitment {cid!r}.")
            if not ratchet.is_past_grace(cm, settings.grace_ms):
                return cm
            r = cm["current_rung"]

            charged = r["stake"]
            try:
                charge = await beeminder.charge(charged, _note(cm, "auto-missed"))
            except beeminder.ChargeError as e:
                raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(e)) from e

            ratchet.apply_auto_miss(cm, charged)
            store.save_commitment_in(conn, user["id"], cm)
            store.add_total_charged_in(conn, user["id"], charged)
    cm["_charge"] = charge.as_dict()
    return cm


# ── daily metrics (the Data tab) ─────────────────────────────────────────────
# Fixed vocabulary: the tracked metrics, in display order. `ratio: True` marks
# the ones whose days-with-data ratio the Ratios subtab shows. The frontend
# renders whatever this returns, so adding a metric here is the whole change.
# TODO(1C/D-5): this vocabulary is still global, not user-defined — see the
# app-store-readiness review. Left as-is here; making it per-user is its own
# change, not a side effect of the multi-tenancy port.
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


def metrics_today(user_tz: str, now: dt.datetime | None = None) -> str:
    """The current calendar day (YYYY-MM-DD) in the given user's timezone."""
    at = now if now is not None else dt.datetime.now(dt.timezone.utc)
    try:
        zone = ZoneInfo(user_tz)
    except Exception:
        zone = ZoneInfo(settings.metrics_tz)
    return at.astimezone(zone).date().isoformat()


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


def _metrics_payload(user_id: str, user_tz: str) -> dict[str, Any]:
    today = metrics_today(user_tz)
    series = store.metric_series(user_id)
    count = series.get(PENALTY_METRIC, {}).get(today, 0)
    penalty_row = store.get_penalty_day(user_id, today)
    charged = penalty_row["charged_count"] if penalty_row else 0
    return {
        "metrics": METRICS,
        "series": series,
        "today": today,
        "pendingPenalty": {"amount": max(0, count - charged)},
    }


@app.get("/v1/metrics")
async def get_metrics(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return _metrics_payload(user["id"], user["timezone"])


@app.post("/v1/metrics/{key}/bump")
async def bump_metric(key: str, body: BumpBody, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if key not in _METRIC_KEYS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No metric {key!r}.")
    if body.delta not in (1, -1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "delta must be 1 or -1.")
    today = metrics_today(user["timezone"])
    store.bump_metric(user["id"], key, today, body.delta)
    if key == PENALTY_METRIC:
        store.upsert_penalty_tz(user["id"], today, body.tz or user["timezone"])
    return _metrics_payload(user["id"], user["timezone"])


# ── scheduled sweep (cron / GitHub Actions call this) ────────────────────────
@app.post("/v1/tick", dependencies=[Depends(require_auth)])
async def tick() -> dict[str, Any]:
    """Headless equivalent of the app's per-second checkAutoMiss, across every
    user. System-level route: authenticated by require_auth (the static
    API_TOKEN, or an owner session), never by current_user — there's no single
    "current user" for a sweep that spans everyone.

    Charges and parks every commitment whose grace window has elapsed with no
    response. Safe to call as often as you like — commitments already resolved
    are skipped, so repeated ticks don't double-charge.
    """
    charged_list: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    penalties_charged: list[dict[str, Any]] = []
    penalty_errors: list[dict[str, Any]] = []
    now = dt.datetime.now(dt.timezone.utc)

    for u in store.list_users():
        uid = u["id"]

        candidate_ids = [
            cm["id"] for cm in store.list_commitments(uid)
            if ratchet.is_past_grace(cm, settings.grace_ms)
        ]
        for cid in candidate_ids:
            async with _charge_lock:
                with store.commitment_lock(uid, cid) as (conn, cm):
                    if cm is None or not ratchet.is_past_grace(cm, settings.grace_ms):
                        continue
                    amount = cm["current_rung"]["stake"]
                    try:
                        charge = await beeminder.charge(amount, _note(cm, "auto-missed (tick)"))
                    except beeminder.ChargeError as e:
                        errors.append({"id": cid, "user_id": uid, "error": str(e)})
                        continue
                    ratchet.apply_auto_miss(cm, amount)
                    store.save_commitment_in(conn, uid, cm)
                    store.add_total_charged_in(conn, uid, amount)
                    charged_list.append({
                        "id": cid, "user_id": uid, "amount": amount, "charge": charge.as_dict(),
                    })

        # Penalty sweep: charge the "goal broken" tally for any day that has
        # closed (past midnight in its recorded tz) and isn't fully billed yet.
        for pending in store.pending_penalties(uid, PENALTY_METRIC, since=PENALTY_START_DAY):
            day = pending["day"]
            async with _charge_lock:
                # Recompute from fresh state: a concurrent tick or a same-day
                # tap may have changed the count or charged_count while
                # waiting on the lock.
                row = store.get_penalty_day(uid, day)
                tz = (row["tz"] if row else None) or pending["tz"]
                charged = row["charged_count"] if row else 0
                count = store.metric_count(uid, PENALTY_METRIC, day)
                if count <= charged or now < _day_end_utc(day, tz):
                    continue
                amount = count - charged
                try:
                    charge = await beeminder.charge(amount, _penalty_note(count, day))
                except beeminder.ChargeError as e:
                    penalty_errors.append({"day": day, "user_id": uid, "error": str(e)})
                    continue
                store.mark_penalty_charged(uid, day, count)
                store.add_total_charged(uid, amount)
                penalties_charged.append({
                    "day": day, "user_id": uid, "amount": amount, "charge": charge.as_dict(),
                })

    return {
        "charged": charged_list, "charged_count": len(charged_list), "errors": errors,
        "penalties_charged": penalties_charged,
        "penalties_charged_count": len(penalties_charged),
        "penalty_errors": penalty_errors,
    }
