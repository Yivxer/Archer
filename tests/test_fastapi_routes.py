"""P5.8 — FastAPI route tests."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.active_context import ActiveContextManager
from terminal.api.fastapi_app import create_app


@pytest.fixture
def client():
    app = create_app("test-token")
    with TestClient(app) as test_client:
        yield test_client


def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_ready_is_public(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "ready": True, "runtime": "fastapi"}


def test_active_context_startup_does_not_override_sigterm_handler(tmp_path, monkeypatch):
    """Desktop normal quit sends SIGTERM; uvicorn should handle it as graceful shutdown."""
    import core.active_context as active_context

    calls: list[ActiveContextManager] = []

    def _unexpected_install(mgr: ActiveContextManager) -> None:
        calls.append(mgr)
        raise AssertionError("startup must not install a custom SIGTERM handler")

    monkeypatch.setattr(active_context, "install_sigterm_handler", _unexpected_install)

    mgr = ActiveContextManager(Path(tmp_path) / "journal")
    app = create_app("test-token", active_context_mgr=mgr)

    with TestClient(app) as test_client:
        response = test_client.get("/active-context", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert calls == []


def test_health_ready_and_status_are_not_rate_limited(client, monkeypatch):
    monkeypatch.setattr("terminal.api.fastapi_app.check_rate_limit", lambda _client_ip, _path: False)

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/status", headers={"Authorization": "Bearer test-token"}).status_code == 200


def test_authenticated_get_reads_are_not_rate_limited(client, monkeypatch):
    monkeypatch.setattr("terminal.api.fastapi_app.check_rate_limit", lambda _client_ip, _path: False)

    response = client.get("/config/doctor", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200


def test_status_requires_bearer_token(client):
    assert client.get("/status").status_code == 401
    response = client.get("/status", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    assert "adapter" in response.json()


def test_openapi_docs_available(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Archer Desktop API"


def test_post_jobs_requires_object_body(client):
    response = client.post(
        "/jobs",
        headers={"Authorization": "Bearer test-token"},
        json={"title": "", "prompt": ""},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"
    assert "message" in response.json()
    assert "detail" in response.json()


def test_post_jobs_creates_job(tmp_path, monkeypatch, client):
    from terminal.api import _routes as routes

    routes.BACKGROUND_JOBS.clear()
    routes.BACKGROUND_JOBS_LOADED = False
    routes.BACKGROUND_JOBS_PATH = tmp_path / "jobs.json"

    response = client.post(
        "/jobs",
        headers={"Authorization": "Bearer test-token"},
        json={
            "title": "FastAPI job",
            "kind": "analysis",
            "prompt": "run analysis",
            "autoStart": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["job"]["title"] == "FastAPI job"


def test_chat_stream_returns_sse(client, monkeypatch):
    monkeypatch.setattr(
        "terminal.api.fastapi_app._iter_chat_chunks",
        lambda *args, **kwargs: iter([{"type": "token", "text": "hi"}]),
    )
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda history: None)

    with client.stream(
        "POST",
        "/chat/stream",
        headers={"Authorization": "Bearer test-token"},
        json={"messages": [{"role": "user", "content": "hello"}]},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
        assert "data:" in body
        assert "hi" in body


def test_chat_stream_returns_busy_when_concurrency_slot_is_full(client, monkeypatch):
    monkeypatch.setattr(
        "terminal.api.fastapi_app._iter_chat_chunks",
        lambda *args, **kwargs: iter([{"type": "token", "text": "should-not-run"}]),
    )
    semaphore = client.app.state.chat_stream_semaphore
    assert semaphore.acquire(blocking=False) is True
    try:
        response = client.post(
            "/chat/stream",
            headers={"Authorization": "Bearer test-token"},
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
    finally:
        semaphore.release()

    assert response.status_code == 429
    assert response.json()["error"] == "chat_busy"


def test_chat_stream_events_release_slot_when_client_closes(monkeypatch):
    from terminal.api.fastapi_app import _chat_stream_events

    def endless_chunks(*args, **kwargs):
        yield {"type": "token", "text": "first"}
        while True:
            yield {"type": "statusEvent", "statusEvent": {"id": "still-running"}}

    monkeypatch.setattr("terminal.api.fastapi_app._iter_chat_chunks", endless_chunks)
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda history: None)

    semaphore = threading.BoundedSemaphore(1)
    assert semaphore.acquire(blocking=False) is True
    stream = _chat_stream_events(
        {"messages": [{"role": "user", "content": "hello"}]},
        release_slot=semaphore.release,
    )
    assert "first" in next(stream)
    stream.close()

    assert semaphore.acquire(blocking=False) is True
    semaphore.release()


def test_chat_stream_events_release_slot_on_generator_error(monkeypatch):
    from terminal.api.fastapi_app import _chat_stream_events

    def failing_chunks(*args, **kwargs):
        yield {"type": "token", "text": "first"}
        raise RuntimeError("boom")

    monkeypatch.setattr("terminal.api.fastapi_app._iter_chat_chunks", failing_chunks)
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda history: None)

    semaphore = threading.BoundedSemaphore(1)
    assert semaphore.acquire(blocking=False) is True
    stream = _chat_stream_events(
        {"messages": [{"role": "user", "content": "hello"}]},
        release_slot=semaphore.release,
    )
    assert "first" in next(stream)
    with pytest.raises(RuntimeError, match="boom"):
        next(stream)

    assert semaphore.acquire(blocking=False) is True
    semaphore.release()


def test_websocket_chat_streams_events(client, monkeypatch):
    monkeypatch.setattr(
        "terminal.api.fastapi_app._iter_chat_chunks",
        lambda *args, **kwargs: iter([{"type": "token", "text": "ws"}]),
    )
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda history: None)

    with client.websocket_connect("/ws/chat?token=test-token") as websocket:
        websocket.send_json({"messages": [{"role": "user", "content": "hello"}]})
        event = websocket.receive_json()
        assert event["type"] == "token"
        assert event["text"] == "ws"


def test_websocket_rejects_missing_token(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/chat"):
            pass


def test_wildcard_get_dispatch_preserves_query(client, monkeypatch):
    captured = {}

    def fake_payload_get(path, runtime_context=None):
        captured["path"] = path
        captured["runtime_context"] = runtime_context
        return 200, {"ok": True, "path": path}

    monkeypatch.setattr("terminal.api.fastapi_app.payload_get", fake_payload_get)

    response = client.get(
        "/memory?include_rejected=true",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "path": "/memory?include_rejected=true"}
    assert captured["path"] == "/memory?include_rejected=true"
    assert captured["runtime_context"] is client.app.state.runtime_context


def test_wildcard_get_dispatch_runs_in_threadpool(client, monkeypatch):
    calls = []

    async def fake_run_in_threadpool(fn, *args, **kwargs):
        calls.append((fn.__name__, args))
        return fn(*args, **kwargs)

    monkeypatch.setattr("terminal.api.fastapi_app.run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(
        "terminal.api.fastapi_app.payload_get",
        lambda path, runtime_context=None: (200, {"path": path}),
    )

    response = client.get("/memory", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json() == {"path": "/memory"}
    assert calls == [("_dispatch_get", ("/memory", client.app.state.runtime_context))]


def test_wildcard_post_dispatch_preserves_body(client, monkeypatch):
    captured = {}

    def fake_payload_post(path, body, runtime_context=None):
        captured["path"] = path
        captured["body"] = body
        captured["runtime_context"] = runtime_context
        return 200, {"ok": True}

    monkeypatch.setattr("terminal.api.fastapi_app.payload_post", fake_payload_post)

    response = client.post(
        "/settings/validate",
        headers={"Authorization": "Bearer test-token"},
        json={"apiKey": "sk-test"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured == {
        "path": "/settings/validate",
        "body": {"apiKey": "sk-test"},
        "runtime_context": client.app.state.runtime_context,
    }


def test_wildcard_post_dispatch_runs_in_threadpool(client, monkeypatch):
    calls = []

    async def fake_run_in_threadpool(fn, *args, **kwargs):
        calls.append((fn.__name__, args))
        return fn(*args, **kwargs)

    monkeypatch.setattr("terminal.api.fastapi_app.run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(
        "terminal.api.fastapi_app.payload_post",
        lambda path, body, runtime_context=None: (200, {"path": path, "body": body}),
    )

    response = client.post(
        "/settings/validate",
        headers={"Authorization": "Bearer test-token"},
        json={"apiKey": "sk-test"},
    )

    assert response.status_code == 200
    assert response.json() == {"path": "/settings/validate", "body": {"apiKey": "sk-test"}}
    assert calls == [(
        "_dispatch_post",
        ("/settings/validate", {"apiKey": "sk-test"}, client.app.state.runtime_context),
    )]


def test_unknown_route_returns_404(client):
    response = client.get("/missing-route", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    assert response.json()["message"] == "not_found"
    assert response.json()["detail"] == "/missing-route"
