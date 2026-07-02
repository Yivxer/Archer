"""Part 8.4 alternative-perspective candidates for future chat use."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DissentCandidate:
    kind: str
    source_text: str
    message: str


def propose_dissent(text: str) -> DissentCandidate | None:
    """Offer one parallel perspective for a clear single-path assumption."""
    source = " ".join(str(text or "").split())
    if not source:
        return None
    if any(marker in source for marker in ("只能", "唯一", "必须先")):
        return DissentCandidate(
            kind="single_path",
            source_text=source,
            message="另一种看法：也许不必先完成全部路径，先验证最小价值同样能带来信息。",
        )
    if any(marker in source for marker in ("只要", "一定", "必然")):
        return DissentCandidate(
            kind="absolute_outcome",
            source_text=source,
            message="另一种看法：结果未必只由这一项决定，还有哪些条件同样需要成立？",
        )
    return None
