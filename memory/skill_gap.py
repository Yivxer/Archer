"""
技能缺口追踪 + 路由学习（进化机制 Phase 1）。

记录三类信号：
- missing：AI 尝试调用但不存在的技能名
- failed：技能存在但执行失败
- success：技能成功执行（积累路由学习数据）

表结构：
  skill_events(id, skill_name, event_type, trigger_text, session_id, created_at)
"""
from datetime import datetime
import sqlite3


def _conn():
    import memory.store as _store
    return sqlite3.connect(_store.DB_PATH)


def init_skill_gap_table():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS skill_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name  TEXT NOT NULL,
                event_type  TEXT NOT NULL,   -- missing / failed / success
                trigger_text TEXT DEFAULT '',
                session_id  TEXT DEFAULT '',
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            )
        """)


def record(skill_name: str, event_type: str, trigger_text: str = "", session_id: str = ""):
    """记录一次技能事件。event_type: missing / failed / success"""
    with _conn() as c:
        c.execute(
            "INSERT INTO skill_events(skill_name, event_type, trigger_text, session_id) VALUES(?,?,?,?)",
            (skill_name, event_type, trigger_text[:200], session_id),
        )


def get_gaps(limit: int = 20) -> list[dict]:
    """返回最近的 missing + failed 事件，按出现频次降序。"""
    with _conn() as c:
        rows = c.execute("""
            SELECT skill_name, event_type, COUNT(*) as cnt, MAX(created_at) as last_seen
            FROM skill_events
            WHERE event_type IN ('missing', 'failed')
            GROUP BY skill_name, event_type
            ORDER BY cnt DESC, last_seen DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [{"skill": r[0], "type": r[1], "count": r[2], "last_seen": r[3]} for r in rows]


def get_route_hints(min_count: int = 3) -> list[dict]:
    """
    从 success 事件中提取路由学习信号：
    trigger_text 里哪些词经常触发哪个技能成功 → 建议加入路由规则。
    """
    with _conn() as c:
        rows = c.execute("""
            SELECT skill_name, trigger_text
            FROM skill_events
            WHERE event_type = 'success' AND trigger_text != ''
            ORDER BY created_at DESC
            LIMIT 200
        """).fetchall()

    from collections import defaultdict
    import re
    skill_words: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for skill_name, text in rows:
        words = re.findall(r'[一-鿿]{2,4}|[a-z]{3,}', text.lower())
        for w in set(words):
            skill_words[skill_name][w] += 1

    hints = []
    for skill, word_counts in skill_words.items():
        for word, cnt in word_counts.items():
            if cnt >= min_count:
                hints.append({"skill": skill, "keyword": word, "count": cnt})
    hints.sort(key=lambda x: -x["count"])
    return hints


def apply_hints(min_count: int = 3) -> int:
    """
    把 get_route_hints() 的结果合并写入 learned_routes.json。
    返回新写入的条目数。
    """
    from core.skill_router import save_learned, _LEARNED_ROUTES_PATH
    import json

    hints = get_route_hints(min_count)
    if not hints:
        return 0

    existing: list[dict] = []
    if _LEARNED_ROUTES_PATH.exists():
        try:
            existing = json.loads(_LEARNED_ROUTES_PATH.read_text())
        except Exception:
            pass

    existing_index: dict[str, set] = {}
    for e in existing:
        for s in e["skills"]:
            existing_index.setdefault(s, set()).update(e["keywords"])

    added = 0
    for hint in hints:
        skill, kw = hint["skill"], hint["keyword"]
        if kw not in existing_index.get(skill, set()):
            matched = next((e for e in existing if skill in e["skills"]), None)
            if matched:
                if kw not in matched["keywords"]:
                    matched["keywords"].append(kw)
            else:
                existing.append({"skills": [skill], "keywords": [kw]})
            added += 1

    save_learned(existing)
    return added


def summary() -> str:
    gaps = get_gaps(10)
    if not gaps:
        return "暂无技能缺口记录。"
    lines = ["技能缺口（最近）："]
    for g in gaps:
        lines.append(f"  [{g['type']}] {g['skill']}  出现 {g['count']} 次  最近：{g['last_seen'][:16]}")
    hints = get_route_hints()
    if hints:
        lines.append("\n路由学习建议（出现≥3次的关键词→技能）：")
        for h in hints[:8]:
            lines.append(f"  '{h['keyword']}' → {h['skill']}  ({h['count']} 次)")
    return "\n".join(lines)
