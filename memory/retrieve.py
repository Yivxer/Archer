from datetime import datetime, timedelta
from memory.a4 import select_context_memories, should_create_reflection_anchor
from memory.store import search, recent, high_importance, update_last_used, get_by_ids
from infrastructure.observability import trace_span

_LIGHT_INPUTS = {
    "你好", "hi", "hello", "在吗", "早", "早安", "晚安",
    "ok", "嗯", "好", "好的", "谢谢", "继续",
}

def _should_skip_memory(user_input: str) -> bool:
    text = user_input.strip().lower()
    if not text:
        return False
    return text in _LIGHT_INPUTS or len(text) <= 2


def _is_valid_memory(m: dict) -> bool:
    """过滤掉 reflection 类型和已过期的记忆。"""
    if m.get("type") == "reflection":
        return False
    valid_until = m.get("valid_until")
    if valid_until:
        now = datetime.now().isoformat(timespec="seconds")
        if valid_until < now:
            return False
    return True


def _infer_trigger(user_input: str, intent: str | None) -> str | None:
    if should_create_reflection_anchor(user_input):
        return "reflection_anchor"
    if intent == "emotional":
        return "emotion_pattern"
    return None


def _matches_tag_hints(tags: str | None, hints: list[str]) -> bool:
    blob = str(tags or "").lower()
    return any(str(hint or "").lower() in blob for hint in hints if str(hint or "").strip())


def for_context(user_input: str = "", limit: int = 5, intent: str | None = None,
                block_types: list[str] | None = None,
                tag_hints: list[str] | None = None) -> tuple[list, list]:
    """
    A4 记忆检索：
    - intent 由业务编排层传入；memory 层不反向执行业务意图分类。
    - 每轮最多注入 limit 条，默认 5；A4 链路可传 7。
    - core 与 related 合并后按 A4 策略排序，再拆回 core / related。
    - 检索后过滤 reflection 类型和已过期记忆，并更新 last_used_at。
    """
    with trace_span("memory.retrieve", limit=limit, intent=intent or "") as span:
        if _should_skip_memory(user_input):
            span["skipped"] = True
            return [], []

        trigger = _infer_trigger(user_input, intent)
        total_limit = max(1, limit)

        core_raw = [m for m in high_importance(min_importance=4, limit=2) if _is_valid_memory(m)]

        if user_input and len(user_input.strip()) >= 2:
            related_raw = _hybrid_search(user_input.strip(), limit=total_limit)
        else:
            related_raw = recent(total_limit)

        # 去重 + 过滤
        seen: set[int] = set()
        combined: list[dict] = []
        for m in core_raw + related_raw:
            mid = m["id"]
            if mid in seen or not _is_valid_memory(m):
                continue
            seen.add(mid)
            combined.append(m)

        selected = select_context_memories(
            combined,
            intent=intent,
            trigger=trigger,
            limit=total_limit,
        )
        if block_types:
            allowed = {bt for bt in block_types if bt}
            if allowed:
                selected = [m for m in selected if m.get("block_type") in allowed]
        if tag_hints:
            tagged = [m for m in selected if _matches_tag_hints(m.get("tags"), tag_hints)]
            if tagged:
                selected = tagged
        selected_ids = {m["id"] for m in selected}
        core_ids = {m["id"] for m in core_raw}
        core = [m for m in selected if m["id"] in core_ids]
        related = [m for m in selected if m["id"] not in core_ids]

        # 更新 last_used_at
        for m in core + related:
            update_last_used(m["id"])

        span["core_count"] = len(core)
        span["related_count"] = len(related)
        return core, related


def _recency_tier(created_at: str | None) -> int:
    """0=近3天 1=近7天 2=更早。用于在保留语义排序的同时小幅提升近期记忆。"""
    if not created_at:
        return 2
    try:
        age = datetime.now() - datetime.fromisoformat(created_at)
        if age <= timedelta(days=3):
            return 0
        if age <= timedelta(days=7):
            return 1
    except Exception:
        pass
    return 2


