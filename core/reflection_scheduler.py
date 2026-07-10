"""Reflection scheduler internals for Soul Insight reviews."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from core.scheduler import add_task, list_tasks
from core.tool_runtime import ToolResult
from memory.store import DB_PATH


HYPOTHESIS_SCAN_TASK = "reflection_scheduler.scan_hypotheses"


def ensure_hypothesis_scan_schedule(
    *,
    interval_spec: str = "daily",
    db_path: Path = DB_PATH,
    now: datetime | None = None,
    output_path: Path | None = None,
) -> int:
    """Ensure the daily due-hypothesis scan exists as an internal scheduled task."""
    for task in list_tasks(db_path=db_path):
        if task.get("skill_name") == HYPOTHESIS_SCAN_TASK:
            return int(task["id"])
    return add_task(
        HYPOTHESIS_SCAN_TASK,
        interval_spec,
        label="Soul Insight 到期假设扫描",
        args={"kind": "hypothesis_due"},
        catchup="latest",
        db_path=db_path,
        now=now,
        output_path=output_path,
    )


def scan_due_hypotheses(
    *,
    db_path: Path = DB_PATH,
    now: datetime | None = None,
    limit: int = 20,
) -> ToolResult:
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    due = _due_hypotheses(db_path, stamp, limit=limit)
    if not due:
        return ToolResult(
            ok=True,
            skill=HYPOTHESIS_SCAN_TASK,
            summary="没有到期 hypothesis",
            content_preview="暂无需要验证的 hypothesis。",
            meta={"dueCount": 0, "hypotheses": []},
        )
    lines = [
        f"- #{item['id']} {item['title']}：{item['statement']}"
        for item in due
    ]
    return ToolResult(
        ok=True,
        skill=HYPOTHESIS_SCAN_TASK,
        summary=f"发现 {len(due)} 条到期 hypothesis",
        content_preview="\n".join(lines),
        meta={"dueCount": len(due), "hypotheses": due},
    )


def _due_hypotheses(db_path: Path, stamp: str, *, limit: int) -> list[dict]:
    if not db_path.exists():
        return []
    try:
        limit = max(1, min(int(limit), 100))
    except Exception:
        limit = 20
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, title, statement, validate_after, source, trigger_type "
            "FROM hypotheses WHERE status='active' AND validate_after <= ? "
            "AND (muted_until IS NULL OR muted_until = '' OR muted_until <= ?) "
            "ORDER BY validate_after ASC, id ASC LIMIT ?",
            (stamp, stamp, limit),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return [dict(row) for row in rows]
