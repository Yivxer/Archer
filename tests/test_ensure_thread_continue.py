"""Ensure a missing topic index entry before the existing continue save.

Continue still uses POST /sessions with that threadId. This does not backfill
every orphan, and it does not read session message files.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.runtime_context import create_runtime_context
from core.thread_store import ensure_thread, read_threads
from terminal.api.fastapi_app import create_app

MESSAGES = [
    {"role": "user", "content": "synthetic user turn"},
    {"role": "assistant", "content": "synthetic assistant turn"},
]
AUTH = {"Authorization": "Bearer test-token"}
SOURCE_SESSION = "20260101_000000"
TOPIC_TITLE = "Synthetic topic"


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr("core.session.SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr("core.thread_store.THREADS_PATH", tmp_path / "threads.json")
    app = create_app(
        "test-token",
        runtime_context=create_runtime_context(db_path=tmp_path / "archer.db"),
    )
    return TestClient(app)


def _index_text(tmp_path: Path) -> str:
    path = tmp_path / "threads.json"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_missing_index_ensure_then_continue_save_keeps_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
):
    thread_id = "thread-missing"
    with _isolate(monkeypatch, tmp_path) as client:
        assert client.get(f"/threads/{thread_id}", headers=AUTH).status_code == 404
        with caplog.at_level(logging.DEBUG):
            ensured = client.post(
                f"/threads/{thread_id}/ensure",
                headers=AUTH,
                json={"title": TOPIC_TITLE, "sessionId": SOURCE_SESSION},
            )
        assert ensured.status_code == 200
        body = ensured.json()
        assert body["id"] == thread_id
        assert body["title"] == TOPIC_TITLE
        assert body["summary"] == ""
        assert body["sessionIds"] == [SOURCE_SESSION]
        assert "synthetic user turn" not in _index_text(tmp_path)
        assert "synthetic assistant turn" not in _index_text(tmp_path)

        saved = client.post(
            "/sessions",
            headers=AUTH,
            json={"messages": MESSAGES, "threadId": thread_id},
        )

    assert saved.status_code == 200
    saved_body = saved.json()
    assert saved_body["threadId"] == thread_id
    threads = read_threads()
    assert [thread["id"] for thread in threads] == [thread_id]
    assert SOURCE_SESSION in threads[0]["sessionIds"]
    assert saved_body["id"] in threads[0]["sessionIds"]
    assert TOPIC_TITLE not in caplog.text
    assert "synthetic user turn" not in caplog.text
    assert "synthetic assistant turn" not in caplog.text


def test_invalid_thread_id_fails_without_index_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
):
    with _isolate(monkeypatch, tmp_path) as client:
        with caplog.at_level(logging.DEBUG):
            invalid = client.post(
                "/threads/bad.id/ensure",
                headers=AUTH,
                json={"title": TOPIC_TITLE, "sessionId": SOURCE_SESSION},
            )
    assert invalid.status_code == 400
    assert invalid.json()["error"] == "validation_error"
    assert invalid.json()["message"] == "invalid threadId"
    assert read_threads() == []
    assert not (tmp_path / "threads.json").exists()
    assert list((tmp_path / "sessions").glob("*.json")) == []
    assert TOPIC_TITLE not in caplog.text


def test_invalid_session_id_is_not_stored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    thread_id = "thread-missing"
    with _isolate(monkeypatch, tmp_path) as client:
        ensured = client.post(
            f"/threads/{thread_id}/ensure",
            headers=AUTH,
            json={"title": TOPIC_TITLE, "sessionId": "../not-a-session"},
        )
    assert ensured.status_code == 200
    assert ensured.json()["id"] == thread_id
    assert ensured.json()["sessionIds"] == []
    assert "../not-a-session" not in _index_text(tmp_path)


def test_known_thread_is_unchanged_by_ensure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with _isolate(monkeypatch, tmp_path) as client:
        created = client.post(
            "/threads",
            headers=AUTH,
            json={"messages": MESSAGES, "title": TOPIC_TITLE},
        )
        assert created.status_code == 200
        thread_id = created.json()["id"]
        before = (tmp_path / "threads.json").read_bytes()
        ensured = client.post(
            f"/threads/{thread_id}/ensure",
            headers=AUTH,
            json={"title": "Different title", "sessionId": "20260102_000000"},
        )
        after = (tmp_path / "threads.json").read_bytes()

    assert ensured.status_code == 200
    assert after == before
    stored = next(thread for thread in read_threads() if thread["id"] == thread_id)
    assert stored["title"] == TOPIC_TITLE
    assert stored["sessionIds"] == []
    assert "Different title" not in stored["summary"]


def test_ensure_does_not_read_session_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ensure must not read session files")

    monkeypatch.setattr("core.session_store.read_session_file", forbidden)
    index = tmp_path / "threads.json"
    stored = ensure_thread("thread-missing", title=TOPIC_TITLE, session_id=SOURCE_SESSION, path=index)
    assert stored is not None
    assert stored["id"] == "thread-missing"
    assert stored["summary"] == ""
    assert "synthetic user turn" not in index.read_text(encoding="utf-8")
    assert ensure_thread("../invalid", title=TOPIC_TITLE, path=index) is None
    assert [thread["id"] for thread in read_threads(index)] == ["thread-missing"]
