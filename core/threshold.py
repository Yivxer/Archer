"""Part 8.3 initiative threshold scoring.

This module decides whether an initiative candidate is worth recording or
considering. It does not deliver messages.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.initiative_shadow import normalize_presence_state

DEFAULT_THRESHOLD = 0.7
MOMENT_WEIGHTS = {
    "deep_conversation": 0.15,
    "open": 0.05,
    "work": -0.1,
    "rest": -1.0,
}


@dataclass(frozen=True)
class InitiativeThresholdInput:
    now: datetime
    presence_state: str
    moment_kind: str
    opportunity_score: float
    relationship_score: float
    creative_score: float


@dataclass(frozen=True)
class InitiativeThresholdDecision:
    allowed: bool
    reason: str
    score: float
    trace: dict[str, Any]


def evaluate_threshold(
    signal: InitiativeThresholdInput,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> InitiativeThresholdDecision:
    presence = normalize_presence_state(signal.presence_state)
    trace = {
        "presenceState": presence,
        "momentKind": signal.moment_kind,
        "opportunityScore": _clamp(signal.opportunity_score),
        "relationshipScore": _clamp(signal.relationship_score),
        "creativeScore": _clamp(signal.creative_score),
        "threshold": threshold,
    }
    if presence == "muted":
        return InitiativeThresholdDecision(False, "presence_muted", 0.0, trace)
    if signal.moment_kind == "rest":
        return InitiativeThresholdDecision(False, "quiet_window", 0.0, trace)

    score = _combined_score(signal)
    trace["combinedScore"] = score
    if score >= threshold:
        return InitiativeThresholdDecision(True, "threshold_met", score, trace)
    return InitiativeThresholdDecision(False, "below_threshold", score, trace)


def _combined_score(signal: InitiativeThresholdInput) -> float:
    score = (
        _clamp(signal.opportunity_score) * 0.45
        + _clamp(signal.relationship_score) * 0.3
        + _clamp(signal.creative_score) * 0.2
        + MOMENT_WEIGHTS.get(signal.moment_kind, 0.0)
    )
    return round(_clamp(score), 3)


def _clamp(value: float) -> float:
    try:
        number = float(value)
    except Exception:
        number = 0.0
    return max(0.0, min(1.0, number))
