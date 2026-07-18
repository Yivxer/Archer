from __future__ import annotations

from pathlib import Path

from memory.migrations import LATEST_SCHEMA_VERSION, run_migrations
from memory.thread_context import (
    format_context_capsule,
    get_thread_context,
    register_thread_session,
    update_thread_context,
)


def _messages(count: int) -> list[dict]:
    messages = [{"role": "user", "content": "目标是完成 Archer 记忆连续性"}]
    for index in range(count - 1):
        role = "assistant" if index % 2 == 0 else "user"
        content = f"第 {index} 条"
        if index == count - 2:
            content = "接下来继续 J8 验收"
        messages.append({"role": role, "content": content})
    messages[-1] = {"role": "user", "content": "接下来继续 J8 验收"}
    return messages


def test_schema_v3_and_context_capsule_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    assert run_migrations(db_path).version == LATEST_SCHEMA_VERSION == 4
    saved = update_thread_context("thread-1", _messages(40), db_path=db_path)
    register_thread_session("thread-1", "session-1", db_path=db_path)
    loaded = get_thread_context("thread-1", db_path=db_path)
    assert loaded == saved
    assert loaded["contextState"]["goal"].startswith("目标是")
    assert "J8" in loaded["lastStop"]
    assert "线程情境胶囊" in format_context_capsule(loaded)


def test_summary_version_advances_every_twelve_long_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    first = update_thread_context("thread-1", _messages(40), db_path=db_path)
    unchanged = update_thread_context("thread-1", _messages(45), db_path=db_path)
    advanced = update_thread_context("thread-1", _messages(52), db_path=db_path)
    assert unchanged["summaryVersion"] == first["summaryVersion"]
    assert advanced["summaryVersion"] == first["summaryVersion"] + 1
