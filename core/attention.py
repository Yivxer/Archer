"""Part 8 attention-focus boundary for future memory reranking."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}")
_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "你", "我", "我们", "这个", "那个",
    "继续", "一下", "可以", "需要", "然后", "现在",
}


@dataclass(frozen=True)
class AttentionFocus:
    terms: tuple[str, ...]
    sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"terms": list(self.terms), "sources": list(self.sources)}


def build_attention_focus(
    *,
    recent_messages: list[dict[str, Any]] | None = None,
    active_threads: list[dict[str, Any]] | None = None,
    soul_tensions: list[str] | None = None,
    max_terms: int = 8,
) -> AttentionFocus:
    """Build a compact focus from recent text, open threads, and Soul tensions."""
    weighted: dict[str, int] = {}
    sources: list[str] = []

    for message in recent_messages or []:
        content = str(message.get("content") or "")
        _add_terms(weighted, content, weight=1)
        if content:
            sources.append("recent_messages")

    for thread in active_threads or []:
        text = " ".join([str(thread.get("topic") or ""), str(thread.get("prompt") or "")])
        _add_terms(weighted, text, weight=3)
        if text.strip():
            sources.append("active_threads")

    for tension in soul_tensions or []:
        _add_terms(weighted, str(tension), weight=2)
        if str(tension).strip():
            sources.append("soul_tensions")

    terms = tuple(
        term for term, _score in sorted(weighted.items(), key=lambda item: (-item[1], item[0]))[: max(1, int(max_terms))]
    )
    return AttentionFocus(terms=terms, sources=tuple(dict.fromkeys(sources)))


def attention_boost(text: str, focus: AttentionFocus) -> float:
    """Return a small rerank boost for text near the current focus."""
    if not focus.terms:
        return 0.0
    haystack = str(text or "").lower()
    hits = sum(1 for term in focus.terms if term.lower() in haystack)
    return round(min(0.5, hits * 0.1), 3)


def _add_terms(weighted: dict[str, int], text: str, *, weight: int) -> None:
    for token in _TOKEN_RE.findall(text.lower()):
        if token in _STOPWORDS:
            continue
        weighted[token] = weighted.get(token, 0) + weight
