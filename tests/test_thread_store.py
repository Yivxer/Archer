import json
from pathlib import Path

import pytest

from core.thread_store import (
    add_session_to_thread,
    create_thread,
    read_threads,
    update_thread,
    write_threads,
)


def test_thread_store_handles_bad_json(tmp_path):
    path = tmp_path / "conversation_threads.json"
    path.write_text("{bad json", encoding="utf-8")

    assert read_threads(path) == []


@pytest.mark.parametrize("explicit_db", [False, True])
def test_thread_read_restores_context_without_changing_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, explicit_db: bool,
) -> None:
    import core.thread_store as threads
    import memory.thread_context as context

    index, db = tmp_path / "threads.json", tmp_path / "context.db"
    monkeypatch.setattr(threads, "THREADS_PATH", index)
    monkeypatch.setattr(threads, "DEFAULT_THREADS_PATH", index)
    monkeypatch.setattr(context, "memory_db_path", lambda: db)
    messages = [
        {"role": "user", "content": "目标：检查青禾备份"},
        {"role": "assistant", "content": "决定：先核对配置"},
        {"role": "user", "content": "不对，纠正为只看本机"},
        {"role": "user", "content": "接下来继续检查，尚未完成"},
    ]
    created = threads.create_thread(messages, "synthetic-session")
    before = index.read_bytes()
    restored = (
        threads.read_threads(index, db_path=db)[0]
        if explicit_db else threads.get_thread(created["id"])
    )
    assert restored is not None
    assert restored["contextState"] == created["contextState"]
    assert restored["lastStop"] == messages[-1]["content"]
    assert index.read_bytes() == before


def test_explicit_isolated_thread_index_does_not_read_default_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.thread_store as threads
    import memory.thread_context as context

    def forbidden_read(*args: object, **kwargs: object) -> None:
        raise AssertionError("explicit isolated index must not read the default DB")

    monkeypatch.setattr(context, "get_thread_context", forbidden_read)
    index = tmp_path / "isolated-threads.json"
    created = threads.create_thread(
        [{"role": "user", "content": "隔离会话"}], "isolated-session", index,
    )
    restored = threads.get_thread(created["id"], index)
    assert restored == created
    assert "contextState" not in restored


def test_thread_store_creates_updates_and_appends_sessions(tmp_path):
    path = tmp_path / "conversation_threads.json"
    messages = [
        {"role": "user", "content": "上传文章到枫弋札记"},
        {"role": "assistant", "content": "已经发布并验证。"},
    ]

    thread = create_thread(messages, "20260702_120000", path)
    updated = update_thread(thread["id"], {"title": "枫弋札记发布"}, path)
    appended = add_session_to_thread(
        thread["id"],
        "20260702_120500",
        messages + [{"role": "user", "content": "继续检查部署"}],
        path,
    )

    assert updated is not None
    assert updated["title"] == "枫弋札记发布"
    assert appended is not None
    assert appended["sessionIds"] == ["20260702_120000", "20260702_120500"]
    assert "继续检查部署" in appended["summary"]
    assert json.loads(path.read_text(encoding="utf-8"))[0]["id"] == thread["id"]


def test_conversation_thread_summary_uses_first_and_latest_turn_from_full_history(tmp_path):
    path = tmp_path / "conversation_threads.json"
    history = [
        {"role": "user", "content": "第一轮：讨论发布流程"},
        {"role": "assistant", "content": "第一轮结论"},
        {"role": "user", "content": "第二轮：继续检查审批"},
        {"role": "assistant", "content": "第二轮结论"},
        {"role": "user", "content": "第三轮：确认 Trace 是否闭环"},
        {"role": "assistant", "content": "第三轮结论"},
    ]

    thread = create_thread(history, path=path)

    assert thread["title"] == "第一轮：讨论发布流程"
    assert "目标：第一轮：讨论发布流程" in thread["summary"]
    assert "最近问题：第三轮：确认 Trace 是否闭环" in thread["summary"]
    assert "最近结论：第三轮结论" in thread["summary"]


def test_thread_store_normalizes_bad_records(tmp_path):
    path = tmp_path / "conversation_threads.json"

    normalized = write_threads([
        {"id": "../bad", "title": "bad"},
        {"id": "thread-ok", "title": " 正常话题 ", "sessionIds": ["s1", "s1", ""]},
    ], path)

    assert normalized == [{
        "id": "thread-ok",
        "title": "正常话题",
        "summary": "",
        "createdAt": "",
        "updatedAt": "",
        "sessionIds": ["s1"],
        "archived": False,
    }]
