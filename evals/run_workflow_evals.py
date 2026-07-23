"""Deterministic workflow evals for routing and side-effect policy."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CASES_PATH = ROOT / "evals" / "workflow_cases.json"
BASELINE_PATH = ROOT / "evals" / "workflow_baseline.json"


def _intent(case: dict) -> dict:
    from core.intent import classify_query_intent

    result = classify_query_intent(case["query"], history=case.get("history"), llm_fallback=False)
    return {key: result[key] for key in (
        "intent", "source", "needs_memory", "needs_project", "needs_soul", "needs_tools"
    )}


def _tool_selection(case: dict) -> dict:
    from core import skill_router
    from core.desktop_tool_router import plan_desktop_turn

    original = skill_router._LEARNED_ROUTES_PATH
    skill_router._LEARNED_ROUTES_PATH = ROOT / "evals" / ".disabled_learned_routes"
    try:
        skills = {name: object() for name in case["skills"]}
        turn = plan_desktop_turn(
            case["query"], skills,
            intent=case["intent"], needs_tools=case["needs_tools"], llm_fallback=False,
        )
    finally:
        skill_router._LEARNED_ROUTES_PATH = original
    return {
        "raw_selected": sorted(turn.raw_selected),
        "filtered_skills": sorted(turn.filtered_skills),
        "preflight_tools": sorted(tool.skill for tool in turn.tool_plan.tools),
        "obsidian_preview": turn.tool_plan.obsidian_preview,
        "obsidian_write": turn.tool_plan.obsidian_write,
    }


def _context(case: dict) -> dict:
    from core.context import build_desktop_core_prompt
    from terminal.api.context_assembly import assemble_memory_context

    calls: list[str] = []

    def event_factory(_id, _name, status, _risk, _summary, _detail, *args, **kwargs):
        return {"status": status}

    def retrieve(query: str, **_kwargs):
        calls.append(query)
        return ([object()], [object()]) if case["has_retrieval"] else ([], [])

    result = assemble_memory_context(
        [{"role": "user", "content": case["query"]}],
        query=case["query"], prior_history=case["history"], intent=case["intent"],
        needs_memory=case["needs_memory"], memory_mode=case["memory_mode"], retrieve_limit=5,
        expert={}, event_factory=event_factory, retrieve=retrieve,
        format_retrieval=lambda core, related: "fixture memory" if core or related else "",
        expert_tags=lambda _expert: [],
    )
    return {
        "core_prompt_sha256": hashlib.sha256(build_desktop_core_prompt({}).encode()).hexdigest(),
        "retrieval_called": bool(calls),
        "retrieval_query": calls[0] if calls else "",
        "message_roles": [message["role"] for message in result.messages],
        "system_messages": [message["content"] for message in result.messages if message["role"] == "system"],
        "event_statuses": [event["status"] for event in result.events],
    }


def _hugo_side_effect(case: dict) -> dict:
    from core.desktop_tool_router import classify_hugo_intent, wants_hugo_publish
    from core.orchestrator import orchestrate_user_input

    result = orchestrate_user_input(case["query"])
    return {
        "hugo_intent": classify_hugo_intent(case["query"]),
        "wants_publish_workflow": wants_hugo_publish(case["query"]),
        "side_effect_level": result.side_effect_level,
        "needs_job": result.needs_job,
        "needs_tools": result.needs_tools,
    }


def _action_mediation(case: dict) -> dict:
    from core.action_mediator import mediate_turn
    from core.turn_decision import ActionRequest, TurnDecision

    actions = tuple(ActionRequest(**item) for item in case.get("action_requests", []))
    decision = TurnDecision(
        user_goal=case.get("user_goal", ""), handling=case["handling"],
        action_requests=actions, confidence=case.get("confidence", 0.9),
    )
    result = mediate_turn(decision, case["query"])
    return {
        "disposition": result.disposition.value,
        "authorization_source": result.authorization_source,
        "reason": result.reason,
        "has_fingerprint": bool(result.fingerprint),
    }


EVALUATORS = {
    "intent": _intent,
    "tool_selection": _tool_selection,
    "context": _context,
    "hugo_side_effect": _hugo_side_effect,
    "action_mediation": _action_mediation,
}


def evaluate_cases(cases: list[dict]) -> dict[str, dict[str, Any]]:
    return {case["id"]: EVALUATORS[case["domain"]](case) for case in cases}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    actual = evaluate_cases(cases)
    rendered = json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.update_baseline:
        BASELINE_PATH.write_text(rendered, encoding="utf-8")
        print(f"updated {BASELINE_PATH.relative_to(ROOT)} ({len(actual)} cases)")
        return 0
    expected = BASELINE_PATH.read_text(encoding="utf-8")
    if rendered != expected:
        print("workflow eval baseline mismatch; inspect diff or run --update-baseline intentionally")
        return 1
    print(f"workflow evals passed: {len(actual)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
