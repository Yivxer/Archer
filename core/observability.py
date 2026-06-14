"""P5.9 — Structured logging and lightweight trace spans."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

try:
    import structlog
except ImportError:  # pragma: no cover - structlog is a declared dependency
    structlog = None  # type: ignore[assignment]

_configured = False
_span_stack: ContextVar[list[str]] = ContextVar("_archer_span_stack", default=[])
_span_recorder: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "_archer_span_recorder", default=None
)


def configure_logging(*, level: int = logging.INFO) -> None:
    """Configure structlog once; safe to call repeatedly."""
    global _configured
    if _configured:
        return
    if structlog is None:
        logging.basicConfig(level=level)
        _configured = True
        return

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str = "archer"):
    configure_logging()
    if structlog is None:
        return logging.getLogger(name)
    return structlog.get_logger(name)


def bind_trace_context(**fields: Any) -> None:
    """Attach correlation fields to subsequent log lines in this context."""
    configure_logging()
    if structlog is None:
        return
    structlog.contextvars.bind_contextvars(**fields)


def clear_trace_context(*keys: str) -> None:
    configure_logging()
    if structlog is None:
        return
    if keys:
        structlog.contextvars.unbind_contextvars(*keys)
    else:
        structlog.contextvars.clear_contextvars()


@contextmanager
def span_recording(enabled: bool = True) -> Iterator[list[dict[str, Any]]]:
    """Collect span records in-memory for tests."""
    if not enabled:
        yield []
        return
    records: list[dict[str, Any]] = []
    token = _span_recorder.set(records)
    try:
        yield records
    finally:
        _span_recorder.reset(token)


def get_recorded_spans() -> list[dict[str, Any]]:
    recorder = _span_recorder.get()
    return list(recorder or [])


def _record_span(entry: dict[str, Any]) -> None:
    recorder = _span_recorder.get()
    if recorder is not None:
        recorder.append(entry)


@contextmanager
def trace_span(name: str, **attributes: Any) -> Iterator[dict[str, Any]]:
    """Nested timing span with structured start/end logs."""
    configure_logging()
    log = get_logger("archer.trace")

    stack = list(_span_stack.get())
    parent = stack[-1] if stack else None
    stack.append(name)
    stack_token = _span_stack.set(stack)

    attrs = dict(attributes)
    start = time.perf_counter()
    log_payload = {"event": "span.start", "span": name, "parent": parent, **attrs}
    if hasattr(log, "info"):
        log.info(**log_payload)
    else:
        log.info("%s", log_payload)

    try:
        yield attrs
    finally:
        duration_ms = int((time.perf_counter() - start) * 1000)
        attrs["duration_ms"] = duration_ms
        end_payload = {
            "event": "span.end",
            "span": name,
            "parent": parent,
            **attrs,
        }
        if hasattr(log, "info"):
            log.info(**end_payload)
        else:
            log.info("%s", end_payload)

        _record_span(
            {
                "name": name,
                "parent": parent,
                "attributes": dict(attrs),
                "duration_ms": duration_ms,
            }
        )
        _span_stack.reset(stack_token)
