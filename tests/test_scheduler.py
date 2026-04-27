"""
P2-D — Scheduler Tests
验证间隔解析、CRUD、到期检测、mark_ran、run_due_tasks。
"""
import json
import sqlite3
import sys
import tempfile
import time
import types
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.scheduler import (
    _mark_ran, add_task, fmt_interval, get_due_tasks, get_task,
    list_tasks, parse_interval, remove_task, run_due_tasks,
    run_task, run_task_by_id, set_enabled,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _make_db() -> Path:
    """建立临时数据库并创建 scheduled_tasks 表。"""
    tmp = tempfile.mkdtemp()
    db = Path(tmp) / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE scheduled_tasks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name   TEXT    NOT NULL,
            label        TEXT    DEFAULT '',
            interval_h   INTEGER NOT NULL,
            args_json    TEXT    DEFAULT '{}',
            enabled      INTEGER DEFAULT 1,
            last_run_at  TEXT,
            next_run_at  TEXT    NOT NULL,
            created_at   TEXT    NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    return db


def _mock_skill(name: str, result_content: str = "ok"):
    """构造最小 mock skill 模块，run(args) 返回 result_content。"""
    mod = types.ModuleType(name)
    mod.SKILL = {"name": name, "default_timeout": 10}
    mod.schema = lambda: {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}
    mod.run = lambda args: result_content
    return mod


# ── parse_interval ────────────────────────────────────────────────────────────

def test_parse_daily():
    assert parse_interval("daily") == 24

def test_parse_weekly():
    assert parse_interval("weekly") == 168

def test_parse_monthly():
    assert parse_interval("monthly") == 720

def test_parse_nh():
    assert parse_interval("6h") == 6
    assert parse_interval("48h") == 48

def test_parse_case_insensitive():
    assert parse_interval("Daily") == 24
    assert parse_interval("WEEKLY") == 168

def test_parse_invalid():
    import pytest
    with pytest.raises(ValueError):
        parse_interval("2days")
    with pytest.raises(ValueError):
        parse_interval("0h")
    with pytest.raises(ValueError):
        parse_interval("")


# ── fmt_interval ──────────────────────────────────────────────────────────────

def test_fmt_daily():
    assert fmt_interval(24) == "每天"

def test_fmt_weekly():
    assert fmt_interval(168) == "每周"

def test_fmt_custom():
    assert "6" in fmt_interval(6)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_add_and_list():
    db = _make_db()
    tid = add_task("weather", "daily", label="天气提醒", db_path=db)
    assert isinstance(tid, int)
    tasks = list_tasks(db_path=db)
    assert len(tasks) == 1
    assert tasks[0]["skill_name"] == "weather"
    assert tasks[0]["label"] == "天气提醒"
    assert tasks[0]["interval_h"] == 24

def test_add_with_args():
    db = _make_db()
    add_task("weather", "6h", args={"city": "Beijing"}, db_path=db)
    tasks = list_tasks(db_path=db)
    stored_args = json.loads(tasks[0]["args_json"])
    assert stored_args["city"] == "Beijing"

def test_remove_task():
    db = _make_db()
    tid = add_task("weather", "daily", db_path=db)
    assert remove_task(tid, db_path=db) is True
    assert list_tasks(db_path=db) == []

def test_remove_nonexistent():
    db = _make_db()
    assert remove_task(999, db_path=db) is False

def test_set_enabled_disable():
    db = _make_db()
    tid = add_task("weather", "daily", db_path=db)
    assert set_enabled(tid, False, db_path=db) is True
    task = get_task(tid, db_path=db)
    assert task["enabled"] == 0

def test_set_enabled_re_enable():
    db = _make_db()
    tid = add_task("weather", "daily", db_path=db)
    set_enabled(tid, False, db_path=db)
    set_enabled(tid, True, db_path=db)
    task = get_task(tid, db_path=db)
    assert task["enabled"] == 1

def test_get_task_nonexistent():
    db = _make_db()
    assert get_task(999, db_path=db) is None


# ── 到期检测 ──────────────────────────────────────────────────────────────────

def test_due_task_detected():
    db = _make_db()
    # next_run_at 设为过去
    past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO scheduled_tasks (skill_name, interval_h, next_run_at, created_at) VALUES (?,?,?,?)",
        ("weather", 24, past, past),
    )
    conn.commit()
    conn.close()
    due = get_due_tasks(db_path=db)
    assert len(due) == 1
    assert due[0]["skill_name"] == "weather"

def test_not_due_task_excluded():
    db = _make_db()
    future = (datetime.now() + timedelta(hours=2)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO scheduled_tasks (skill_name, interval_h, next_run_at, created_at) VALUES (?,?,?,?)",
        ("weather", 24, future, future),
    )
    conn.commit()
    conn.close()
    assert get_due_tasks(db_path=db) == []

def test_disabled_task_not_due():
    db = _make_db()
    past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO scheduled_tasks (skill_name, interval_h, enabled, next_run_at, created_at) VALUES (?,?,?,?,?)",
        ("weather", 24, 0, past, past),
    )
    conn.commit()
    conn.close()
    assert get_due_tasks(db_path=db) == []


# ── _mark_ran ─────────────────────────────────────────────────────────────────

def test_mark_ran_updates_timestamps():
    db = _make_db()
    past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO scheduled_tasks (skill_name, interval_h, next_run_at, created_at) VALUES (?,?,?,?)",
        ("weather", 24, past, past),
    )
    tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    _mark_ran(tid, 24, db_path=db)

    task = get_task(tid, db_path=db)
    assert task["last_run_at"] is not None
    # next_run_at 应该在现在之后
    assert task["next_run_at"] > datetime.now().isoformat(timespec="seconds")


# ── run_due_tasks ─────────────────────────────────────────────────────────────

def test_run_due_tasks_with_mock_skill():
    db = _make_db()
    past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO scheduled_tasks (skill_name, interval_h, next_run_at, created_at) VALUES (?,?,?,?)",
        ("weather", 24, past, past),
    )
    conn.commit()
    conn.close()

    skills = {"weather": _mock_skill("weather", "晴，25°C")}
    results = run_due_tasks(skills, db_path=db)

    assert len(results) == 1
    task, tr = results[0]
    assert task["skill_name"] == "weather"
    assert tr is not None
    assert tr.ok

    # 执行后不再是到期状态
    assert get_due_tasks(db_path=db) == []

def test_run_due_tasks_skill_not_loaded():
    db = _make_db()
    past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO scheduled_tasks (skill_name, interval_h, next_run_at, created_at) VALUES (?,?,?,?)",
        ("missing_skill", 24, past, past),
    )
    conn.commit()
    conn.close()

    results = run_due_tasks({}, db_path=db)
    assert len(results) == 1
    _, tr = results[0]
    assert tr is None  # 技能未加载
    # 仍然更新了 next_run_at，不重复执行
    assert get_due_tasks(db_path=db) == []

def test_run_due_tasks_empty():
    db = _make_db()
    results = run_due_tasks({}, db_path=db)
    assert results == []


# ── run_task_by_id ────────────────────────────────────────────────────────────

def test_run_task_by_id_ok():
    db = _make_db()
    past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO scheduled_tasks (skill_name, interval_h, next_run_at, created_at) VALUES (?,?,?,?)",
        ("weather", 24, past, past),
    )
    tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    skills = {"weather": _mock_skill("weather")}
    tr = run_task_by_id(tid, skills, db_path=db)
    assert tr is not None
    assert tr.ok

def test_run_task_by_id_nonexistent():
    db = _make_db()
    assert run_task_by_id(999, {}, db_path=db) is None
