"""Active context journaling for crash detection and runtime self-awareness.

L0 of Part 9 稳定性框架. See [[Archer 稳定性框架]] §三 L0.1 详细契约.

设计要点:
- 单写者: 只有 Python API 进程写 active_context.json
- 原子写: 写 .tmp 再 os.replace(), 避免读到半截 JSON
- 文件锁: fcntl.flock 防御多 API 进程
- Desktop 只读: 通过 GET /active-context API 读
- 崩溃判定: last_heartbeat_at 30s 未更新且无 exit_status = 崩溃
"""
from __future__ import annotations

import json
import os
import fcntl
import logging
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
HEARTBEAT_INTERVAL_SECONDS = 5
CRASH_DETECTION_WINDOW_SECONDS = 30
MAX_CRASH_REPORTS = 5
CONSECUTIVE_CRASH_THRESHOLD = 3

_DEFAULT_JOURNAL_DIR = Path(__file__).resolve().parent.parent / "journal"
_ACTIVE_CONTEXT_FILENAME = "active_context.json"
_CRASH_COUNT_FILENAME = "crash_count.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _default_active_context(pid: int, desktop_pid: int | None = None) -> dict[str, Any]:
    now = _now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "pid": pid,
        "started_at": now,
        "last_heartbeat_at": now,
        "exit_status": None,
        "session_id": None,
        "thread_id": None,
        "last_message_at": None,
        "last_tool_at": None,
        "last_trace_id": None,
        "desktop_pid": desktop_pid,
    }


