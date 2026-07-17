from scripts.collect_metrics import collect_trace_metrics


def _performance(trace_id: str, *, total: int, ttft: int, context: int, tool: int, prompt: int = 0):
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
        "tokenUsage": {
            "promptTokens": prompt,
            "completionTokens": 20,
            "totalTokens": prompt + 20,
            "historyEstimatedTokens": prompt - 10,
            "tokenLimit": 50_000,
            "compressionTriggered": prompt > 40_000,
        },
    }


def test_trace_metrics_use_performance_terminal_event_for_closure_and_percentiles():
    metrics = collect_trace_metrics([
        _performance("trace-1", total=100, ttft=20, context=10, tool=0, prompt=1000),
        _performance("trace-2", total=300, ttft=80, context=50, tool=40, prompt=45_000),
    ])

    assert metrics["closed"] == 2
    assert metrics["closed_rate"] == "100.0%"
    assert metrics["performance"]["total_duration_ms"]["p50"] == 300
    assert metrics["performance"]["ttft_ms"]["p95"] == 80
    assert metrics["performance"]["tool_duration_ms"]["max"] == 40
    assert metrics["performance"]["prompt_tokens"]["p95"] == 45_000
    assert metrics["performance"]["compression_trigger_rate"] == {
        "count": 2, "triggered": 1, "rate": "50.0%",
    }
