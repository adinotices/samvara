"""Structured logging: JSON lines to stdout, with a request id on every record.

Before this module existed, nothing in the process ever called
logging.basicConfig or dictConfig. Python's root logger then defaults to
WARNING with no handler, so every log.info(...) call in the codebase (send-code
outcomes, access-request notifications, tick results) was silently dropped —
only warnings and exceptions surfaced, via the interpreter's last-resort
handler, unformatted and with no way to correlate them to a request.

setup() configures the root logger plus uvicorn's own loggers so app code and
framework logs share one format. request_id_ctx is set by main.py's
middleware from the incoming X-Request-Id header (or a generated one) and read
back here via a logging.Filter, so every line emitted while handling a request
carries the id that ties it to that request — including the exact log lines a
Beeminder charge failure produces, which is the case this earns its keep for.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        # Any extra=... fields the caller passed ride along verbatim.
        for k, v in record.__dict__.items():
            if k not in _RESERVED and k not in out and k != "request_id":
                out[k] = v
        if record.exc_info:
            out["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(_RequestIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # uvicorn installs its own handlers on these; replace rather than stack so
    # error logs come out as the same JSON shape as app logs.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False

    # uvicorn's own access log fires at the ASGI-protocol layer, outside the
    # app middleware stack — request_id_ctx isn't set yet when it runs, so
    # every line would read request_id "-". main.py's request_id_middleware
    # logs an equivalent (and better: it adds duration) line that IS
    # correlated, so silence uvicorn's to avoid a second, uncorrelated copy.
    logging.getLogger("uvicorn.access").disabled = True
