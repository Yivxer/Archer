"""Part 8.4 gentle assumption challenges."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssumptionChallenge:
    assumption: str
    kind: str
    question: str


def challenge_assumption(text: str) -> AssumptionChallenge | None:
    """Return one non-judgmental question for a clear absolute assumption."""
    assumption = " ".join(str(text or "").split())
    if not assumption:
        return None
    if any(marker in assumption for marker in ("只要", "一定", "必然", "绝对")):
        return AssumptionChallenge(
            assumption=assumption,
            kind="absolute_claim",
            question="如果不成立，最早会出现什么信号？",
        )
    if any(marker in assumption for marker in ("必须", "只能", "不得不")):
        return AssumptionChallenge(
            assumption=assumption,
            kind="must_statement",
            question="这个要求有没有例外，或一个成本更低的替代做法？",
        )
    return None
