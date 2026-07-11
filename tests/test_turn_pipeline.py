from __future__ import annotations

from types import SimpleNamespace

from terminal.api.turn_pipeline import classify_turn, orchestrate_turn


def test_classify_turn_separates_current_user_message_from_history():
    calls = []

    def classifier(query, *, history, llm_fallback):
        calls.append((query, history, llm_fallback))
        return {"intent": "chat", "needs_memory": False, "needs_tools": False}

    result = classify_turn(
        [
            {"role": "system", "content": "thread context"},
            {"role": "user", "content": "earlier"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "continue"},
        ],
        classifier=classifier,
    )

    assert result.query == "continue"
    assert result.prior_history[-1] == {"role": "assistant", "content": "answer"}
    assert calls == [("continue", result.prior_history, False)]
    assert result.intent_info["intent"] == "chat"


def test_classify_turn_uses_latest_user_even_when_history_ends_with_assistant():
    result = classify_turn(
        [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ],
        classifier=lambda query, **_: {
            "intent": "chat",
            "query": query,
            "needs_memory": False,
            "needs_tools": False,
        },
    )

    assert result.query == "question"
    assert len(result.prior_history) == 2


def test_orchestrate_turn_builds_prompt_blocks_and_events(monkeypatch):
    orchestration = SimpleNamespace(memory_scope=("working",), matched_skills=("write",))
    task_plan = SimpleNamespace(task_title="Plan", steps=[])
    monkeypatch.setattr(
        "core.orchestrator.orchestrate_user_input",
        lambda query, *, history, soul_insight: orchestration,
    )
    monkeypatch.setattr("core.orchestrator.build_task_plan", lambda *_: task_plan)
    monkeypatch.setattr("core.orchestrator.format_task_plan_for_prompt", lambda _: "task block")
    monkeypatch.setattr("core.orchestrator.format_mode_constraints_for_prompt", lambda _: "mode block")
    monkeypatch.setattr("core.orchestrator.format_matched_skills_for_prompt", lambda _: "skills block")
    monkeypatch.setattr("core.orchestrator.orchestration_to_event_dict", lambda _: {"mode": "doing"})

    result = orchestrate_turn("continue", [{"role": "user", "content": "earlier"}], "insight")

    assert result.orchestration is orchestration
    assert result.memory_scope == ("working",)
    assert result.task_plan_block == "task block"
    assert result.mode_constraint_block == "mode block"
    assert result.matched_skills_block == "skills block"
    assert result.plan_event["title"] == "Plan"
    assert result.orchestration_event == {"mode": "doing"}


def test_orchestrate_turn_degrades_to_empty_plan(monkeypatch):
    monkeypatch.setattr(
        "core.orchestrator.orchestrate_user_input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    result = orchestrate_turn("hello", [], "")

    assert result.orchestration is None
    assert result.memory_scope is None
    assert result.task_plan_block == ""
    assert result.plan_event is None
