"""
Sub-task 系统 (v1.5 Phase A/B)

sub_tasks 表：Work item 下的子代理任务单元。
每个 sub_task 是一次独立的 LLM 调用，有自己的 agent_type + system prompt。

agent_type 决定系统提示策略：
  explore  — 搜索和整理信息，不做决策
  plan     — 基于已知信息制定方案，不执行
  work     — 执行具体任务（可调用工具）
  review   — 审查结果，找问题和遗漏

model_tier 决定用哪个模型：
  fast     — cfg["models"][1]（flash/turbo，快而省）
  default  — cfg["models"][0]（主模型）
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

AGENT_TYPES = ("explore", "plan", "work", "review")
MODEL_TIERS  = ("fast", "default")
SUBTASK_STATUSES = ("pending", "running", "done", "failed", "cancelled")

# 各 agent_type 对应的系统提示骨架
_AGENT_PROMPTS: dict[str, str] = {
    "explore": (
        "你是一个信息搜集代理。任务：搜集、整理和归纳信息。\n"
        "规则：只做搜集和整理，不做建议和决策。结果要结构化，来源要清晰。"
    ),
    "plan": (
        "你是一个规划代理。任务：基于已有信息制定可执行方案。\n"
        "规则：方案要分步骤，每步骤要可验证。不执行，只规划。"
    ),
    "work": (
        "你是一个执行代理。任务：按指令完成具体工作，可调用工具。\n"
        "规则：直接执行，不多解释。遇到阻碍立即报告，不自行绕过。"
    ),
    "review": (
        "你是一个审查代理。任务：审查结果的质量、完整性和正确性。\n"
        "规则：找问题和遗漏，不修改原内容。给出具体的改进建议。"
    ),
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _conn(db_path: Path | None = None) -> sqlite3.Connection:
    import memory.store as _store
    conn = sqlite3.connect(db_path or _store.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_subtask_table(db_path: Path | None = None) -> None:
    conn = _conn(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sub_tasks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            work_item_id  INTEGER REFERENCES work_items(id),
            agent_type    TEXT    NOT NULL DEFAULT 'work',
            model_tier    TEXT    NOT NULL DEFAULT 'default',
            prompt        TEXT    NOT NULL,
            status        TEXT    NOT NULL DEFAULT 'pending',
            result        TEXT,
            error_msg     TEXT,
            session_id    TEXT,
            created_at    TEXT    NOT NULL,
            started_at    TEXT,
            finished_at   TEXT
        )
    """)
    conn.commit()
    conn.close()


def create(
    prompt: str,
    agent_type: str = "work",
    model_tier: str = "default",
    work_item_id: int | None = None,
    session_id: str | None = None,
) -> int:
    if agent_type not in AGENT_TYPES:
        agent_type = "work"
    if model_tier not in MODEL_TIERS:
        model_tier = "default"
    now = _now()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO sub_tasks (work_item_id, agent_type, model_tier, prompt, session_id, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (work_item_id, agent_type, model_tier, prompt, session_id, now),
    )
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    assert tid is not None, "INSERT 未返回 lastrowid"
    return tid


def get(subtask_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM sub_tasks WHERE id=?", (subtask_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_for_work(work_item_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM sub_tasks WHERE work_item_id=? ORDER BY id",
        (work_item_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_pending() -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM sub_tasks WHERE status='pending' ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_running(subtask_id: int) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE sub_tasks SET status='running', started_at=? WHERE id=?",
        (_now(), subtask_id),
    )
    conn.commit()
    conn.close()


def set_done(subtask_id: int, result: str) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE sub_tasks SET status='done', result=?, finished_at=? WHERE id=?",
        (result, _now(), subtask_id),
    )
    conn.commit()
    conn.close()


def set_failed(subtask_id: int, error_msg: str) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE sub_tasks SET status='failed', error_msg=?, finished_at=? WHERE id=?",
        (error_msg, _now(), subtask_id),
    )
    conn.commit()
    conn.close()


def cancel(subtask_id: int) -> bool:
    conn = _conn()
    cur = conn.execute(
        "UPDATE sub_tasks SET status='cancelled' WHERE id=? AND status='pending'",
        (subtask_id,),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def delete(subtask_id: int) -> bool:
    conn = _conn()
    cur = conn.execute("DELETE FROM sub_tasks WHERE id=?", (subtask_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def get_agent_system_prompt(agent_type: str) -> str:
    return _AGENT_PROMPTS.get(agent_type, _AGENT_PROMPTS["work"])
