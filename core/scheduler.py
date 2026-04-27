"""
P2-D: 定时任务调度器

间隔制调度（daily / weekly / monthly / Nh），启动时执行到期任务。
数据持久化在 archer.db scheduled_tasks 表（由 memory/store.py init_db 建表）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from memory.store import DB_PATH
from core.tool_runtime import invoke as runtime_invoke

# ── 间隔别名 ───────────────────────────────────────────────────────────────────

_ALIASES: dict[str, int] = {
    "daily":   24,
    "weekly":  168,
    "monthly": 720,
}


def parse_interval(spec: str) -> int:
    """
    解析间隔规格，返回小时数。
    支持：daily / weekly / monthly / Nh（如 6h、48h）
    """
    s = spec.strip().lower()
    if s in _ALIASES:
        return _ALIASES[s]
    if s.endswith("h") and s[:-1].isdigit():
        hours = int(s[:-1])
        if hours < 1:
            raise ValueError("间隔最少 1 小时")
        return hours
    raise ValueError(
        f"无效的间隔格式：{spec!r}。支持：daily, weekly, monthly, Nh（如 6h）"
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── CRUD ───────────────────────────────────────────────────────────────────────

def add_task(
    skill_name: str,
    interval_spec: str,
    label: str = "",
    args: dict | None = None,
    db_path: Path = DB_PATH,
) -> int:
    """添加定时任务，next_run_at 设为当前时间（下次启动即执行）。"""
    interval_h = parse_interval(interval_spec)
    args_json = json.dumps(args or {}, ensure_ascii=False)
    now = _now()
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO scheduled_tasks (skill_name, label, interval_h, args_json, next_run_at, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (skill_name, label, interval_h, args_json, now, now),
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    return task_id


def remove_task(task_id: int, db_path: Path = DB_PATH) -> bool:
    conn = sqlite3.connect(db_path)
    cur = conn.execute("DELETE FROM scheduled_tasks WHERE id=?", (task_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def set_enabled(task_id: int, enabled: bool, db_path: Path = DB_PATH) -> bool:
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "UPDATE scheduled_tasks SET enabled=? WHERE id=?",
        (1 if enabled else 0, task_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def list_tasks(db_path: Path = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM scheduled_tasks ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_due_tasks(db_path: Path = DB_PATH) -> list[dict]:
    """返回 enabled=1 且 next_run_at <= now 的任务。"""
    now = _now()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE enabled=1 AND next_run_at <= ?",
        (now,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_task(task_id: int, db_path: Path = DB_PATH) -> dict | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE id=?", (task_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _mark_ran(task_id: int, interval_h: int, db_path: Path = DB_PATH):
    now = datetime.now()
    next_run = (now + timedelta(hours=interval_h)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE scheduled_tasks SET last_run_at=?, next_run_at=? WHERE id=?",
        (now.isoformat(timespec="seconds"), next_run, task_id),
    )
    conn.commit()
    conn.close()


# ── 执行 ───────────────────────────────────────────────────────────────────────

def run_task(task: dict, skills: dict) -> Any:
    """执行单个任务，返回 ToolResult（技能不存在时返回 None）。"""
    skill_name = task["skill_name"]
    if skill_name not in skills:
        return None
    try:
        args = json.loads(task.get("args_json") or "{}")
    except Exception:
        args = {}
    return runtime_invoke(skill_name, args, skills)


def run_due_tasks(skills: dict, db_path: Path = DB_PATH) -> list[tuple[dict, Any]]:
    """
    检查并执行所有到期任务。
    返回 [(task_dict, ToolResult | None)]，供调用方展示结果。
    技能未加载的任务：ToolResult=None，仍更新 next_run_at（避免每次重试）。
    """
    due = get_due_tasks(db_path)
    results = []
    for task in due:
        tr = run_task(task, skills)
        _mark_ran(task["id"], task["interval_h"], db_path)
        results.append((task, tr))
    return results


def run_task_by_id(task_id: int, skills: dict, db_path: Path = DB_PATH) -> Any:
    """手动立即执行指定任务，更新 last_run_at / next_run_at。"""
    task = get_task(task_id, db_path)
    if task is None:
        return None
    tr = run_task(task, skills)
    _mark_ran(task_id, task["interval_h"], db_path)
    return tr


# ── 格式化辅助 ─────────────────────────────────────────────────────────────────

def fmt_interval(hours: int) -> str:
    if hours == 24:
        return "每天"
    if hours == 168:
        return "每周"
    if hours == 720:
        return "每月"
    return f"每 {hours} 小时"
