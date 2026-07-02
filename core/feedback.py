"""Part 8.3 feedback analysis for shadow initiatives.

Feedback is interpreted as a pacing recommendation for later arbitration. This
module neither records feedback nor changes any delivery policy by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

POSITIVE_FEEDBACK = {"acknowledged", "helpful"}
TOO_FREQUENT_FEEDBACK = "too_frequent"


@dataclass(frozen=True)
class InitiativeFeedbackSummary:
    feedback_count: int
    recognition_rate: float | None
    too_frequent_count: int
    recommendation: str
    pacing_multiplier: float


def analyze_initiative_feedback(logs: list[dict[str, Any]]) -> InitiativeFeedbackSummary:
    """Summarize explicit user feedback from initiative shadow logs."""
    feedbacks = [
        str(log.get("feedback") or "").strip().lower()
        for log in logs
        if isinstance(log, dict)
    ]
    known = [item for item in feedbacks if item in POSITIVE_FEEDBACK | {TOO_FREQUENT_FEEDBACK}]
    too_frequent_count = sum(item == TOO_FREQUENT_FEEDBACK for item in known)
    positive_count = sum(item in POSITIVE_FEEDBACK for item in known)
    recognition_rate = round(positive_count / len(known), 3) if known else None

    if too_frequent_count:
        recommendation, pacing_multiplier = "slow_down", 0.25
    elif len(known) >= 3 and recognition_rate is not None and recognition_rate >= 0.6:
        recommendation, pacing_multiplier = "steady", 1.0
    else:
        recommendation, pacing_multiplier = "observe", 1.0
    return InitiativeFeedbackSummary(
        feedback_count=len(known),
        recognition_rate=recognition_rate,
        too_frequent_count=too_frequent_count,
        recommendation=recommendation,
        pacing_multiplier=pacing_multiplier,
    )
