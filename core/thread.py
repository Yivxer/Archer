"""
thread.py — 跨轮话题线程状态（想法 8）

纯规则、零 token：从对话历史推断「当前在聊什么」，注入 prompt 让多轮更连贯。
"""
from __future__ import annotations

from core.intent import _classify_single, _is_followup, _needs_retrieval_context, _recent_user_texts

# 短追问：语义上依赖上文，但可能被意图分类器标成 reflection 等非 chat
_SHORT_CONTINUATIONS = frozenset([
    "为什么", "为什么？", "真的吗", "然后呢", "还有呢", "继续", "嗯", "嗯嗯", "好", "好的",
])


def _is_thread_continuation(text: str, history: list[dict] | None) -> bool:
    base = _classify_single(text)
    if _is_followup(text, base, history):
        return True
    t = text.strip()
    if history and t in _SHORT_CONTINUATIONS:
        return True
    if history and _needs_retrieval_context(t, base, history):
        return True
    return False


def _summarize_topic(text: str, max_len: int = 36) -> str:
    t = (text or "").strip()
    for prefix in ("我想", "帮我", "请问", "能不能", "可以吗", "麻烦"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
    if len(t) > max_len:
        return t[:max_len] + "…"
    return t


def resolve_topic_thread(user_text: str, history: list[dict] | None = None) -> dict | None:
    """推断当前对话线程。

    返回 {"topic": str, "turns": int} 或 None。
    - 跟随式输入：沿用锚点话题，turns 为锚点以来的轮数（含当轮）。
    - 新实质输入：以当轮内容为新话题，turns=1。
    """
    text = (user_text or "").strip()
    if not text:
        return None

    if history and _is_thread_continuation(text, history):
        anchor = None
        for prev in _recent_user_texts(history):
            if _is_thread_continuation(prev, history):
                continue
            anchor = prev
            break
        if anchor:
            turns = 1
            for prev in _recent_user_texts(history):
                turns += 1
                if prev == anchor:
                    break
            return {"topic": _summarize_topic(anchor), "turns": turns}

    if len(text) >= 4:
        return {"topic": _summarize_topic(text), "turns": 1}
    return None
