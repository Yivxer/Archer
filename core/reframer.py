"""Part 8.4 conservative, rule-based problem reframing."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reframe:
    angle: str
    prompt: str
    reason: str


def reframe_problem(text: str) -> Reframe | None:
    """Offer one alternative question only for clear, low-ambiguity patterns."""
    source = " ".join(str(text or "").split())
    if not source:
        return None
    if _contains_any(source, ("一次做完", "必须", "不然没有意义", "否则没有意义")):
        return Reframe(
            angle="scope",
            prompt="能否先定义一个最小闭环，再判断它是否值得继续扩展？",
            reason="all_or_nothing_scope",
        )
    if _contains_any(source, ("没时间", "没有时间", "时间不够")):
        return Reframe(
            angle="priority",
            prompt="这更像时间不足，还是当前优先级还没有被明确选择？",
            reason="time_shortage",
        )
    if _contains_any(source, ("怕做错", "害怕失败", "不敢开始", "怕失败")):
        return Reframe(
            angle="experiment",
            prompt="能否把下一步设计成一次可逆的小实验，而不是一次定输赢的决定？",
            reason="failure_avoidance",
        )
    return None


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)
