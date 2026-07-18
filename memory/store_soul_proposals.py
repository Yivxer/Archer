"""SOUL 演化提议（soul_proposals）管理（从 memory/store.py 抽出）。

包含：add_soul_proposal / list_soul_proposals / count_soul_proposals / resolve_soul_proposal

依赖：DB_PATH / _now 通过 `import memory.store as _store` 动态查找。
"""

from __future__ import annotations

import sqlite3

import memory.store as _store


def _now() -> str:
    return _store._now()


def add_soul_proposal(content: str, source: str = "reflect") -> int:
    """添加一条待审阅的 SOUL 演化提议，返回 ID。"""
    conn = sqlite3.connect(_store.DB_PATH)
    cur = conn.execute(
        "INSERT INTO soul_proposals (content, source, status, created_at) VALUES (?,?,?,?)",
        (content.strip(), source, "pending", _now()),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    assert pid is not None, "INSERT 未返回 lastrowid"
    return pid


def list_soul_proposals(status: str = "pending") -> list[dict]:
    conn = sqlite3.connect(_store.DB_PATH)
    rows = conn.execute(
        "SELECT id, content, source, status, created_at FROM soul_proposals "
        "WHERE status = ? ORDER BY id",
        (status,),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "content": r[1], "source": r[2], "status": r[3], "created_at": r[4]}
        for r in rows
    ]


def count_soul_proposals() -> int:
    conn = sqlite3.connect(_store.DB_PATH)
    n = conn.execute(
        "SELECT COUNT(*) FROM soul_proposals WHERE status = 'pending'"
    ).fetchone()[0]
    conn.close()
    return n


def resolve_soul_proposal(pid: int | str, accepted: bool) -> list[int]:
    """将提议标记为 accepted 或 rejected，返回处理的 ID 列表。"""
    conn = sqlite3.connect(_store.DB_PATH)
    status = "accepted" if accepted else "rejected"
    if str(pid) == "all":
        rows = conn.execute(
            "SELECT id FROM soul_proposals WHERE status = 'pending'"
        ).fetchall()
        ids = [r[0] for r in rows]
        conn.execute(
            "UPDATE soul_proposals SET status = ?, reviewed_at = ? WHERE status = 'pending'",
            (status, _now()),
        )
    else:
        conn.execute(
            "UPDATE soul_proposals SET status = ?, reviewed_at = ? WHERE id = ? AND status = 'pending'",
            (status, _now(), int(pid)),
        )
        ids = [int(pid)]
    conn.commit()
    conn.close()
    return ids
