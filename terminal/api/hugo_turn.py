"""Dedicated deterministic Hugo execution branch for Desktop chat turns."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4


@dataclass(frozen=True)
class HugoTurnDependencies:
    delete: Callable
    redeploy: Callable
    deploy_existing: Callable
    publish: Callable
    agent: Callable
    trace_event: Callable
    failure_hint: Callable


def iter_hugo_turn_events(
    *, query: str, file_refs: list[dict] | None, messages: list[dict],
    intent: str, selected_tools, memory_scope, trace_id: str,
    dependencies: HugoTurnDependencies, heartbeat_seconds: float = 8.0,
    total_timeout_seconds: float = 300.0,
):
    output: queue.Queue[tuple[str, object]] = queue.Queue()

    def run_workflow() -> None:
        try:
            direct = dependencies.delete(query)
            if not direct:
                direct = dependencies.redeploy(query, file_refs or [], messages)
            if not direct:
                direct = dependencies.deploy_existing(messages, query)
            if not direct:
                direct = dependencies.publish(query, file_refs or [], messages)
            if direct:
                output.put(("result", direct))
                return
            _, agent_events, agent_summary = dependencies.agent(messages, query, file_refs or [])
            output.put(("result", (agent_events, agent_summary)))
        except Exception as exc:
            output.put(("error", exc))

    threading.Thread(target=run_workflow, daemon=True).start()
    started = time.monotonic()
    while True:
        if time.monotonic() - started > total_timeout_seconds:
            raise TimeoutError("hugo workflow total timeout")
        try:
            kind, value = output.get(timeout=heartbeat_seconds)
        except queue.Empty:
            yield {
                "type": "statusEvent",
                "statusEvent": {
                    "id": f"hugo-wait-{uuid4().hex[:8]}",
                    "intentType": intent,
                    "intentLabel": "枫弋札记部署中",
                    "matchedSkills": list(selected_tools.keys()),
                    "isBackground": False,
                    "memoryScope": memory_scope,
                    "traceId": trace_id,
                },
            }
            continue
        if kind == "error":
            raise value
        hugo_events, hugo_summary = value
        break

    for event in hugo_events:
        yield dependencies.trace_event(event, trace_id)
    if any(
        isinstance(event, dict)
        and event.get("toolEvent", {}).get("status") == "blocked"
        for event in hugo_events
    ):
        yield {
            "type": "failureHintEvent",
            "failureHintEvent": dependencies.failure_hint(
                RuntimeError(hugo_summary or "hugo workflow failed"),
                stage="hugo_workflow",
                trace_id=trace_id,
            ),
        }
    yield {"type": "ready", "ready": True}
    yield {
        "type": "token",
        "text": hugo_summary or "未能完成枫弋札记操作。请用附件添加 .md 文件，或说明要部署哪篇文章。",
    }
    yield {"type": "done", "done": True}
