"""Session save must not invent a thread for an unknown threadId."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.runtime_context import create_runtime_context
from core.thread_store import read_threads
from terminal.api.fastapi_app import create_app
from terminal.api.session_routes import session_meta_from_payload

MESSAGES = [
    {"role": "user", "content": "synthetic user turn"},
    {"role": "assistant", "content": "synthetic assistant turn"},
]
AUTH = {"Authorization": "Bearer test-token"}


def test_session_route_metadata_filters_invalid_ids_and_truncates_label():
    meta = session_meta_from_payload({
        "expertId": "expert_1",
        "expertLabel": "x" * 100,
        "threadId": "../invalid",
        "modeId": "writer",
        "modeLabel": "写作",
    })

    assert meta == {
        "expertId": "expert_1",
        "expertLabel": "x" * 64,
        "modeId": "writer",
        "modeLabel": "写作",
    }


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr("core.session.SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr("core.thread_store.THREADS_PATH", tmp_path / "threads.json")
    app = create_app(
        "test-token",
        runtime_context=create_runtime_context(db_path=tmp_path / "archer.db"),
    )
    return TestClient(app)


def _thread_ids() -> list[str]:
    return [str(thread["id"]) for thread in read_threads()]


def test_unknown_thread_id_on_session_save_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with _isolate(monkeypatch, tmp_path) as client:
        unknown = client.post(
            "/sessions",
            headers=AUTH,
            json={"messages": MESSAGES, "threadId": "thread-missing"},
        )
        invalid = client.post(
            "/sessions",
            headers=AUTH,
            json={"messages": MESSAGES, "threadId": "../invalid"},
        )

    assert unknown.status_code == 404
    assert unknown.json()["error"] == "not_found"
    assert unknown.json()["message"] == "thread not found: thread-missing"
    assert invalid.status_code == 400
    assert invalid.json()["error"] == "validation_error"
    assert invalid.json()["message"] == "invalid threadId"
    assert _thread_ids() == []
    assert list((tmp_path / "sessions").glob("*.json")) == []
    assert not (tmp_path / "threads.json").exists()


def test_known_thread_id_links_saved_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with _isolate(monkeypatch, tmp_path) as client:
        created = client.post(
            "/threads",
            headers=AUTH,
            json={"messages": MESSAGES, "title": "Known topic"},
        )
        assert created.status_code == 200
        thread_id = created.json()["id"]
        before = _thread_ids()
        saved = client.post(
            "/sessions",
            headers=AUTH,
            json={"messages": MESSAGES, "threadId": thread_id},
        )

    assert saved.status_code == 200
    body = saved.json()
    assert body["threadId"] == thread_id
    assert _thread_ids() == before
    linked = next(thread for thread in read_threads() if thread["id"] == thread_id)
    assert body["id"] in linked["sessionIds"]


def test_intentional_thread_create_still_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with _isolate(monkeypatch, tmp_path) as client:
        saved = client.post("/sessions", headers=AUTH, json={"messages": MESSAGES})
        explicit = client.post(
            "/threads",
            headers=AUTH,
            json={"messages": MESSAGES, "title": "Intentional topic"},
        )

    assert saved.status_code == 200
    assert explicit.status_code == 200
    saved_thread = saved.json()["threadId"]
    assert saved_thread.startswith("thread-")
    assert explicit.json()["title"] == "Intentional topic"
    assert explicit.json()["id"] != saved_thread
    assert set(_thread_ids()) == {saved_thread, explicit.json()["id"]}
