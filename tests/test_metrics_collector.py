from scripts.collect_metrics import collect_trace_metrics


def _performance(trace_id: str, *, total: int, ttft: int, context: int, tool: int):
    return {
        "type": "runtime.context",
        "traceId": trace_id,
        "phase": "performance",
        "outcome": "complete",
        "totalDurationMs": total,
        "ttftMs": ttft,
        "contextBuildMs": context,
        "toolDurationMs": tool,
        "peakRssBytes": 100,
    }


def test_trace_metrics_use_performance_terminal_event_for_closure_and_percentiles():
    metrics = collect_trace_metrics([
        _performance("trace-1", total=100, ttft=20, context=10, tool=0),
        _performance("trace-2", total=300, ttft=80, context=50, tool=40),
    ])

    assert metrics["closed"] == 2
    assert metrics["closed_rate"] == "100.0%"
    assert metrics["performance"]["total_duration_ms"]["p50"] == 300
    assert metrics["performance"]["ttft_ms"]["p95"] == 80
    assert metrics["performance"]["tool_duration_ms"]["max"] == 40
