"""Part 8.4 transparent creative-candidate scoring."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreativeCandidate:
    kind: str
    message: str
    novelty: float
    relevance: float
    safety: float


@dataclass(frozen=True)
class CreativeScore:
    total: float
    trace: dict[str, float]


def score_creative_candidate(candidate: CreativeCandidate) -> CreativeScore:
    """Score a candidate with fixed, inspectable weights."""
    trace = {
        "novelty": _clamp(candidate.novelty),
        "relevance": _clamp(candidate.relevance),
        "safety": _clamp(candidate.safety),
    }
    total = round(trace["novelty"] * 0.4 + trace["relevance"] * 0.4 + trace["safety"] * 0.2, 3)
    return CreativeScore(total=total, trace=trace)


def _clamp(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return max(0.0, min(1.0, number))
