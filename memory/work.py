"""
Work Item 系统 (v1.4)

work_items 表：聚焦"单次交付物"的轻量任务追踪。
与 Project 的区别：Work item 是"做完就结束"，Project 是"长期跟踪事件流"。

checklist 字段：JSON 数组 [{"item": "文本", "done": false}, ...]
artifacts 字段：JSON 数组 ["路径1", "路径2"]
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

WORK_STATUSES = ("pending", "in_progress", "done", "cancelled")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _conn(db_path: Path | None = None) -> sqlite3.Connection:
    import memory.store as _store
    conn = sqlite3.connect(db_path or _store.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_work_table(db_path: Path | None = None) -> None:
    conn = _conn(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_items (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT    NOT NULL,
            description  TEXT    DEFAULT '',
            status       TEXT    DEFAULT 'pending',
            checklist    TEXT    DEFAULT '[]',
            artifacts    TEXT    DEFAULT '[]',
            project_id   INTEGER,
            session_id   TEXT,
            created_at   TEXT    NOT NULL,
            updated_at   TEXT    NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def create(
    title: str,
    description: str = "",
    checklist: list[str] | None = None,
    project_id: int | None = None,
    session_id: str | None = None,
) -> int:
    items = [{"item": t, "done": False} for t in (checklist or [])]
    now = _now()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO work_items (title, description, checklist, project_id, session_id, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (title, description, json.dumps(items, ensure_ascii=False),
         project_id, session_id, now, now),
    )
    wid = cur.lastrowid
    conn.commit()
    conn.close()
    return wid


def get(work_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM work_items WHERE id=?", (work_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["checklist"] = json.loads(d.get("checklist") or "[]")
    d["artifacts"] = json.loads(d.get("artifacts") or "[]")
    return d


def list_active(limit: int = 20) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM work_items WHERE status IN ('pending','in_progress')"
        " ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return _hydrate(rows)


def list_all(limit: int = 50) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM work_items ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return _hydrate(rows)


def update_status(work_id: int, status: str) -> bool:
    if status not in WORK_STATUSES:
        return False
    conn = _conn()
    cur = conn.execute(
        "UPDATE work_items SET status=?, updated_at=? WHERE id=?",
        (status, _now(), work_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def add_checklist_item(work_id: int, item_text: str) -> bool:
    w = get(work_id)
    if not w:
        return False
    items = w["checklist"]
    items.append({"item": item_text, "done": False})
    return _update_checklist(work_id, items)


def check_item(work_id: int, item_index: int, done: bool = True) -> bool:
    """勾选（或取消勾选）第 item_index 个检查项（从 1 开始）。"""
    w = get(work_id)
    if not w:
        return False
    items = w["checklist"]
    idx = item_index - 1
    if idx < 0 or idx >= len(items):
        return False
    items[idx]["done"] = done
    return _update_checklist(work_id, items)


def add_artifact(work_id: int, path: str) -> bool:
    w = get(work_id)
    if not w:
        return False
    artifacts = w["artifacts"]
    if path not in artifacts:
        artifacts.append(path)
    conn = _conn()
    cur = conn.execute(
        "UPDATE work_items SET artifacts=?, updated_at=? WHERE id=?",
        (json.dumps(artifacts, ensure_ascii=False), _now(), work_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def delete(work_id: int) -> bool:
    conn = _conn()
    cur = conn.execute("DELETE FROM work_items WHERE id=?", (work_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def _update_checklist(work_id: int, items: list) -> bool:
    conn = _conn()
    cur = conn.execute(
        "UPDATE work_items SET checklist=?, updated_at=? WHERE id=?",
        (json.dumps(items, ensure_ascii=False), _now(), work_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def _hydrate(rows) -> list[dict]:
    result = []
    for row in rows:
        d = dict(row)
        d["checklist"] = json.loads(d.get("checklist") or "[]")
        d["artifacts"] = json.loads(d.get("artifacts") or "[]")
        result.append(d)
    return result
