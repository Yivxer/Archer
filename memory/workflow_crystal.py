"""
workflow_crystal — 工作流结晶模块。

将多步工具链保存为可复用工作流，支持按名称/关键词触发。
由 store.init_db() 调用 init_table() 初始化表。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _conn(db_path: Path | None = None) -> sqlite3.Connection:
    import memory.store as _store
    conn = sqlite3.connect(db_path or _store.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── 表初始化（由 store.init_db 调用）───────────────────────────────────────

def init_table(db_path: Path | None = None) -> None:
    """创建 workflow_crystal 表（幂等）。由 store.init_db() 调用。"""
    conn = _conn(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_crystal (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            keywords    TEXT    DEFAULT '',
            steps_json  TEXT    NOT NULL,
            use_count   INTEGER DEFAULT 0,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# ── CRUD ─────────────────────────────────────────────────────────────────────

def save(name: str, steps: list[dict], keywords: str = "") -> int:
    """
    保存一条工作流，返回新 ID。
    steps: [{"skill": "xxx", "args": {...}}, ...]
    """
    name = name.strip()
    keywords = keywords.strip()
    steps_json = json.dumps(steps, ensure_ascii=False)
    now = _now()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO workflow_crystal (name, keywords, steps_json, use_count, created_at, updated_at) "
        "VALUES (?, ?, ?, 0, ?, ?)",
        (name, keywords, steps_json, now, now),
    )
    conn.commit()
    wid = cur.lastrowid
    conn.close()
    assert wid is not None, "INSERT 未返回 lastrowid"
    return wid


def list_all() -> list[dict]:
    """返回所有工作流（按使用次数降序）。"""
    conn = _conn()
    rows = conn.execute(
        "SELECT id, name, keywords, steps_json, use_count, created_at, updated_at "
        "FROM workflow_crystal ORDER BY use_count DESC, id DESC"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "id": r["id"],
            "name": r["name"],
            "keywords": r["keywords"],
            "steps": json.loads(r["steps_json"]),
            "use_count": r["use_count"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    return result


def get(wid: int) -> dict | None:
    """按 ID 获取工作流，不存在返回 None。"""
    conn = _conn()
    r = conn.execute(
        "SELECT id, name, keywords, steps_json, use_count, created_at, updated_at "
        "FROM workflow_crystal WHERE id = ?", (wid,)
    ).fetchone()
    conn.close()
    if not r:
        return None
    return {
        "id": r["id"],
        "name": r["name"],
        "keywords": r["keywords"],
        "steps": json.loads(r["steps_json"]),
        "use_count": r["use_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def delete(wid: int) -> bool:
    """删除工作流，返回是否成功。"""
    conn = _conn()
    cur = conn.execute("DELETE FROM workflow_crystal WHERE id = ?", (wid,))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def increment_use(wid: int) -> None:
    """使用次数 +1。"""
    conn = _conn()
    conn.execute(
        "UPDATE workflow_crystal SET use_count = use_count + 1, updated_at = ? WHERE id = ?",
        (_now(), wid),
    )
    conn.commit()
    conn.close()


def search(keyword: str) -> list[dict]:
    """按名称或关键词搜索工作流，返回匹配列表。"""
    conn = _conn()
    like = f"%{keyword}%"
    rows = conn.execute(
        "SELECT id, name, keywords, steps_json, use_count, created_at, updated_at "
        "FROM workflow_crystal WHERE name LIKE ? OR keywords LIKE ? ORDER BY use_count DESC, id DESC",
        (like, like),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "id": r["id"],
            "name": r["name"],
            "keywords": r["keywords"],
            "steps": json.loads(r["steps_json"]),
            "use_count": r["use_count"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    return result
