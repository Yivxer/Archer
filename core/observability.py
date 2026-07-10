"""Compatibility exports for the infrastructure observability layer."""
from infrastructure.observability import (
    bind_trace_context,
    clear_trace_context,
    configure_logging,
    get_logger,
    get_recorded_spans,
    span_recording,
    trace_span,
)

__all__ = [
    "bind_trace_context",
    "clear_trace_context",
    "configure_logging",
    "get_logger",
    "get_recorded_spans",
    "span_recording",
    "trace_span",
]
