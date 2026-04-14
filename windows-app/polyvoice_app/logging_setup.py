"""Structured logging setup for the Windows app."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

from polyvoice_app import paths

_INSTALLED = False
_BASE_FIELDS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Format logs as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _BASE_FIELDS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure rotating file logging and uncaught exception hooks."""
    global _INSTALLED
    paths.ensure_app_dirs()
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    log_file = paths.log_path()
    existing = [
        handler
        for handler in root.handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
        and getattr(handler, "baseFilename", None) == str(log_file)
    ]
    if not existing:
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)

    if not _INSTALLED:
        sys.excepthook = _make_sys_excepthook(sys.excepthook)
        threading.excepthook = _make_threading_excepthook(threading.excepthook)
        _INSTALLED = True

    logging.getLogger("polyvoice.logging").info(
        "logging configured",
        extra={"event": "logging_configured", "path": str(log_file), "level": level.upper()},
    )


def event_extra(event: str, **fields: Any) -> Mapping[str, Any]:
    return {"event": event, **fields}


def _make_sys_excepthook(previous: Any) -> Any:
    def hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        logging.getLogger("polyvoice.crash").exception(
            "uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback),
            extra={"event": "uncaught_exception", "error": str(exc_value)},
        )
        previous(exc_type, exc_value, exc_traceback)

    return hook


def _make_threading_excepthook(previous: Any) -> Any:
    def hook(args: threading.ExceptHookArgs) -> None:
        logging.getLogger("polyvoice.crash").exception(
            "uncaught thread exception",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            extra={
                "event": "uncaught_thread_exception",
                "thread_name": getattr(args.thread, "name", None),
                "error": str(args.exc_value),
            },
        )
        previous(args)

    return hook
