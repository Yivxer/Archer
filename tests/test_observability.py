"""P5.9 — Observability span tests."""
from __future__ import annotations

import time

from core.observability import (
    bind_trace_context,
    clear_trace_context,
    span_recording,
    trace_span,
)


def test_trace_span_records_duration_and_attributes():
    with span_recording() as records:
        with trace_span("test.op", foo="bar") as span:
            span["extra"] = 1
            time.sleep(0.01)

    assert len(records) == 1
    entry = records[0]
    assert entry["name"] == "test.op"
    assert entry["parent"] is None
    assert entry["attributes"]["foo"] == "bar"
    assert entry["attributes"]["extra"] == 1
    assert entry["duration_ms"] >= 1


def test_trace_span_nesting_sets_parent():
    with span_recording() as records:
        with trace_span("outer"):
            with trace_span("inner"):
                pass

    assert [r["name"] for r in records] == ["inner", "outer"]
    assert records[0]["parent"] == "outer"
    assert records[1]["parent"] is None


def test_bind_trace_context_does_not_break_spans():
    with span_recording() as records:
        bind_trace_context(trace_id="sess-1")
        try:
            with trace_span("context.op"):
                pass
        finally:
            clear_trace_context("trace_id")

    assert records[0]["name"] == "context.op"


def test_memory_retrieve_span_on_skip():
    from memory.retrieve import for_context

    with span_recording() as records:
        core, related = for_context("你好")

    assert core == [] and related == []
    assert records[0]["name"] == "memory.retrieve"
    assert records[0]["attributes"]["skipped"] is True
