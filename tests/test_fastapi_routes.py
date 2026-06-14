"""P5.8 — FastAPI route tests."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

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


def test_unknown_route_returns_404(client):
    response = client.get("/missing-route", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
