"""Part 8.4 shadow-only creative candidate ranking."""
from __future__ import annotations

from dataclasses import dataclass

from core.scorer import CreativeCandidate, CreativeScore, score_creative_candidate

MIN_CREATIVE_SCORE = 0.65
MIN_SAFETY_SCORE = 0.5


@dataclass(frozen=True)
class RankedCreativeCandidate:
    candidate: CreativeCandidate
    score: CreativeScore
    shadow: bool = True


def rank_creative_candidates(
    candidates: list[CreativeCandidate],
    *,
    limit: int = 3,
    min_score: float = MIN_CREATIVE_SCORE,
) -> list[RankedCreativeCandidate]:
    """Filter and rank candidates without delivering or persisting them."""
    ranked = [
        RankedCreativeCandidate(candidate=candidate, score=score_creative_candidate(candidate))
        for candidate in candidates
        if score_creative_candidate(candidate).trace["safety"] >= MIN_SAFETY_SCORE
        and score_creative_candidate(candidate).total >= min_score
    ]
    ranked.sort(key=lambda item: (-item.score.total, item.candidate.kind, item.candidate.message))
    return ranked[: max(1, min(int(limit), 10))]
