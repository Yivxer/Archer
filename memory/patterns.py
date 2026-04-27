"""
patterns.py — 跨会话行为模式归纳

从记忆库中提炼重复出现的主题/模式，建立记忆↔主题图结构。
"""
import json
from core.llm import stream_chat
from memory.store import (
    get_memories_for_detection,
    save_theme,
    list_themes,
    link_memory_to_theme,
    get_theme_memories,
)

_MAX_THEME_NAME_CHARS = 12   # 主题名称最大字符数
_MIN_EVIDENCE_LINKS    = 2   # 每个主题至少需要的证据条数
_MIN_SESSION_SPAN      = 2   # 证据必须跨越的最少不同 session_id 数（v1.2）
_MIN_DATE_SPAN         = 2   # 证据必须跨越的最少不同日期数（fallback）
_SAME_DAY_CONF_CAP     = 0.65  # 两个 session 在同一天时置信度上限

_DETECT_PROMPT = """\
你是行为模式分析助手。分析以下记忆条目，识别其中反复出现的主题和行为模式。

要求：
- 只归纳真正跨越多条记忆、反复出现的模式，不要强行分类单一记忆
- 每个主题用 2-8 个字概括，配一句话描述
- category 从以下选择：behavior（行为习惯）/ interest（持续兴趣）/ struggle（持续挑战）/ growth（成长轨迹）
- linked_memory_ids 列出最能体现该主题的记忆 ID（最多 5 个），并给每个 strength（0.0-1.0）

以 JSON 返回：
{
  "themes": [
    {
      "name": "主题名",
      "description": "一句话描述",
      "category": "behavior",
      "links": [
        {"memory_id": 1, "strength": 0.9},
        {"memory_id": 3, "strength": 0.7}
      ]
    }
  ]
}

记忆不足时返回 {"themes": []}。最多返回 5 个主题。\
"""


def detect_and_save(limit: int = 50) -> list[dict]:
    """
    从近期高重要度记忆中检测主题，保存到 themes/memory_links 表。
    返回新识别的主题列表。
    """
    memories = get_memories_for_detection(limit)
    if len(memories) < 3:
        return []

    mem_text = "\n".join(
        f"[ID:{m['id']}] ({m['type']}, ★{m['importance']}) {m['content']}"
        for m in memories
    )

    messages = [
        {"role": "system", "content": _DETECT_PROMPT},
        {"role": "user", "content": f"记忆列表：\n\n{mem_text}"},
    ]

    raw = ""
    for chunk in stream_chat(messages, track_usage=False):
        raw += chunk

    try:
        s = raw.find("{")
        e = raw.rfind("}") + 1
        if s < 0 or e <= s:
            return []
        data = json.loads(raw[s:e])
        raw_themes = data.get("themes", [])
    except Exception:
        return []

    # 构建 memory_id → (date, session_id) 的快速查找表
    mem_meta_lookup: dict[int, tuple[str, str]] = {
        m["id"]: (
            (m.get("created_at") or "")[:10],
            m.get("session_id") or "",
        )
        for m in memories
        if m.get("created_at")
    }

    saved = []
    for t in raw_themes[:5]:
        name = str(t.get("name", "")).strip()
        if not name:
            continue

        # 约束 1：名称不超过 _MAX_THEME_NAME_CHARS 个字符
        if len(name) > _MAX_THEME_NAME_CHARS:
            continue

        links = t.get("links", [])
        if not isinstance(links, list):
            links = []

        # 约束 2：至少需要 _MIN_EVIDENCE_LINKS 条证据
        valid_links = [lk for lk in links if isinstance(lk, dict) and lk.get("memory_id") is not None]
        if len(valid_links) < _MIN_EVIDENCE_LINKS:
            continue

        # 约束 3（v1.2）：证据必须跨越至少 _MIN_SESSION_SPAN 个不同 session_id
        evidence_sessions = {
            mem_meta_lookup.get(int(lk["memory_id"]), ("", ""))[1]
            for lk in valid_links
        }
        evidence_sessions.discard("")
        evidence_dates = {
            mem_meta_lookup.get(int(lk["memory_id"]), ("", ""))[0]
            for lk in valid_links
        }
        evidence_dates.discard("")

        if len(evidence_sessions) >= _MIN_SESSION_SPAN:
            # 有跨 session 证据：使用 session 门控
            # 若两个 session 在同一天，置信度上限为 _SAME_DAY_CONF_CAP
            cross_day = len(evidence_dates) >= _MIN_DATE_SPAN
        else:
            # 无 session_id 数据（旧记忆兼容）：降级到跨日期门控
            if len(evidence_dates) < _MIN_DATE_SPAN:
                continue
            cross_day = True

        description = str(t.get("description", "")).strip()
        category = str(t.get("category", "behavior")).strip()
        if category not in ("behavior", "interest", "struggle", "growth"):
            category = "behavior"

        tid = save_theme(name, description, category)

        for link in valid_links:
            mid = link.get("memory_id")
            raw_strength = float(link.get("strength", 0.5))
            # 同 session 同日场景：限制 strength 上限
            if not cross_day:
                raw_strength = min(raw_strength, _SAME_DAY_CONF_CAP)
            try:
                link_memory_to_theme(int(mid), tid, raw_strength)
            except Exception:
                pass

        saved.append({"id": tid, "name": name, "description": description, "category": category})

    return saved


def themes_summary(limit: int = 10) -> list[dict]:
    """返回主题列表，供显示用。"""
    return list_themes(limit)


def theme_detail(theme_id: int) -> tuple[dict | None, list[dict]]:
    """返回 (theme_meta, linked_memories)。"""
    themes = list_themes(100)
    meta = next((t for t in themes if t["id"] == theme_id), None)
    memories = get_theme_memories(theme_id)
    return meta, memories
