from __future__ import annotations

from pathlib import Path

import core.thread_store as thread_store
from terminal.api.session_routes import create_thread, save_session


def test_journey_session_and_thread_do_not_touch_user_index(tmp_path: Path, monkeypatch) -> None:
    user_index = tmp_path / "conversation_threads.json"
    monkeypatch.setattr(thread_store, "THREADS_PATH", user_index)
    payload = {
        "environment": "test",
        "runId": "isolation-test",
        "messages": [
            {"role": "user", "content": "Journey test"},
            {"role": "assistant", "content": "ok"},
        ],
    }
    saved = save_session(payload)
    created = create_thread({**payload, "title": "Journey isolated"})
    assert "archer-journey-isolation-test" in saved["path"]
    assert created["title"] == "Journey isolated"
    assert not user_index.exists()
