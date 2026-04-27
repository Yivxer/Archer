from datetime import datetime
from memory.store import search, recent, high_importance, update_last_used, get_by_ids

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


def for_context(user_input: str = "", limit: int = 5) -> tuple[list, list]:
    """
    双路记忆检索：
    - 第一路：importance >= 4 的核心记忆，始终注入（最多 3 条）
    - 第二路：与当前输入相关的记忆（FTS 搜索 → fallback 最近）
    检索后过滤 reflection 类型和已过期记忆，并更新 last_used_at。
    """
    if _should_skip_memory(user_input):
        return [], []

    core = [m for m in high_importance(min_importance=4, limit=2) if _is_valid_memory(m)]

    if user_input and len(user_input.strip()) >= 2:
        related_raw = _hybrid_search(user_input.strip(), limit=limit)
    else:
        related_raw = recent(limit)

    # 去重 + 过滤
    core_ids = {m["id"] for m in core}
    related = [m for m in related_raw if m["id"] not in core_ids and _is_valid_memory(m)]

    # 更新 last_used_at
    for m in core + related:
        update_last_used(m["id"])

    return core, related


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

        return combined[:limit]

    except Exception:
        return fts_mems


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
            line = f"- [{stars}] {m['content']}"
            if m.get("tags"):
                line += f"  #{m['tags'].replace(',', ' #')}"
            lines.append(line)
        parts.append("\n".join(lines))

    if related:
        lines = ["## 相关记忆\n"]
        for m in related:
            stars = "★" * min(m.get("importance", 3), 5)
            line = f"- [{stars}] {m['content']}"
            if m.get("tags"):
                line += f"  #{m['tags'].replace(',', ' #')}"
            lines.append(line)
        parts.append("\n".join(lines))

    return "\n\n".join(parts)
