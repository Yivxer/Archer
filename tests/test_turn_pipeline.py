from __future__ import annotations

from types import SimpleNamespace

from core.orchestrator import build_task_plan
from terminal.api.turn_pipeline import (
    assemble_model_messages,
    classify_turn,
    orchestrate_turn,
    select_turn_tools,
)


def test_explicit_vault_reflection_builds_confirmable_job_handoff():
    plan = build_task_plan(
        "请结晶 `/Users/example/Vault/一篇笔记.md`",
        SimpleNamespace(needs_job=False, side_effect_level="none"),
    )

    assert plan is not None
    assert plan.steps[0].tool == "vault_reflection"
    assert plan.steps[0].requires_approval is True
    assert plan.execution == {
        "jobKind": "vault_reflection",
        "vaultArgs": {
            "notePath": "/Users/example/Vault/一篇笔记.md",
            "force": False,
        },
        "timeoutSeconds": 600,
    }


def test_vault_reflection_requires_explicit_quoted_markdown_path():
    plan = build_task_plan(
        "帮我结晶最近的笔记",
        SimpleNamespace(needs_job=False, side_effect_level="none"),
    )

    assert plan is None


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


def test_assemble_model_messages_removes_tool_residue_and_keeps_text():
    messages = assemble_model_messages(
        [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "useful", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "raw result"},
        ],
        core_persona="persona",
        tool_notes=["read file"],
        obsidian_hint="\nobsidian hint",
    )

    assert messages[0]["role"] == "system"
    assert "persona" in messages[0]["content"]
    assert "read file" in messages[0]["content"]
    assert messages[0]["content"].endswith("obsidian hint")
    assert messages[1:] == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "useful"},
    ]


def test_assemble_model_messages_uses_simple_path_instruction():
    messages = assemble_model_messages(
        [{"role": "user", "content": "hello"}],
        core_persona="persona",
        simple=True,
    )

    assert "请直接自然回答" in messages[0]["content"]
    assert "本轮已触发的工具能力" not in messages[0]["content"]


def test_select_turn_tools_uses_one_server_side_plan():
    calls = []
    plan = SimpleNamespace(
        filtered_skills={"obsidian_write": object()},
        tool_plan=SimpleNamespace(obsidian_write=True),
    )

    def planner(query, scoped_skills, *, intent, needs_tools, llm_fallback):
        calls.append((query, scoped_skills, intent, needs_tools, llm_fallback))
        return plan

    result = select_turn_tools(
        "save this",
        {"obsidian_write": object()},
        intent="task",
        needs_tools=True,
        planner=planner,
    )

    assert calls == [
        ("save this", result.scoped_skills, "task", True, True),
    ]
    assert result.turn_plan is plan
    assert result.selected_tools is plan.filtered_skills
    assert result.tool_plan is plan.tool_plan
