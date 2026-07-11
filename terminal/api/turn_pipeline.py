"""Independently testable stages for the Desktop chat turn pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from uuid import uuid4


IntentClassifier = Callable[..., dict]


@dataclass(frozen=True, slots=True)
class ClassifiedTurn:
    query: str
    prior_history: list[dict]
    intent_info: dict


@dataclass(frozen=True, slots=True)
class OrchestratedTurn:
    orchestration: object | None
    memory_scope: object | None
    task_plan_block: str
    mode_constraint_block: str
    matched_skills_block: str
    plan_event: dict | None
    orchestration_event: dict | None


def _latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", "")).strip()
    return ""


def classify_turn(
    messages: list[dict],
    *,
    classifier: IntentClassifier | None = None,
) -> ClassifiedTurn:
    if classifier is None:
        from core.context import classify_query_intent

        classifier = classify_query_intent
    query = _latest_user_text(messages)
    prior_history = (
        messages[:-1]
        if messages and messages[-1].get("role") == "user"
        else messages
    )
    intent_info = classifier(query, history=prior_history, llm_fallback=False)
    return ClassifiedTurn(
        query=query,
        prior_history=prior_history,
        intent_info=intent_info,
    )


def _plan_event(plan, query: str) -> dict | None:
    if plan is None:
        return None
    return {
        "id": f"plan-{uuid4().hex[:8]}",
        "title": plan.task_title,
        "status": "proposed",
        "detail": "先按计划处理；涉及写入、保存或发布的步骤需要用户确认。",
        "prompt": query.strip(),
        "steps": [
            {
                "id": step.id,
                "action": step.action,
                "tool": step.tool,
                "requiresApproval": step.requires_approval,
            }
            for step in plan.steps
        ],
    }


def orchestrate_turn(
    query: str,
    prior_history: list[dict],
    soul_insight: str,
) -> OrchestratedTurn:
    from core.orchestrator import (
        build_task_plan,
        format_matched_skills_for_prompt,
        format_mode_constraints_for_prompt,
        format_task_plan_for_prompt,
        orchestrate_user_input,
        orchestration_to_event_dict,
    )

    try:
        try:
            orchestration = orchestrate_user_input(
                query,
                history=prior_history,
                soul_insight=soul_insight,
            )
        except TypeError as exc:
            if "soul_insight" not in str(exc):
                raise
            orchestration = orchestrate_user_input(query, history=prior_history)
        task_plan = build_task_plan(query, orchestration)
        return OrchestratedTurn(
            orchestration=orchestration,
            memory_scope=orchestration.memory_scope,
            task_plan_block=format_task_plan_for_prompt(task_plan),
            mode_constraint_block=format_mode_constraints_for_prompt(orchestration),
            matched_skills_block=format_matched_skills_for_prompt(
                orchestration.matched_skills
            ),
            plan_event=_plan_event(task_plan, query),
            orchestration_event=orchestration_to_event_dict(orchestration),
        )
    except Exception:
        return OrchestratedTurn(None, None, "", "", "", None, None)


def plain_chat_message(message) -> dict:
    if isinstance(message, dict):
        return message
    model_dump = getattr(message, "model_dump", None)
    if callable(model_dump):
        data = model_dump(exclude_none=True)
        if isinstance(data, dict):
            return data
    legacy_dict = getattr(message, "dict", None)
    if callable(legacy_dict):
        data = legacy_dict(exclude_none=True)
        if isinstance(data, dict):
            return data
    return {
        "role": str(getattr(message, "role", "assistant") or "assistant"),
        "content": getattr(message, "content", "") or "",
    }


def trim_model_messages(
    messages: list[dict], *, keep_recent: int = 20, threshold: int = 36
) -> list[dict]:
    if len(messages) <= threshold or keep_recent <= 0:
        return messages
    system_prefix: list[dict] = []
    rest = list(messages)
    while rest and rest[0].get("role") == "system":
        system_prefix.append(rest.pop(0))
    if len(rest) <= keep_recent:
        return [*system_prefix, *rest]
    omitted = len(rest) - keep_recent
    summary = {
        "role": "system",
        "content": f"[长上下文保护] 旧对话已省略 {omitted} 条，仅保留最近 {keep_recent} 条消息。",
    }
    return [*system_prefix, summary, *rest[-keep_recent:]]


def assemble_model_messages(
    enriched_messages: list[dict],
    *,
    core_persona: str,
    tool_notes: list[str] | None = None,
    obsidian_hint: str = "",
    simple: bool = False,
) -> list[dict]:
    clean_messages: list[dict] = []
    for raw_message in enriched_messages:
        message = plain_chat_message(raw_message)
        role = message.get("role")
        if role == "tool":
            continue
        if role == "assistant" and message.get("tool_calls"):
            content = message.get("content")
            if content:
                clean_messages.append({"role": "assistant", "content": content})
            continue
        clean_messages.append(message)

    notes = tool_notes or []
    if simple:
        instruction = "\n\n请直接自然回答，不要输出 XML、function_call、tool_call。"
    elif not notes:
        instruction = "\n\n工具事件由本地客户端处理；请直接自然回答，不要输出 XML、function_call、tool_call。"
    else:
        tool_context = "\n\n本轮本地客户端已经处理以下工具事件：\n- " + "\n- ".join(notes)
        instruction = (
            "本轮已触发的工具能力："
            + tool_context
            + "\n\n你可以自然地使用这些能力完成用户的要求——"
            + "在你的回复中用自然语言描述你想做什么，客户端会自动处理执行细节。"
            + "不要输出 XML 伪标签或 function call 语法。"
        )
    return trim_model_messages(
        [
            {
                "role": "system",
                "content": (
                    "你正在 Archer Desktop 中回复用户。\n\n"
                    + core_persona
                    + instruction
                    + obsidian_hint
                ),
            },
            *clean_messages,
        ]
    )
