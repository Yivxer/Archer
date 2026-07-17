"""Bounded, privacy-safe performance telemetry for one chat turn."""
from __future__ import annotations

import resource
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from uuid import uuid4


def process_peak_rss_bytes() -> int:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def _trace_id(event: dict) -> str:
    direct = str(event.get("traceId") or "").strip()
    if direct:
        return direct
    for key in ("runtimeContextEvent", "statusEvent", "toolEvent", "failureHintEvent"):
        payload = event.get(key)
        if isinstance(payload, dict) and payload.get("traceId"):
            return str(payload["traceId"]).strip()
    return ""


@dataclass
class TurnPerformance:
    started_at: float
    cpu_started: float
    trace_id: str = ""
    context_build_ms: int = 0
    tool_duration_ms: int = 0
    ttft_ms: int | None = None
    outcome: str = "complete"
    token_usage: dict[str, Any] | None = None

    def observe(self, event: dict, *, now: float, step_duration_ms: int) -> None:
        self.trace_id = self.trace_id or _trace_id(event)
        if event.get("type") == "_metric" and event.get("stage") == "context_ready":
            self.context_build_ms = max(0, round((now - self.started_at) * 1000))
            return
        if event.get("type") == "_metric" and event.get("stage") == "token_context":
            self.token_usage = {
                "historyEstimatedTokens": max(0, int(event.get("historyEstimatedTokens") or 0)),
                "tokenLimit": max(0, int(event.get("tokenLimit") or 0)),
                "compressionTriggered": bool(event.get("compressionTriggered")),
            }
            return
        if event.get("type") == "_metric" and event.get("stage") == "token_usage":
            usage = event.get("tokenUsage") if isinstance(event.get("tokenUsage"), dict) else {}
            self.token_usage = {
                **(self.token_usage or {}),
                "promptTokens": max(0, int(usage.get("promptTokens") or 0)),
                "completionTokens": max(0, int(usage.get("completionTokens") or 0)),
                "totalTokens": max(0, int(usage.get("totalTokens") or 0)),
            }
            return
        if event.get("toolEvent"):
            self.tool_duration_ms += max(0, int(step_duration_ms))
        if self.ttft_ms is None and event.get("type") == "token" and event.get("text"):
            self.ttft_ms = max(0, round((now - self.started_at) * 1000))
        if event.get("type") == "error" or event.get("failureHintEvent"):
            self.outcome = "failed"

    def terminal_event(self, *, now: float, cpu_now: float, peak_rss_bytes: int) -> dict:
        total_ms = max(0, round((now - self.started_at) * 1000))
        snapshot = {
            "id": f"performance-{uuid4().hex[:8]}",
            "traceId": self.trace_id,
            "task": "chat_turn",
            "phase": "performance",
            "userIntent": "chat_turn",
            "lastResult": self.outcome,
            "expectedNext": "trace_closed",
            "outcome": self.outcome,
            "totalDurationMs": total_ms,
            "contextBuildMs": self.context_build_ms,
            "toolDurationMs": self.tool_duration_ms,
            "cpuTimeMs": max(0, round((cpu_now - self.cpu_started) * 1000)),
            "peakRssBytes": max(0, int(peak_rss_bytes)),
        }
        if self.ttft_ms is not None:
            snapshot["ttftMs"] = self.ttft_ms
        if self.token_usage:
            snapshot["tokenUsage"] = self.token_usage
        return {"type": "performanceEvent", "performanceEvent": snapshot}


def instrument_turn_events(
    events,
    *,
    clock: Callable[[], float] = time.perf_counter,
    cpu_clock: Callable[[], float] = time.process_time,
    rss_reader: Callable[[], int] = process_peak_rss_bytes,
) -> Iterator[dict]:
    from infrastructure.observability import bind_trace_context, clear_trace_context

    perf = TurnPerformance(started_at=clock(), cpu_started=cpu_clock())
    iterator = iter(events)
    completed = False
    terminal_emitted = False
    try:
        while True:
            step_started = clock()
            try:
                event = next(iterator)
            except StopIteration:
                completed = True
                break
            now = clock()
            perf.observe(
                event,
                now=now,
                step_duration_ms=max(0, int((now - step_started) * 1000)),
            )
            if event.get("type") == "_metric":
                if event.get("stage") == "trace_started" and perf.trace_id:
                    bind_trace_context(trace_id=perf.trace_id)
                continue
            if event.get("type") == "done":
                yield perf.terminal_event(
                    now=clock(),
                    cpu_now=cpu_clock(),
                    peak_rss_bytes=rss_reader(),
                )
                terminal_emitted = True
            yield event
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()
        clear_trace_context("trace_id")
    if completed and not terminal_emitted:
        yield perf.terminal_event(
            now=clock(),
            cpu_now=cpu_clock(),
            peak_rss_bytes=rss_reader(),
        )
