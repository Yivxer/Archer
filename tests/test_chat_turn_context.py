from datetime import datetime
from types import SimpleNamespace

from core.runtime_context import create_runtime_context
from memory.migrations import run_migrations
from terminal.api.chat_turn_context import (
    FullTurnDependencies,
    _attach_task_plan_shadow,
    prepare_full_turn,
)
from terminal.api.turn_pipeline import ClassifiedTurn, OrchestratedTurn


def _event(name: str) -> dict:
    return {"type": "tool_event", "toolEvent": {"name": name}}


def test_attach_task_plan_shadow_adds_queryable_runtime_receipt(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    runtime = create_runtime_context(
        db_path=db_path,
        clock=lambda: datetime(2026, 7, 25, 10, 0, 0),
    )
    plan_event = {
        "id": "plan-1",
        "title": "检查并整理材料",
        "status": "proposed",
        "steps": [
            {
                "id": 1,
                "action": "inspect_context",
                "tool": "project_context",
                "requiresApproval": False,
            }
        ],
    }

    projected = _attach_task_plan_shadow(
        plan_event,
        runtime_context=runtime,
        trace_id="trace-plan-1",
    )

    assert projected is not None
    assert projected["shadowProjection"]["status"] == "aligned"
    assert projected["shadowProjection"]["shadowState"] == "waiting_user"


def test_prepare_full_turn_preserves_context_event_order_and_trace_id():
    orchestration = SimpleNamespace(
        needs_tools=False,
        needs_job=False,
        memory_scope=["local"],
        matched_skills=["web_search"],
    )
    tool_plan = SimpleNamespace(obsidian_preview=False)
    selected_turn_tools = SimpleNamespace(
        turn_plan=SimpleNamespace(),
        selected_tools={"web_search": object()},
        tool_plan=tool_plan,
    )
    dependencies = FullTurnDependencies(
        classify=lambda messages: ClassifiedTurn(
            query="hello",
            prior_history=[],
            intent_info={"intent": "chat", "needs_memory": True, "needs_tools": False, "intent_label": "聊天"},
        ),
        orchestrate=lambda query, history, soul: OrchestratedTurn(
            orchestration, ["local"], "plan", "mode", "skills",
            {"id": "plan-1"}, {"id": "orchestration-1"},
        ),
        soul_insight=lambda: "soul",
        resolve_limits=lambda *args, **kwargs: SimpleNamespace(retrieve_total=3),
        load_config=lambda: {"persona": {"mode_auto": True}},
        active_expert=lambda cfg: {"label": "General"},
        active_expert_id=lambda cfg: "general",
        expert_allowlist=lambda expert: set(),
        format_expert=lambda expert: "expert",
        scoped_skills=lambda cfg: {"web_search": object()},
        select_tools=lambda *args, **kwargs: selected_turn_tools,
        decide=lambda query, **kwargs: SimpleNamespace(
            handling="converse", action_requests=(), confidence=0.9, summary="chat",
        ),
        shadow_events=lambda runtime: [_event("shadow")],
        file_context=lambda refs: ("file context", [_event("file")]),
        vault=lambda messages, **kwargs: SimpleNamespace(
            messages=[{"role": "system", "content": "vault"}, *messages],
            events=[_event("vault")],
        ),
        memory=lambda messages, **kwargs: SimpleNamespace(
            messages=[{"role": "system", "content": "memory"}, *messages],
            events=[_event("memory")],
            receipt={"triggered": True, "reason": "test", "hitCount": 1, "injectedCount": 1},
        ),
        obsidian=lambda messages, **kwargs: SimpleNamespace(
            messages=[{"role": "system", "content": "obsidian"}, *messages],
            events=[_event("obsidian")],
        ),
        web=lambda messages, **kwargs: SimpleNamespace(
            messages=[{"role": "system", "content": "web"}, *messages],
            events=[_event("web")],
        ),
        event_factory=lambda *args, **kwargs: _event(args[1]),
        trace_event=lambda event, trace_id: {**event, "traceId": trace_id},
        runtime_event=lambda **kwargs: {"id": "runtime-1", "traceId": kwargs["trace_id"]},
        extract_obsidian_path=lambda query: None,
    )

    prepared = prepare_full_turn(
        [{"role": "user", "content": "hello"}],
        memory_mode="full",
        obsidian_mode="summary",
        file_refs=[],
        runtime_context=None,
        trace_id="trace-1",
        dependencies=dependencies,
    )

    assert [event.get("toolEvent", {}).get("name", event["type"]) for event in prepared.events] == [
        "shadow", "file", "vault", "orchestrationEvent", "planEvent",
        "runtimeContextEvent", "statusEvent", "memory", "runtimeContextEvent", "obsidian", "web",
    ]
    assert prepared.events[2]["traceId"] == "trace-1"
    assert prepared.events[3]["traceId"] == "trace-1"
    assert prepared.events[5]["runtimeContextEvent"]["traceId"] == "trace-1"
    assert prepared.enriched_messages[0]["content"] == "web"
