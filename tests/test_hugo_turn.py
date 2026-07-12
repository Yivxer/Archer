import time

import pytest

from terminal.api.hugo_turn import HugoTurnDependencies, iter_hugo_turn_events


def _event(status="complete"):
    return {"type": "tool_event", "toolEvent": {"status": status}}


def _deps(*, delete, redeploy, existing, publish, agent):
    return HugoTurnDependencies(
        delete=delete,
        redeploy=redeploy,
        deploy_existing=existing,
        publish=publish,
        agent=agent,
        trace_event=lambda event, trace_id: {**event, "traceId": trace_id},
        failure_hint=lambda exc, **kwargs: {"detail": str(exc), **kwargs},
    )


def test_hugo_turn_uses_direct_paths_before_agent_fallback():
    calls = []
    dependencies = _deps(
        delete=lambda query: calls.append("delete"),
        redeploy=lambda query, refs, messages: calls.append("redeploy"),
        existing=lambda messages, query: (calls.append("existing") or ([_event()], "published")),
        publish=lambda query, refs, messages: (_ for _ in ()).throw(AssertionError("publish called")),
        agent=lambda messages, query, file_refs: (_ for _ in ()).throw(AssertionError("agent called")),
    )

    events = list(iter_hugo_turn_events(
        query="deploy", file_refs=[], messages=[], intent="chat", selected_tools={"hugo_blog": object()},
        memory_scope=[], trace_id="trace-1", dependencies=dependencies,
    ))

    assert calls == ["delete", "redeploy", "existing"]
    assert [event["type"] for event in events] == ["tool_event", "ready", "token", "done"]
    assert events[0]["traceId"] == "trace-1"


def test_hugo_turn_emits_heartbeat_while_direct_workflow_runs():
    def slow_delete(query):
        time.sleep(0.02)
        return ([_event()], "published")

    events = list(iter_hugo_turn_events(
        query="deploy", file_refs=[], messages=[], intent="chat", selected_tools={"hugo_blog": object()},
        memory_scope=["local"], trace_id="trace-1",
        dependencies=_deps(delete=slow_delete, redeploy=lambda *args: None, existing=lambda *args: None, publish=lambda *args: None, agent=lambda *args: None),
        heartbeat_seconds=0.001,
    ))

    assert any(event.get("statusEvent", {}).get("intentLabel") == "枫弋札记部署中" for event in events)


def test_hugo_turn_emits_failure_hint_for_blocked_result():
    events = list(iter_hugo_turn_events(
        query="deploy", file_refs=[], messages=[], intent="chat", selected_tools={"hugo_blog": object()},
        memory_scope=[], trace_id="trace-1",
        dependencies=_deps(delete=lambda query: ([_event("blocked")], "blocked"), redeploy=lambda *args: None, existing=lambda *args: None, publish=lambda *args: None, agent=lambda *args: None),
    ))

    assert events[1]["type"] == "failureHintEvent"


def test_hugo_turn_uses_agent_after_all_direct_paths_miss():
    events = list(iter_hugo_turn_events(
        query="deploy", file_refs=[], messages=[], intent="chat", selected_tools={"hugo_blog": object()},
        memory_scope=[], trace_id="trace-1",
        dependencies=_deps(delete=lambda *args: None, redeploy=lambda *args: None, existing=lambda *args: None, publish=lambda *args: None, agent=lambda *args: (None, [_event()], "agent summary")),
    ))

    assert events[-2] == {"type": "token", "text": "agent summary"}


def test_hugo_turn_raises_timeout_when_worker_exceeds_limit():
    with pytest.raises(TimeoutError, match="hugo workflow total timeout"):
        list(iter_hugo_turn_events(
            query="deploy", file_refs=[], messages=[], intent="chat", selected_tools={"hugo_blog": object()},
            memory_scope=[], trace_id="trace-1",
            dependencies=_deps(delete=lambda *args: time.sleep(0.02), redeploy=lambda *args: None, existing=lambda *args: None, publish=lambda *args: None, agent=lambda *args: None),
            heartbeat_seconds=0.001,
            total_timeout_seconds=0.002,
        ))
