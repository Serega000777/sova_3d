"""Structured logs with a trace id that survives the hop into a job (T-096).

One request gets one trace id. It goes out on `X-Request-ID`, into every log line the
request writes, and onto the jobs the request enqueues — so a slow model or a failed
kernel run can be followed from the click that caused it, across processes, by one id.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

# Fields that are always safe to log: ids and outcomes, never user content or tokens.
_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)

RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def context() -> dict[str, Any]:
    return dict(_context.get() or {})


def trace_id() -> str | None:
    value = context().get("trace_id")
    return str(value) if value else None


@contextmanager
def bind(**fields: Any) -> Iterator[None]:
    """Add fields to every log line written inside the block (and to nested blocks)."""
    token = _context.set({**context(), **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _context.reset(token)


class JsonFormatter(logging.Formatter):
    """One JSON object per line: greppable in a terminal, queryable in a log store."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **context(),
        }
        for key, value in record.__dict__.items():
            if key not in RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Install the formatter on the root logger. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn installs its own handlers; make them go through ours so access logs match.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def new_trace_id() -> str:
    return str(uuid.uuid4())
