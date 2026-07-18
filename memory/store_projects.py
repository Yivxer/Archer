"""项目（projects）管理（从 memory/store.py 抽出）。

包含：create_project / list_projects / get_project / get_project_by_name /
      archive_project / log_project_event / get_project_events

依赖：DB_PATH / _now 通过 `import memory.store as _store` 动态查找。
"""

from __future__ import annotations

import sqlite3

import memory.store as _store


def _now() -> str:
    return _store._now()


def create_project(name: str, description: str = "") -> int:
    """创建项目，返回 ID。名称重复时返回已有 ID。"""
    name = name.strip()
    conn = sqlite3.connect(_store.DB_PATH)
    existing = conn.execute(
        "SELECT id FROM projects WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    if existing:
        conn.close()
        return existing[0]
    cur = conn.execute(
        "INSERT INTO projects (name, description, status, created_at, updated_at) VALUES (?,?,?,?,?)",
        (name, description.strip(), "active", _now(), _now()),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def list_projects(include_archived: bool = False) -> list[dict]:
    conn = sqlite3.connect(_store.DB_PATH)
    if include_archived:
        rows = conn.execute(
            "SELECT id, name, description, status, created_at, updated_at FROM projects "
            "ORDER BY status ASC, updated_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name, description, status, created_at, updated_at FROM projects "
            "WHERE status = 'active' ORDER BY updated_at DESC"
        ).fetchall()
    conn.close()
    return [
        {"id": r[0], "name": r[1], "description": r[2],
         "status": r[3], "created_at": r[4], "updated_at": r[5]}
        for r in rows
    ]


def get_project(pid: int) -> dict | None:
    conn = sqlite3.connect(_store.DB_PATH)
    row = conn.execute(
        "SELECT id, name, description, status, created_at, updated_at FROM projects WHERE id = ?",
        (pid,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "description": row[2],
            "status": row[3], "created_at": row[4], "updated_at": row[5]}


def get_project_by_name(name: str) -> dict | None:
    conn = sqlite3.connect(_store.DB_PATH)
    row = conn.execute(
        "SELECT id, name, description, status, created_at, updated_at FROM projects WHERE name = ?",
        (name.strip(),),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "description": row[2],
            "status": row[3], "created_at": row[4], "updated_at": row[5]}


def archive_project(pid: int) -> bool:
    conn = sqlite3.connect(_store.DB_PATH)
    cur = conn.execute(
        "UPDATE projects SET status = 'archived', updated_at = ? WHERE id = ? AND status = 'active'",
        (_now(), pid),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def log_project_event(project_id: int, event_type: str, content: str) -> int:
    """记录项目事件，返回事件 ID。"""
    conn = sqlite3.connect(_store.DB_PATH)
    cur = conn.execute(
        "INSERT INTO project_events (project_id, event_type, content, created_at) VALUES (?,?,?,?)",
        (project_id, event_type, content.strip(), _now()),
    )
    conn.execute(
        "UPDATE projects SET updated_at = ? WHERE id = ?",
        (_now(), project_id),
    )
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid


def get_project_events(project_id: int, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(_store.DB_PATH)
    rows = conn.execute(
        "SELECT id, event_type, content, created_at FROM project_events "
        "WHERE project_id = ? ORDER BY id DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "event_type": r[1], "content": r[2], "created_at": r[3]}
        for r in rows
    ]
