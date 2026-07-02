"""Part 8.3 stable voice for shadow initiative candidates.

This layer chooses a companion or witness tone independent from chat work mode.
It returns text only and never delivers it.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.opportunity import OpportunityCandidate

VALID_STANCES = {"companion", "witness"}


@dataclass(frozen=True)
class ProactiveVoiceDraft:
    stance: str
    message: str
    source_kind: str


def compose_proactive_voice(
    candidate: OpportunityCandidate,
    *,
    stance: str = "companion",
    current_mode: str = "",
) -> ProactiveVoiceDraft:
    """Phrase a candidate without changing tone for the current work mode."""
    del current_mode
    selected_stance = stance if stance in VALID_STANCES else "companion"
    message = _message_for(candidate, stance=selected_stance)
    return ProactiveVoiceDraft(
        stance=selected_stance,
        message=message,
        source_kind=candidate.kind,
    )


def _message_for(candidate: OpportunityCandidate, *, stance: str) -> str:
    if candidate.kind == "stale_thread":
        topic = str(candidate.trace.get("topic") or "这个话题").strip()
        if stance == "witness":
            return f"我记得你曾把「{topic}」留在这里。它还在，不需要现在回答。"
        return f"之前的「{topic}」还停在这里。你不需要现在回答，只是先留给你。"
    if candidate.kind == "presence_return":
        if stance == "witness":
            return "你回来了。这里有一条线索仍被记着，不急着处理。"
        return "你回来了。先不急着做什么；这里有一条线索仍在。"
    return "有一条线索值得先留在这里，不急着处理。"