def _hybrid_search(query: str, limit: int) -> list[dict]:
    """
    混合检索：向量 KNN + FTS5，结果合并去重。

    策略：
    1. 尝试向量检索（sqlite-vec + embedder），取 2*limit 条
    2. FTS5 检索，取 limit 条
    3. 向量命中在前（按距离排序），FTS-only 命中追加在后
    4. embedder/sqlite-vec 不可用时静默降级到纯 FTS5
    """
    fts_mems = search(query, limit=limit)

    try:
        from memory.embedder import encode
        from memory.vector_store import search_similar

        q_vec = encode(query)
        vec_hits = search_similar(q_vec, limit=limit * 2)  # [(id, distance)]
        if not vec_hits:
            return fts_mems

        # 水合向量命中
        vec_ids = [h[0] for h in vec_hits]
        id_to_mem = get_by_ids(vec_ids)
        # 按 distance 顺序排列（最相似在前）
        vec_mems = [id_to_mem[i] for i in vec_ids if i in id_to_mem]

        # 合并去重：向量结果优先，FTS-only 追加
        seen: set[int] = set()
        combined: list[dict] = []
        for m in vec_mems:
            seen.add(m["id"])
            combined.append(m)
        for m in fts_mems:
            if m["id"] not in seen:
                combined.append(m)

        # recency boost：按 (tier, 原始位置) 稳定排序，近期记忆前移
        combined = [m for _, m in sorted(
            enumerate(combined),
            key=lambda t: (_recency_tier(t[1].get("created_at")), t[0])
        )]
        return combined[:limit]

    except Exception:
        return fts_mems


def _time_ago(created_at: str | None) -> str:
    if not created_at:
        return ""
    try:
        from datetime import datetime
        age = datetime.now() - datetime.fromisoformat(created_at)
        days = age.days
        if days == 0:
            return ""  # 今天的不标
        elif days == 1:
            return " (昨天)"
        elif days < 7:
            return f" ({days}天前)"
        elif days < 30:
            return f" ({days // 7}周前)"
        elif days < 180:
            return f" ({days // 30}月前)"
        else:
            return f" ({days // 30}月前)"
    except Exception:
        return ""


def format_for_prompt(core: list, related: list) -> str:
    parts = []

    if core or related:
        parts.append(
            "## 记忆使用规则\n"
            "- 记忆可能过期或与当前问题无关，只在明显相关时使用。\n"
            "- 不要主动展示记忆库内容，不要为了使用记忆而使用记忆。\n"
            "- 当前用户消息与记忆冲突时，以当前消息为准。"
        )

    if core:
        lines = ["## 核心记忆（必读）\n"]
        for m in core:
            stars = "★" * min(m.get("importance", 3), 5)
            mem_type = m.get("type", "insight")
            mem_id = m.get("id", "?")
            line = f"- [src=memory.db:{mem_type}:id={mem_id}] [{stars}] {m['content']}"
            if m.get("tags"):
                line += f"  #{m['tags'].replace(',', ' #')}"
            line += _time_ago(m.get("created_at"))
            lines.append(line)
        parts.append("\n".join(lines))

    if related:
        lines = ["## 相关记忆\n"]
        for m in related:
            stars = "★" * min(m.get("importance", 3), 5)
            mem_type = m.get("type", "insight")
            mem_id = m.get("id", "?")
            line = f"- [src=memory.db:{mem_type}:id={mem_id}] [{stars}] {m['content']}"
            if m.get("tags"):
                line += f"  #{m['tags'].replace(',', ' #')}"
            line += _time_ago(m.get("created_at"))
            lines.append(line)
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def filter_by_block_type(block_type: str, limit: int = 20, label: str | None = None) -> list[dict]:
    from memory.store import list_by_block_type
    return list_by_block_type(block_type, limit=limit, label=label)
