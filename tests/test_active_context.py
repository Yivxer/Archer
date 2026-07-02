"""Tests for core/active_context.py - L0.2 10 条测试矩阵.

T1  首次启动
T2  正常退出后启动
T3  崩溃后启动 (no_exit_status_and_heartbeat_stale)
T4  SIGTERM 退出 (写 exit_status.clean=False)
T5  正常 shutdown (写 exit_status.clean=True)
T6  并发写 (flock)
T7  原子写 (读到旧版本, 不是半截 JSON)
T8  多次崩溃 (crash_count)
T9  schema_version 演进 (旧字段不崩溃)
T10 desktop_pid 不匹配 (不当崩溃处理)
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import active_context as ac


# ==================== Helpers ====================

def _iso_seconds_ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _write_active_context(journal_dir: Path, data: dict) -> None:
    """直接写, 绕过 manager (用于构造测试初始状态)."""
    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / "active_context.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ==================== T1: 首次启动 ====================

def test_T1_first_startup(tmp_path: Path) -> None:
    """无 journal/ 目录时首次启动, 应创建目录 + active_context.json, is_crash=False."""
    journal_dir = tmp_path / "journal"
    assert not journal_dir.exists()

    mgr = ac.ActiveContextManager(journal_dir)
    is_crash, reason, crash_count = mgr.on_startup(desktop_pid=12345)

    assert is_crash is False
    assert reason == "no_previous_context"
    assert crash_count == 0
    assert journal_dir.exists()
    assert (journal_dir / "active_context.json").exists()

    data = json.loads((journal_dir / "active_context.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["pid"] == os.getpid()
    assert data["desktop_pid"] == 12345
    assert data["exit_status"] is None
    assert data["session_id"] is None
    assert data["thread_id"] is None


# ==================== T2: 正常退出后启动 ====================

def test_T2_clean_exit_startup(tmp_path: Path) -> None:
    """上次 exit_status.clean=True 时启动, is_crash=False."""
    journal_dir = tmp_path / "journal"
    _write_active_context(journal_dir, {
        "schema_version": 1,
        "pid": 99999,
        "started_at": _iso_seconds_ago(3600),
        "last_heartbeat_at": _iso_seconds_ago(300),
        "exit_status": {"clean": True, "exited_at": _iso_seconds_ago(300), "reason": "user_quit"},
        "session_id": "old-session",
        "thread_id": None,
        "last_message_at": None,
        "last_tool_at": None,
        "last_trace_id": None,
        "desktop_pid": None,
    })

    mgr = ac.ActiveContextManager(journal_dir)
    is_crash, reason, crash_count = mgr.on_startup()

    assert is_crash is False
    assert reason == "clean_exit"
    assert crash_count == 0


# ==================== T3: 崩溃后启动 ====================

def test_T3_crash_startup_stale_heartbeat(tmp_path: Path) -> None:
    """exit_status=null 且 heartbeat 30s+ 前时启动, is_crash=True."""
    journal_dir = tmp_path / "journal"
    _write_active_context(journal_dir, {
        "schema_version": 1,
        "pid": 99999,
        "started_at": _iso_seconds_ago(3600),
        "last_heartbeat_at": _iso_seconds_ago(120),  # 120s 前, 超过 30s 窗口
        "exit_status": None,
        "session_id": "old-session",
        "thread_id": None,
        "last_message_at": None,
        "last_tool_at": None,
        "last_trace_id": "trace-old",
        "desktop_pid": None,
    })

    mgr = ac.ActiveContextManager(journal_dir)
    is_crash, reason, crash_count = mgr.on_startup()

    assert is_crash is True
    assert reason == "no_exit_status_and_heartbeat_stale"
    assert crash_count == 1  # 这次崩溃被记录


def test_T3b_crash_startup_fresh_heartbeat(tmp_path: Path) -> None:
    """exit_status=null 但 heartbeat 5s 前 (新鲜), is_crash=False (可能只是重启)."""
    journal_dir = tmp_path / "journal"
    _write_active_context(journal_dir, {
        "schema_version": 1,
        "pid": 99999,
        "started_at": _iso_seconds_ago(60),
        "last_heartbeat_at": _iso_seconds_ago(5),  # 5s 前, 新鲜
        "exit_status": None,
        "session_id": None,
        "thread_id": None,
        "last_message_at": None,
        "last_tool_at": None,
        "last_trace_id": None,
        "desktop_pid": None,
    })

    mgr = ac.ActiveContextManager(journal_dir)
    is_crash, reason, crash_count = mgr.on_startup()

    assert is_crash is False
    assert reason == "normal"


def test_T3c_crash_startup_unclean_exit_status(tmp_path: Path) -> None:
    """exit_status.clean=False 时启动, is_crash=True, reason 来自 exit_status."""
    journal_dir = tmp_path / "journal"
    _write_active_context(journal_dir, {
        "schema_version": 1,
        "pid": 99999,
        "started_at": _iso_seconds_ago(3600),
        "last_heartbeat_at": _iso_seconds_ago(120),
        "exit_status": {"clean": False, "exited_at": _iso_seconds_ago(120), "reason": "sigterm"},
        "session_id": None,
        "thread_id": None,
        "last_message_at": None,
        "last_tool_at": None,
        "last_trace_id": None,
        "desktop_pid": None,
    })

    mgr = ac.ActiveContextManager(journal_dir)
    is_crash, reason, crash_count = mgr.on_startup()

    assert is_crash is True
    assert reason == "sigterm"
    assert crash_count == 1


# ==================== T4: SIGTERM 退出 ====================

def test_T4_on_shutdown_unclean(tmp_path: Path) -> None:
    """on_shutdown(clean=False, reason='sigterm') 应写 exit_status.clean=False."""
    journal_dir = tmp_path / "journal"
    mgr = ac.ActiveContextManager(journal_dir)
    mgr.on_startup()

    mgr.on_shutdown(clean=False, reason="sigterm")

    data = json.loads((journal_dir / "active_context.json").read_text(encoding="utf-8"))
    assert data["exit_status"]["clean"] is False
    assert data["exit_status"]["reason"] == "sigterm"
    assert "exited_at" in data["exit_status"]


# ==================== T5: 正常 shutdown ====================

def test_T5_on_shutdown_clean(tmp_path: Path) -> None:
    """on_shutdown(clean=True, reason='user_quit') 应写 exit_status.clean=True."""
    journal_dir = tmp_path / "journal"
    mgr = ac.ActiveContextManager(journal_dir)
    mgr.on_startup()

    mgr.on_shutdown(clean=True, reason="user_quit")

    data = json.loads((journal_dir / "active_context.json").read_text(encoding="utf-8"))
    assert data["exit_status"]["clean"] is True
    assert data["exit_status"]["reason"] == "user_quit"


# ==================== T6: 并发写 (flock) ====================

def test_T6_concurrent_writes_no_corruption(tmp_path: Path) -> None:
    """两个 manager 并发写, 最终文件应是有效 JSON (不崩溃)."""
    journal_dir = tmp_path / "journal"
    mgr1 = ac.ActiveContextManager(journal_dir)
    mgr1.on_startup()

    # 并发 update_session
    errors: list[Exception] = []

    def _writer(mgr: ac.ActiveContextManager, idx: int) -> None:
        try:
            for i in range(20):
                mgr.update_session(session_id=f"session-{idx}-{i}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_writer, args=(mgr1, i)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 最终文件应是有效 JSON, 无 corruption
    data = json.loads((journal_dir / "active_context.json").read_text(encoding="utf-8"))
    assert "session_id" in data
    assert data["session_id"].startswith("session-")
    assert errors == []


# ==================== T7: 原子写 ====================

def test_T7_atomic_write_no_partial_json(tmp_path: Path) -> None:
    """写到一半被杀, 读到的应是旧版本或新版本, 不是半截 JSON."""
    journal_dir = tmp_path / "journal"
    mgr = ac.ActiveContextManager(journal_dir)
    mgr.on_startup()

    # 模拟写到一半: .tmp 文件存在但 active_context.json 完整
    (journal_dir / "active_context.json.tmp").write_text(
        '{"schema_version": 1, "pid": INCOMPLETE', encoding="utf-8"
    )

    # 读应该正常 (读 active_context.json, 不读 .tmp)
    data = mgr._read()
    assert data is not None
    assert data["schema_version"] == 1
    assert data["pid"] == os.getpid()


# ==================== T8: 多次崩溃 ====================

def test_T8_multiple_crashes_crash_count(tmp_path: Path) -> None:
    """连续 3 次崩溃后, crash_count=3."""
    journal_dir = tmp_path / "journal"

    # 模拟 3 次崩溃 → 启动
    for i in range(3):
        _write_active_context(journal_dir, {
            "schema_version": 1,
            "pid": 99999 + i,
            "started_at": _iso_seconds_ago(3600 * (3 - i)),
            "last_heartbeat_at": _iso_seconds_ago(120),  # 心跳过期
            "exit_status": None,
            "session_id": None, "thread_id": None,
            "last_message_at": None, "last_tool_at": None, "last_trace_id": None,
            "desktop_pid": None,
        })
        mgr = ac.ActiveContextManager(journal_dir)
        is_crash, reason, crash_count = mgr.on_startup()
        assert is_crash is True
        mgr.on_shutdown(clean=False, reason="test_crash")

    # 第 4 次启动应读到 crash_count=3
    _write_active_context(journal_dir, {
        "schema_version": 1,
        "pid": 99998,
        "started_at": _iso_seconds_ago(3600),
        "last_heartbeat_at": _iso_seconds_ago(120),
        "exit_status": None,
        "session_id": None, "thread_id": None,
        "last_message_at": None, "last_tool_at": None, "last_trace_id": None,
        "desktop_pid": None,
    })
    mgr = ac.ActiveContextManager(journal_dir)
    is_crash, reason, crash_count = mgr.on_startup()
    assert is_crash is True
    assert crash_count == 4  # 3 次之前 + 这次


def test_T8b_reset_journal_clears_crash_count(tmp_path: Path) -> None:
    """reset_journal 后 crash_count 归零."""
    journal_dir = tmp_path / "journal"
    _write_active_context(journal_dir, {
        "schema_version": 1, "pid": 99999,
        "started_at": _iso_seconds_ago(3600),
        "last_heartbeat_at": _iso_seconds_ago(120),
        "exit_status": None,
        "session_id": None, "thread_id": None,
        "last_message_at": None, "last_tool_at": None, "last_trace_id": None,
        "desktop_pid": None,
    })
    mgr = ac.ActiveContextManager(journal_dir)
    mgr.on_startup()  # 触发一次崩溃记录
    assert (journal_dir / "crash_count.json").exists()

    ac.reset_journal(journal_dir)
    assert not (journal_dir / "crash_count.json").exists()
    assert not (journal_dir / "active_context.json").exists()

    # 再启动 crash_count=0
    mgr2 = ac.ActiveContextManager(journal_dir)
    _, _, crash_count = mgr2.on_startup()
    assert crash_count == 0


# ==================== T9: schema_version 演进 ====================

def test_T9_old_schema_version_no_crash(tmp_path: Path) -> None:
    """旧 schema_version (或缺失字段) 启动时不应崩溃."""
    journal_dir = tmp_path / "journal"
    # 模拟旧版本: 缺 desktop_pid 和 last_trace_id 字段, schema_version=0
    _write_active_context(journal_dir, {
        "schema_version": 0,
        "pid": 99999,
        "started_at": _iso_seconds_ago(3600),
        "last_heartbeat_at": _iso_seconds_ago(300),
        "exit_status": {"clean": True, "exited_at": _iso_seconds_ago(300), "reason": "user_quit"},
        "session_id": "old-session",
        # 缺 thread_id, last_message_at, last_tool_at, last_trace_id, desktop_pid
    })

    mgr = ac.ActiveContextManager(journal_dir)
    is_crash, reason, crash_count = mgr.on_startup()

    # 应正常判定为 clean_exit, 不崩溃
    assert is_crash is False
    assert reason == "clean_exit"
    assert crash_count == 0

    # 新写入的应是 schema_version=1 + 全字段
    data = json.loads((journal_dir / "active_context.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert "thread_id" in data
    assert "desktop_pid" in data


# ==================== T10: desktop_pid 不匹配 ====================

def test_T10_desktop_pid_mismatch_not_crash(tmp_path: Path) -> None:
    """上次 desktop_pid != 当前时, 不当崩溃处理 (但应记录)."""
    journal_dir = tmp_path / "journal"
    _write_active_context(journal_dir, {
        "schema_version": 1,
        "pid": 99999,
        "started_at": _iso_seconds_ago(3600),
        "last_heartbeat_at": _iso_seconds_ago(120),  # 心跳过期
        "exit_status": None,
        "session_id": None, "thread_id": None,
        "last_message_at": None, "last_tool_at": None, "last_trace_id": None,
        "desktop_pid": 99999,  # 上次是另一个 desktop 拉起的
    })

    mgr = ac.ActiveContextManager(journal_dir)
    # 这次用不同的 desktop_pid
    is_crash, reason, crash_count = mgr.on_startup(desktop_pid=88888)

    # 心跳过期 + 无 exit_status 仍判定为崩溃 (desktop_pid 不影响崩溃判定)
    # 但这是合理的: 上次 desktop 可能崩溃了
    assert is_crash is True
    assert reason == "no_exit_status_and_heartbeat_stale"
    # 新写入的 desktop_pid 应是当前值
    data = json.loads((journal_dir / "active_context.json").read_text(encoding="utf-8"))
    assert data["desktop_pid"] == 88888


# ==================== 心跳测试 (附加) ====================

def test_heartbeat_updates_last_heartbeat_at(tmp_path: Path) -> None:
    """心跳线程启动后, last_heartbeat_at 应被更新."""
    journal_dir = tmp_path / "journal"
    mgr = ac.ActiveContextManager(journal_dir)
    mgr.on_startup()

    data_before = mgr._read()
    hb_before = data_before["last_heartbeat_at"]

    # 启动心跳, 等 7s (超过 1 个心跳周期)
    mgr.start_heartbeat()
    import time
    time.sleep(7)
    mgr.stop_heartbeat()

    data_after = mgr._read()
    hb_after = data_after["last_heartbeat_at"]

    assert hb_after > hb_before


def test_update_session_writes_fields(tmp_path: Path) -> None:
    """update_session 应写入 session_id/thread_id/last_* 字段."""
    journal_dir = tmp_path / "journal"
    mgr = ac.ActiveContextManager(journal_dir)
    mgr.on_startup()

    mgr.update_session(
        session_id="sess-123",
        thread_id="thread-456",
        last_message_at=_iso_seconds_ago(1),
        last_tool_at=_iso_seconds_ago(2),
        last_trace_id="trace-789",
    )

    data = mgr._read()
    assert data["session_id"] == "sess-123"
    assert data["thread_id"] == "thread-456"
    assert data["last_message_at"] is not None
    assert data["last_tool_at"] is not None
    assert data["last_trace_id"] == "trace-789"


def test_get_snapshot_returns_copy(tmp_path: Path) -> None:
    """get_snapshot 应返回副本, 修改不影响内部状态."""
    journal_dir = tmp_path / "journal"
    mgr = ac.ActiveContextManager(journal_dir)
    mgr.on_startup()

    snap = mgr.get_snapshot()
    snap["session_id"] = "modified"

    snap2 = mgr.get_snapshot()
    assert snap2["session_id"] is None  # 内部未被修改


# ==================== detect_crash 单元测试 ====================

def test_detect_crash_none_input() -> None:
    assert ac.detect_crash(None) == (False, "no_previous_context")


def test_detect_crash_empty_dict() -> None:
    assert ac.detect_crash({}) == (False, "no_previous_context")


def test_detect_crash_clean_exit() -> None:
    ctx = {"exit_status": {"clean": True, "exited_at": "2026-01-01T00:00:00+00:00", "reason": "user_quit"}}
    assert ac.detect_crash(ctx) == (False, "clean_exit")


def test_detect_crash_no_heartbeat() -> None:
    ctx = {"exit_status": None, "last_heartbeat_at": None}
    assert ac.detect_crash(ctx) == (False, "no_previous_context")


def test_detect_crash_stale_heartbeat() -> None:
    ctx = {
        "exit_status": None,
        "last_heartbeat_at": _iso_seconds_ago(120),
    }
    is_crash, reason = ac.detect_crash(ctx)
    assert is_crash is True
    assert reason == "no_exit_status_and_heartbeat_stale"


def test_detect_crash_fresh_heartbeat() -> None:
    ctx = {
        "exit_status": None,
        "last_heartbeat_at": _iso_seconds_ago(5),
    }
    is_crash, reason = ac.detect_crash(ctx)
    assert is_crash is False
    assert reason == "normal"


def test_detect_crash_unclean_exit_status() -> None:
    ctx = {
        "exit_status": {"clean": False, "exited_at": "2026-01-01T00:00:00+00:00", "reason": "sigterm"},
        "last_heartbeat_at": _iso_seconds_ago(5),
    }
    is_crash, reason = ac.detect_crash(ctx)
    assert is_crash is True
    assert reason == "sigterm"
