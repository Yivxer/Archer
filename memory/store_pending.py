"""待确认记忆（pending_memories）审阅管理（从 memory/store.py 抽出）。

包含：
- add_pending: 写入候选记忆
- list_pending: 列出待确认
- count_pending: 统计待确认数量
- update_pending: 编辑待确认内容
- accept_pending: 接受并写入主表（调用 store.save）
- reject_pending: 软拒绝

依赖：DB_PATH / MEMORY_TYPES / infer_block_type / normalize_label / save 通过
`import memory.store as _store` 动态查找，确保测试修改 _store.DB_PATH 生效。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import memory.store as _store


def _now() -> str:
    """当前 ISO 时间字符串（秒精度）。与 store._now 实现一致。"""
    return datetime.now().isoformat(timespec="seconds")


def add_pending(content: str, type: str = "insight", importance: int = 3,
                tags: str = "", source: str = "auto", confidence: float = 0.7,
                depth: int = 3, suggest_reason: str = "",
                block_type: str | None = None, label: str | None = None,
                session_summary: str = "", *, db_path: str | Path | None = None) -> int:
    """将候选记忆写入 pending_memories 表，返回 ID。"""
    content = content.strip()
    if type not in _store.MEMORY_TYPES:
        type = "insight"
    try:
        importance = max(1, min(5, int(importance)))
    except Exception:
        importance = 3
    try:
        depth = max(1, min(5, int(depth)))
    except Exception:
        depth = 3
    resolved_block = _store.infer_block_type(type, block_type)
    resolved_label = _store.normalize_label(label)

    conn = sqlite3.connect(db_path or _store.DB_PATH)
    cur = conn.execute(
        "INSERT INTO pending_memories (content, type, importance, depth, tags, source, confidence, "
        "created_at, suggest_reason, block_type, label, session_summary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (content, type, importance, depth, tags.strip(), source, float(confidence),
         _now(), suggest_reason.strip(), resolved_block, resolved_label, session_summary.strip()),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    assert pid is not None, "INSERT 未返回 lastrowid"
    return pid


def list_pending(limit: int = 50, include_rejected: bool = False) -> list[dict]:
    """返回待确认记忆。默认仅 pending，include_rejected=True 时包含 rejected。"""
    conn = sqlite3.connect(_store.DB_PATH)
    if include_rejected:
        rows = conn.execute(
            "SELECT id, content, type, importance, depth, tags, source, confidence, created_at, "
            "status, suggest_reason, block_type, label, session_summary "
            "FROM pending_memories ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content, type, importance, depth, tags, source, confidence, created_at, "
            "status, suggest_reason, block_type, label, session_summary "
            "FROM pending_memories WHERE status = 'pending' ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "content": r[1], "type": r[2],
            "importance": r[3], "depth": r[4], "tags": r[5],
            "source": r[6], "confidence": r[7], "created_at": r[8],
            "status": r[9] if len(r) > 9 and r[9] else "pending",
            "suggest_reason": r[10] if len(r) > 10 and r[10] else "",
            "block_type": r[11] if len(r) > 11 and r[11] else _store.infer_block_type(r[2]),
            "label": r[12] if len(r) > 12 and r[12] else "",
            "session_summary": r[13] if len(r) > 13 and r[13] else "",
        }
        for r in rows
    ]


def count_pending(include_rejected: bool = False) -> int:
    """返回待确认记忆数量。"""
    conn = sqlite3.connect(_store.DB_PATH)
    if include_rejected:
        n = conn.execute("SELECT COUNT(*) FROM pending_memories").fetchone()[0]
    else:
        n = conn.execute("SELECT COUNT(*) FROM pending_memories WHERE status = 'pending'").fetchone()[0]
    conn.close()
    return n


def update_pending(pid: int, content: str) -> bool:
    """编辑一条待确认记忆的内容，返回是否更新成功。"""
    content = content.strip()
    if not content:
        return False
    conn = sqlite3.connect(_store.DB_PATH)
    cur = conn.execute(
        "UPDATE pending_memories SET content = ? WHERE id = ?",
        (content, int(pid)),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def accept_pending(pid: int | str) -> list[int]:
    """
    接受待确认记忆，写入主 memories 表并从 pending 中删除。
    pid 可以是具体 ID 或 "all"。返回写入的 memory ID 列表。
    """
    conn = sqlite3.connect(_store.DB_PATH)
    if str(pid) == "all":
        rows = conn.execute(
            "SELECT id, content, type, importance, depth, tags, source, confidence, block_type, label "
            "FROM pending_memories WHERE status = 'pending'"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content, type, importance, depth, tags, source, confidence, block_type, label "
            "FROM pending_memories WHERE id = ? AND status = 'pending'",
            (int(pid),),
        ).fetchall()
    conn.close()

    if not rows:
        return []

    memory_ids = []
    accepted_pids = []
    for row in rows:
        p_id, content, type_, importance, depth, tags, source, confidence, block_type, label = row
        mid = _store.save(
            content, tags=tags, type=type_, importance=importance, source=source,
            confidence=confidence, depth=depth, block_type=block_type, label=label,
        )
        memory_ids.append(mid)
        accepted_pids.append(p_id)

    conn = sqlite3.connect(_store.DB_PATH)
    if str(pid) == "all":
        conn.execute("DELETE FROM pending_memories WHERE status = 'pending'")
    else:
        conn.execute("DELETE FROM pending_memories WHERE id = ? AND status = 'pending'", (int(pid),))
    conn.commit()
    conn.close()

    return memory_ids


def reject_pending(pid: int | str) -> int:
    """
    软拒绝待确认记忆（status 改为 rejected）。pid 可以是具体 ID 或 "all"。返回更新数量。
    """
    conn = sqlite3.connect(_store.DB_PATH)
    if str(pid) == "all":
        n = conn.execute("SELECT COUNT(*) FROM pending_memories WHERE status = 'pending'").fetchone()[0]
        conn.execute("UPDATE pending_memories SET status = 'rejected' WHERE status = 'pending'")
    else:
        cur = conn.execute(
            "UPDATE pending_memories SET status = 'rejected' WHERE id = ? AND status = 'pending'",
            (int(pid),),
        )
        n = cur.rowcount
    conn.commit()
    conn.close()
    return n

