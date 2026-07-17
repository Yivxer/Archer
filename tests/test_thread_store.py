import json

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
