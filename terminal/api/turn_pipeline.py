"""Independently testable stages for the Desktop chat turn pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


IntentClassifier = Callable[..., dict]


@dataclass(frozen=True, slots=True)
class ClassifiedTurn:
    query: str
    prior_history: list[dict]
    intent_info: dict


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