def _ensure_journal_dir(journal_dir: Path) -> None:
    journal_dir.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """原子写 JSON: 先写 .tmp 再 os.replace()."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)


def _read_json_safe(path: Path) -> dict[str, Any] | None:
    """读 JSON, 任何异常返回 None (不崩溃)."""
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.warning("active_context: failed to read %s: %s", path, exc)
        return None


def _flock_write(path: Path, data: dict[str, Any]) -> None:
    """带 flock 的原子写."""
    _ensure_journal_dir(path.parent)
    with open(path, "w", encoding="utf-8") as fp:
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
        except (OSError, IOError):
            # flock 在某些文件系统 (NFS) 可能失败, 降级为普通写
            logger.debug("active_context: flock unavailable, writing without lock")
        _atomic_write_json(path, data)
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        except (OSError, IOError):
            pass


def detect_crash(active_context: dict[str, Any] | None) -> tuple[bool, str]:
    """崩溃判定算法. 启动时调用.

    Returns:
        (is_crash, reason)
        - (False, "no_previous_context"): 首次启动, 无历史
        - (False, "clean_exit"): 上次正常退出
        - (False, "normal"): 上次退出状态未知但心跳新鲜
        - (True, "no_exit_status_and_heartbeat_stale"): SIGKILL/断电
        - (True, "<reason>"): 上次异常退出, reason 来自 exit_status
    """
    if not active_context:
        return False, "no_previous_context"

    exit_status = active_context.get("exit_status")
    if isinstance(exit_status, dict) and exit_status.get("clean") is True:
        return False, "clean_exit"

    last_heartbeat = active_context.get("last_heartbeat_at")
    if not last_heartbeat:
        return False, "no_previous_context"

    heartbeat_dt = _parse_iso(last_heartbeat)
    if heartbeat_dt is None:
        return False, "no_previous_context"

    now = datetime.now(timezone.utc)
    # 心跳可能带不同时区, 统一转 UTC 比较
    if heartbeat_dt.tzinfo is None:
        heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)
    gap_seconds = (now - heartbeat_dt).total_seconds()

    if exit_status is None and gap_seconds > CRASH_DETECTION_WINDOW_SECONDS:
        return True, "no_exit_status_and_heartbeat_stale"
    if isinstance(exit_status, dict) and exit_status.get("clean") is False:
        return True, str(exit_status.get("reason", "unclean_exit"))
    return False, "normal"


# ==================== Crash count ====================

def _read_crash_count(journal_dir: Path) -> int:
    """读近 7 天崩溃次数."""
    data = _read_json_safe(journal_dir / _CRASH_COUNT_FILENAME)
    if not data:
        return 0
    now = datetime.now(timezone.utc)
    crashes = data.get("crashes", [])
    if not isinstance(crashes, list):
        return 0
    # 只统计近 7 天
    recent = []
    for entry in crashes:
        if not isinstance(entry, dict):
            continue
        ts = _parse_iso(entry.get("timestamp"))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if (now - ts).days <= 7:
            recent.append(entry)
    return len(recent)


def _record_crash(journal_dir: Path, reason: str) -> int:
    """记录一次崩溃, 返回当前近 7 天崩溃次数."""
    path = journal_dir / _CRASH_COUNT_FILENAME
    data = _read_json_safe(path) or {"crashes": []}
    if not isinstance(data.get("crashes"), list):
        data["crashes"] = []
    data["crashes"].append({"timestamp": _now_iso(), "reason": reason})
    # 保留最近 MAX_CRASH_REPORTS * 4 条 (足够 7 天统计)
    data["crashes"] = data["crashes"][-(MAX_CRASH_REPORTS * 4):]
    _flock_write(path, data)
    return _read_crash_count(journal_dir)


def _reset_crash_count(journal_dir: Path) -> None:
    """重置崩溃计数 (用户点'重置 journal'时调用)."""
    path = journal_dir / _CRASH_COUNT_FILENAME
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


# ==================== ActiveContext manager ====================

class ActiveContextManager:
    """管理 active_context.json 生命周期.

    用法:
        mgr = ActiveContextManager(journal_dir)
        mgr.on_startup(desktop_pid=67890)  # 启动时调用, 返回 (is_crash, reason, crash_count)
        mgr.start_heartbeat()               # 启动心跳线程
        mgr.update_session(session_id, thread_id)  # 每轮对话后调用
        mgr.on_shutdown(clean=True, reason="user_quit")  # 退出时调用
    """

    def __init__(self, journal_dir: Path | None = None) -> None:
        self.journal_dir = journal_dir or _DEFAULT_JOURNAL_DIR
        self.path = self.journal_dir / _ACTIVE_CONTEXT_FILENAME
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()
        self._lock = threading.Lock()
        self._current: dict[str, Any] = {}

    def _read(self) -> dict[str, Any] | None:
        return _read_json_safe(self.path)

    def _write(self, data: dict[str, Any]) -> None:
        _flock_write(self.path, data)

    def on_startup(self, desktop_pid: int | None = None) -> tuple[bool, str, int]:
        """启动时调用. 返回 (is_crash, reason, crash_count)."""
        _ensure_journal_dir(self.journal_dir)
        previous = self._read()
        is_crash, reason = detect_crash(previous)
        crash_count = _read_crash_count(self.journal_dir)
        if is_crash:
            crash_count = _record_crash(self.journal_dir, reason)
            logger.warning("active_context: crash detected, reason=%s, count=%d", reason, crash_count)

        self._current = _default_active_context(os.getpid(), desktop_pid)
        self._write(self._current)
        return is_crash, reason, crash_count

    def start_heartbeat(self) -> None:
        """启动后台心跳线程, 每 5s 更新 last_heartbeat_at."""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="active-context-heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            with self._lock:
                if not self._current:
                    continue
                self._current["last_heartbeat_at"] = _now_iso()
                try:
                    self._write(self._current)
                except (OSError, IOError) as exc:
                    logger.warning("active_context: heartbeat write failed: %s", exc)

    def update_session(
        self,
        session_id: str | None = None,
        thread_id: str | None = None,
        last_message_at: str | None = None,
        last_tool_at: str | None = None,
        last_trace_id: str | None = None,
    ) -> None:
        """更新当前 session 信息. 每轮对话后调用."""
        with self._lock:
            if not self._current:
                return
            if session_id is not None:
                self._current["session_id"] = session_id
            if thread_id is not None:
                self._current["thread_id"] = thread_id
            if last_message_at is not None:
                self._current["last_message_at"] = last_message_at
            if last_tool_at is not None:
                self._current["last_tool_at"] = last_tool_at
            if last_trace_id is not None:
                self._current["last_trace_id"] = last_trace_id
            self._current["last_heartbeat_at"] = _now_iso()
            try:
                self._write(self._current)
            except (OSError, IOError) as exc:
                logger.warning("active_context: update_session write failed: %s", exc)

    def on_shutdown(self, clean: bool, reason: str) -> None:
        """退出时调用. 写 exit_status."""
        self.stop_heartbeat()
        with self._lock:
            if not self._current:
                return
            self._current["exit_status"] = {
                "clean": clean,
                "exited_at": _now_iso(),
                "reason": reason,
            }
            try:
                self._write(self._current)
            except (OSError, IOError) as exc:
                logger.warning("active_context: on_shutdown write failed: %s", exc)

    def get_snapshot(self) -> dict[str, Any]:
        """返回当前 active_context 副本 (供 API 读)."""
        with self._lock:
            return dict(self._current) if self._current else {}


# ==================== SIGTERM handler ====================

_global_manager: ActiveContextManager | None = None


def install_sigterm_handler(mgr: ActiveContextManager) -> None:
    """安装 SIGTERM handler, 被 kill 时写 exit_status.clean=False.

    只在 main thread 安装 (signal 模块限制). 非 main thread 调用时静默跳过.
    """
    global _global_manager
    _global_manager = mgr

    # 检查是否在 main thread (signal 只能在 main thread 用)
    if threading.current_thread() is not threading.main_thread():
        logger.debug("active_context: SIGTERM handler skipped (not in main thread)")
        return

    def _handler(signum: int, frame: Any) -> None:
        if _global_manager is not None:
            try:
                _global_manager.on_shutdown(clean=False, reason="sigterm")
            except Exception as exc:
                logger.warning("active_context: SIGTERM handler failed: %s", exc)
        # 默认行为: 重新抛出 SIGTERM 让进程退出
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError) as exc:
        logger.warning("active_context: failed to install SIGTERM handler: %s", exc)


def reset_journal(journal_dir: Path | None = None) -> None:
    """重置 journal 目录 (用户点'重置 journal'时调用)."""
    jdir = journal_dir or _DEFAULT_JOURNAL_DIR
    _reset_crash_count(jdir)
    try:
        (jdir / _ACTIVE_CONTEXT_FILENAME).unlink(missing_ok=True)
    except OSError:
        pass
