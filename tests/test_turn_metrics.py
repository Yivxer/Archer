from terminal.api.turn_metrics import TurnPerformance, instrument_turn_events


def test_turn_performance_builds_bounded_terminal_snapshot():
    perf = TurnPerformance(started_at=10.0, cpu_started=2.0)
    perf.observe(
        {"type": "_metric", "stage": "context_ready", "traceId": "trace-1"},
        now=10.03,
        step_duration_ms=30,
    )
    perf.observe(
        {"type": "toolEvent", "toolEvent": {"traceId": "trace-1", "name": "search"}},
        now=10.07,
        step_duration_ms=40,
    )
    perf.observe(
        {"type": "token", "text": "hello"},
        now=10.08,
        step_duration_ms=10,
    )

    event = perf.terminal_event(now=10.20, cpu_now=2.04, peak_rss_bytes=123_456)
    snapshot = event["performanceEvent"]

    assert snapshot["traceId"] == "trace-1"
    assert snapshot["phase"] == "performance"
    assert snapshot["ttftMs"] == 80
    assert snapshot["totalDurationMs"] == 200
    assert snapshot["contextBuildMs"] == 30
    assert snapshot["toolDurationMs"] == 40
    assert snapshot["cpuTimeMs"] == 40
    assert snapshot["peakRssBytes"] == 123_456
    assert snapshot["outcome"] == "complete"


def test_turn_performance_marks_failed_outcome_without_copying_error_text():
    perf = TurnPerformance(started_at=1.0, cpu_started=1.0)
    perf.observe(
        {"type": "error", "detail": "secret user text"},
        now=1.1,
        step_duration_ms=10,
    )
    event = perf.terminal_event(now=1.2, cpu_now=1.1, peak_rss_bytes=1)

    snapshot = event["performanceEvent"]
    assert snapshot["outcome"] == "failed"
    assert "secret user text" not in str(snapshot)


def test_instrumented_turn_emits_performance_before_done():
    events = list(instrument_turn_events(
        iter([
            {"type": "_metric", "stage": "context_ready", "traceId": "trace-1"},
            {"type": "token", "text": "ok"},
            {"type": "done", "done": True},
        ]),
        rss_reader=lambda: 42,
    ))

    assert [event["type"] for event in events] == ["token", "performanceEvent", "done"]
    assert events[1]["performanceEvent"]["traceId"] == "trace-1"
