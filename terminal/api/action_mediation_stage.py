"""Turn Pipeline stage that projects Action Mediator results into runtime events."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from core.action_mediator import ActionDisposition, mediate_turn


@dataclass(frozen=True)
class ActionMediationStageResult:
    enriched_messages: list[dict]
    tool_events: list[dict]
    runtime_event: dict


def _authorized_result(run_hugo: Callable, action: str) -> tuple[list[dict], str, list[str], str]:
    workflow_events = list(run_hugo(action))
    summary = "".join(
        str(event.get("text", "")) for event in workflow_events if event.get("type") == "token"
    )
    events = [event for event in workflow_events if event.get("type") not in {"token", "ready", "done"}]
    results = [event.get("toolEvent", {}) for event in events if event.get("toolEvent", {}).get("name") == "hugo_blog"]
    outcome = "AUTO_EXECUTE"
    if results and not any(item.get("status") == "complete" for item in results):
        outcome = "EXECUTION_FAILED"
    return events, outcome, ["hugo_blog"] if results else [], summary


def _confirmation_events(action, query: str, mediation, *, delete, make_request, set_draft, event_from_request):
    if action.action in {"delete", "unpublish", "delete_and_deploy", "withdraw"}:
        direct = delete(query)
        if direct:
            return direct[0]
    args = dict(action.parameters)
    args.setdefault("action", action.action)
    if action.target:
        args.setdefault("sourcePath", action.target)
    event_id = f"hugo-mediated-{uuid4().hex[:8]}"
    request = make_request(
        "hugo_blog", args, event_id=event_id, display_name="hugo_blog",
        extra={"authorizationFingerprint": mediation.fingerprint}, force_approval=True,
    )
    if not request.get("blocked"):
        set_draft(event_id, request)
    return [event_from_request(request, summary="确认枫弋札记操作", detail_prefix=mediation.reason)]


def run_action_mediation(
    decision, query: str, selected_tools: dict, enriched_messages: list[dict], trace_id: str,
    *, run_hugo: Callable, delete: Callable, make_request: Callable,
    set_draft: Callable, event_from_request: Callable,
) -> ActionMediationStageResult:
    mediation = mediate_turn(decision, query, candidate_capabilities=set(selected_tools))
    events: list[dict] = []
    calls: list[str] = []
    outcome = mediation.disposition.value
    if mediation.disposition == ActionDisposition.AUTO_EXECUTE and mediation.action:
        events, outcome, calls, summary = _authorized_result(run_hugo, mediation.action.action)
        enriched_messages = [{"role": "system", "content": f"[已授权 Hugo 动作结果]\n{summary or '请依据工具事件如实说明。'}"}, *enriched_messages]
    elif mediation.disposition == ActionDisposition.REQUEST_CONFIRMATION and mediation.action:
        events = _confirmation_events(
            mediation.action, query, mediation, delete=delete, make_request=make_request,
            set_draft=set_draft, event_from_request=event_from_request,
        )
        enriched_messages = [{"role": "system", "content": "[行动仲裁] 已生成确认卡；不要声称已经执行。"}, *enriched_messages]
    runtime = {
        "id": f"runtime-mediation-{uuid4().hex[:8]}", "traceId": trace_id,
        "task": "blog_publish" if mediation.action else "conversation", "phase": "action_mediation",
        "userIntent": getattr(decision, "handling", "converse"), "lastResult": outcome,
        "expectedNext": "model_response", "matchedSkills": list(selected_tools),
        "decisionTrace": {
            "handling": getattr(decision, "handling", "converse"),
            "authorizationSource": mediation.authorization_source, "actionResult": outcome,
            "actualCalls": calls, "reason": mediation.reason, "fingerprint": mediation.fingerprint,
        },
    }
    return ActionMediationStageResult(enriched_messages, events, runtime)
