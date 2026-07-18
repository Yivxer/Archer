"""主题（themes）管理（从 memory/store.py 抽出）。

包含：save_theme / list_themes / link_memory_to_theme / get_theme_memories / get_memories_for_detection

依赖：DB_PATH / _now / _clamp_depth / _row_to_dict 通过 `import memory.store as _store` 动态查找。
"""

from __future__ import annotations

import sqlite3

import memory.store as _store


def _now() -> str:
    return _store._now()


def save_theme(name: str, description: str = "", category: str = "behavior") -> int:
    """保存或更新一个主题，重名时增加 occurrence_count。返回 theme ID。"""
    name = name.strip()
    conn = sqlite3.connect(_store.DB_PATH)
    existing = conn.execute(
        "SELECT id FROM themes WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE themes SET occurrence_count = occurrence_count + 1, "
            "last_seen_at = ?, description = CASE WHEN ? != '' THEN ? ELSE description END "
            "WHERE id = ?",
            (_now(), description, description, existing[0]),
        )
        conn.commit()
        tid = existing[0]
    else:
        cur = conn.execute(
            "INSERT INTO themes (name, description, category, occurrence_count, last_seen_at, created_at) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (name, description.strip(), category, _now(), _now()),
        )
        conn.commit()
        tid = cur.lastrowid
    conn.close()
    return tid


def list_themes(limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(_store.DB_PATH)
    rows = conn.execute(
        "SELECT id, name, description, category, occurrence_count, last_seen_at "
        "FROM themes ORDER BY occurrence_count DESC, last_seen_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "name": r[1], "description": r[2],
         "category": r[3], "occurrence_count": r[4], "last_seen_at": r[5]}
        for r in rows
    ]


def link_memory_to_theme(memory_id: int, theme_id: int, strength: float = 0.5):
    """关联记忆与主题，已存在则更新 strength。"""
    conn = sqlite3.connect(_store.DB_PATH)
    conn.execute(
        "INSERT INTO memory_links (memory_id, theme_id, strength, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(memory_id, theme_id) DO UPDATE SET strength = excluded.strength",
        (memory_id, theme_id, float(strength), _now()),
    )
    conn.commit()
    conn.close()


def get_theme_memories(theme_id: int, limit: int = 10) -> list[dict]:
    conn = sqlite3.connect(_store.DB_PATH)
    rows = conn.execute(
        "SELECT m.id, m.content, m.tags, m.type, m.importance, m.depth, m.confidence, m.valid_until, ml.strength "
        "FROM memory_links ml JOIN memories m ON ml.memory_id = m.id "
        "WHERE ml.theme_id = ? AND m.status = 'active' "
        "ORDER BY ml.strength DESC, m.importance DESC LIMIT ?",
        (theme_id, limit),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "content": r[1], "tags": r[2], "type": r[3],
         "importance": r[4], "depth": _store._clamp_depth(r[5]), "confidence": r[6], "valid_until": r[7], "strength": r[8]}
        for r in rows
    ]


def get_memories_for_detection(limit: int = 50) -> list[dict]:
    """返回用于主题检测的核心记忆（importance >= 3，排除 reflection/context）。含 session_id。"""
    conn = sqlite3.connect(_store.DB_PATH)
    rows = conn.execute(
        "SELECT id, content, tags, type, importance, depth, created_at, confidence, valid_until, session_id "
        "FROM memories WHERE status = 'active' AND importance >= 3 "
        "AND type NOT IN ('reflection', 'context') "
        "ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = _store._row_to_dict(r[:9], has_date=True)
        d["session_id"] = r[9] if len(r) > 9 else None
        result.append(d)
    return result
