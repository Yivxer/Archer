"""Semantic turn decision contract for material-aware Desktop turns."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

Handling = Literal["converse", "analyze", "inspect", "propose_action", "execute_action"]


@dataclass(frozen=True)
class ContextRequest:
    kind: Literal["local_markdown"]
    target: str = ""
    read_only: bool = True


@dataclass(frozen=True)
class ActionRequest:
    capability: str
    action: str
    target: str = ""
    parameters: dict = field(default_factory=dict)
    evidence: str = ""


@dataclass(frozen=True)
class TurnDecision:
    user_goal: str
    handling: Handling
    context_requests: tuple[ContextRequest, ...] = ()
    action_requests: tuple[ActionRequest, ...] = ()
    confidence: float = 0.0
    summary: str = ""
    source: str = "model"
    valid: bool = True


_HANDLINGS = {"converse", "analyze", "inspect", "propose_action", "execute_action"}


def _json_object(text: str) -> dict | None:
    try:
        value = json.loads(text.strip())
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group())
        except Exception:
            return None
    return value if isinstance(value, dict) else None


def _parse_decision(raw: str) -> TurnDecision | None:
    data = _json_object(raw)
    if not data or data.get("handling") not in _HANDLINGS:
        return None
    contexts = tuple(
        ContextRequest(kind="local_markdown", target=str(item.get("target", "")))
        for item in data.get("context_requests", []) if isinstance(item, dict)
        and item.get("kind") == "local_markdown"
    )
    actions = tuple(
        ActionRequest(
            capability=str(item.get("capability", "")), action=str(item.get("action", "")),
            target=str(item.get("target", "")), parameters=item.get("parameters", {}) or {},
            evidence=str(item.get("evidence", "")),
        ) for item in data.get("action_requests", []) if isinstance(item, dict)
    )
    return TurnDecision(
        user_goal=str(data.get("user_goal", ""))[:300], handling=data["handling"],
        context_requests=contexts, action_requests=actions,
        confidence=max(0.0, min(1.0, float(data.get("confidence", 0.0)))),
        summary=str(data.get("summary", ""))[:300],
    )


def safe_fallback_decision(query: str, *, has_markdown: bool) -> TurnDecision:
    return TurnDecision(
        user_goal=query[:300], handling="analyze" if has_markdown else "converse",
        confidence=0.0, summary="语义判断失败，安全降级为普通对话。",
        source="fallback", valid=False,
    )


def default_conversation_decision(query: str) -> TurnDecision:
    return TurnDecision(
        user_goal=query[:300], handling="converse", confidence=1.0,
        summary="当前轮不需要语义行动判断。", source="pipeline",
    )


def decide_turn(
    query: str, *, file_context: str = "", candidate_capabilities: list[str] | None = None,
) -> TurnDecision:
    """Ask the active main model for a compact decision; failure is side-effect free."""
    has_markdown = bool(file_context)
    prompt = (
        "你是 Archer 的回合决策器。只输出一个 JSON 对象，不输出思维链。"
        "handling 只能是 converse/analyze/inspect/propose_action/execute_action。"
        "action_requests 只在用户当前轮明确要求动作时填写；建议、反问、历史叙述、否定均不得执行。"
        "每个动作必须包含 capability、action、target、parameters、evidence；evidence 必须逐字引用当前用户原文。"
        "本地材料默认只读。字段：user_goal,handling,context_requests,action_requests,confidence,summary。\n"
        f"候选能力：{candidate_capabilities or []}\n用户原文：{query}\n"
        f"已读取材料：{file_context[:12000]}"
    )
    try:
        from core.llm import stream_chat
        raw = "".join(stream_chat([{"role": "system", "content": prompt}], track_usage=False))
        return _parse_decision(raw) or safe_fallback_decision(query, has_markdown=has_markdown)
    except Exception:
        return safe_fallback_decision(query, has_markdown=has_markdown)
