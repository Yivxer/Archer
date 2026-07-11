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
