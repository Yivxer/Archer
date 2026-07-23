"""Runtime context projections for Desktop turn stages."""
from __future__ import annotations

from uuid import uuid4


def build_route_runtime_context(
    *, query: str, intent_info: dict, orchestration,
    file_refs: list[dict] | None = None, trace_id: str = "", turn_decision=None,
) -> dict:
    matched_skills = list(getattr(orchestration, "matched_skills", []) or [])
    handling = str(getattr(turn_decision, "handling", "") or "converse")
    actions = list(getattr(turn_decision, "action_requests", ()) or ())
    wants_blog = any(getattr(action, "capability", "") == "hugo_blog" for action in actions)
    user_intent = str(
        getattr(orchestration, "sub_intent", "") or intent_info.get("intent", "chat")
    )
    return {
        "id": f"runtime-context-{uuid4().hex[:8]}", "traceId": trace_id,
        "task": "blog_publish" if wants_blog else user_intent, "phase": "route",
        "userIntent": user_intent,
        "lastResult": "", "expectedNext": "mediate_action" if wants_blog else "model_response",
        "matchedSkills": matched_skills,
        "decisionTrace": {
            "handling": handling, "candidateCapabilities": matched_skills,
            "requestedActions": [f"{a.capability}:{a.action}" for a in actions],
            "confidence": getattr(turn_decision, "confidence", 0.0),
            "summary": str(getattr(turn_decision, "summary", ""))[:300],
        },
    }
