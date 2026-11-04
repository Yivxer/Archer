"""P5.8 — FastAPI route tests."""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from core.active_context import ActiveContextManager
from core.runtime_context import create_runtime_context
from terminal.api.fastapi_app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(
        "test-token",
        runtime_context=create_runtime_context(db_path=tmp_path / "archer.db"),
    )
    with TestClient(app) as test_client:
        yield test_client


def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["contractVersion"] == 1


def test_ready_is_public(client):
    response = client.get("/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["contractVersion"] == 1
    assert payload["ok"] is True
    assert payload["ready"] is True
    assert payload["runtime"] == "fastapi"
    assert payload["persona"]["ready"] is True
    assert payload["persona"]["missing"] == []


def test_active_context_startup_does_not_override_sigterm_handler(tmp_path, monkeypatch):
    """Desktop normal quit sends SIGTERM; uvicorn should handle it as graceful shutdown."""
    import core.active_context as active_context

    calls: list[ActiveContextManager] = []

    def _unexpected_install(mgr: ActiveContextManager) -> None:
        calls.append(mgr)
        raise AssertionError("startup must not install a custom SIGTERM handler")

    monkeypatch.setattr(active_context, "install_sigterm_handler", _unexpected_install)

    mgr = ActiveContextManager(Path(tmp_path) / "journal")
    app = create_app(
        "test-token",
        active_context_mgr=mgr,
        runtime_context=create_runtime_context(db_path=tmp_path / "archer.db"),
    )

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


def test_list_response_uses_contract_envelope(client):
    response = client.get(
        "/sessions",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json()["contractVersion"] == 1
    assert isinstance(response.json()["data"], list)


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
    from terminal.api import job_routes as jobs

    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    jobs.BACKGROUND_JOBS_PATH = tmp_path / "jobs.json"

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
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda history, **kwargs: None)

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
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda history, **kwargs: None)

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
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda history, **kwargs: None)

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


def test_chat_stream_permit_release_is_idempotent():
    """A late cleanup must not free the next request's acquire."""
    from terminal.api.fastapi_app import _ChatStreamPermit

    semaphore = threading.BoundedSemaphore(1)
    assert semaphore.acquire(blocking=False) is True
    permit = _ChatStreamPermit(semaphore)
    permit.release()
    permit.release()

    assert semaphore.acquire(blocking=False) is True
    semaphore.release()


_CHAT_JSON = {"messages": [{"role": "user", "content": "hello"}]}
_CHAT_BODY = json.dumps(_CHAT_JSON).encode()


def _streaming_app(tmp_path: Path):
    return create_app(
        "test-token",
        runtime_context=create_runtime_context(db_path=tmp_path / "archer.db"),
    )


def _slot_is_free(app) -> bool:
    semaphore = app.state.chat_stream_semaphore
    acquired = semaphore.acquire(blocking=False)
    if acquired:
        semaphore.release()
    return acquired


async def _drive_chat_stream(
    app,
    *,
    spec: str = "2.3",
    disconnect: asyncio.Event | None = None,
    fail_send_after_body: bool = False,
    saw_body: asyncio.Event | None = None,
) -> tuple[int, bytes]:
    """Run one POST /chat/stream at a chosen ASGI spec version.

    ``disconnect`` lets the caller emit ``http.disconnect`` (uvicorn's spec
    2.3 path). ``fail_send_after_body`` makes the first body ``send`` raise
    ``OSError`` (spec >= 2.4 path).
    """
    sent_request = False
    status = 0
    body = bytearray()

    async def receive():
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": _CHAT_BODY, "more_body": False}
        if disconnect is None:
            await asyncio.Event().wait()
        else:
            await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(message["status"])
            return
        if message["type"] != "http.response.body":
            return
        chunk = message.get("body") or b""
        body.extend(chunk)
        if chunk and saw_body is not None:
            saw_body.set()
        if chunk and fail_send_after_body:
            raise OSError("client gone")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/chat/stream",
        "raw_path": b"/chat/stream",
        "query_string": b"",
        "headers": [
            (b"authorization", b"Bearer test-token"),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 80),
    }
    await app(scope, receive, send)
    return status, bytes(body)


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("timed out waiting for chat-stream condition")
        await asyncio.sleep(0.01)


def test_chat_stream_normal_completion_then_second_request_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "terminal.api.fastapi_app._iter_chat_chunks",
        lambda *args, **kwargs: iter(
            [{"type": "token", "text": "hi"}, {"type": "done", "done": True}]
        ),
    )
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda *args, **kwargs: None)
    monkeypatch.setattr("terminal.api.fastapi_app.check_rate_limit", lambda *args, **kwargs: True)
    app = _streaming_app(tmp_path)

    async def scenario():
        first_status, first_body = await _drive_chat_stream(app)
        second_status, second_body = await _drive_chat_stream(app)
        return first_status, first_body, second_status, second_body

    first_status, first_body, second_status, second_body = asyncio.run(scenario())

    assert first_status == 200
    assert b"hi" in first_body
    assert second_status == 200
    assert b"hi" in second_body
    assert _slot_is_free(app)


def test_chat_stream_client_disconnect_frees_slot_for_next_request(tmp_path, monkeypatch):
    """uvicorn HTTP (ASGI 2.3) drops a sync generator on disconnect without close()."""
    calls = {"n": 0}

    def chunks(*args, **kwargs):
        calls["n"] += 1
        turn = calls["n"]
        yield {"type": "token", "text": f"turn{turn}"}
        if turn == 1:
            while True:
                time.sleep(0.01)
                yield {"type": "statusEvent", "statusEvent": {"id": "still-running"}}
        yield {"type": "done", "done": True}

    monkeypatch.setattr("terminal.api.fastapi_app._iter_chat_chunks", chunks)
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda *args, **kwargs: None)
    monkeypatch.setattr("terminal.api.fastapi_app.check_rate_limit", lambda *args, **kwargs: True)
    app = _streaming_app(tmp_path)

    async def scenario():
        disconnect = asyncio.Event()
        saw_body = asyncio.Event()
        first = asyncio.create_task(
            _drive_chat_stream(app, spec="2.3", disconnect=disconnect, saw_body=saw_body)
        )
        await asyncio.wait_for(saw_body.wait(), timeout=2)
        disconnect.set()
        first_status, first_body = await asyncio.wait_for(first, timeout=2)
        await _wait_until(lambda: _slot_is_free(app))
        second_status, second_body = await _drive_chat_stream(app, spec="2.3")
        return first_status, first_body, second_status, second_body

    first_status, first_body, second_status, second_body = asyncio.run(scenario())

    assert first_status == 200
    assert b"turn1" in first_body
    assert second_status == 200
    assert b"turn2" in second_body
    assert b"chat_busy" not in second_body
    assert _slot_is_free(app)


def test_chat_stream_send_error_disconnect_frees_slot(tmp_path, monkeypatch):
    """ASGI spec >= 2.4 reports client disconnect as OSError from send()."""
    calls = {"n": 0}

    def chunks(*args, **kwargs):
        calls["n"] += 1
        turn = calls["n"]
        yield {"type": "token", "text": f"turn{turn}"}
        if turn == 1:
            while True:
                time.sleep(0.01)
                yield {"type": "statusEvent", "statusEvent": {"id": "still-running"}}
        yield {"type": "done", "done": True}

    monkeypatch.setattr("terminal.api.fastapi_app._iter_chat_chunks", chunks)
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda *args, **kwargs: None)
    monkeypatch.setattr("terminal.api.fastapi_app.check_rate_limit", lambda *args, **kwargs: True)
    app = _streaming_app(tmp_path)

    async def scenario():
        with pytest.raises(OSError, match="client gone"):
            await _drive_chat_stream(app, spec="2.4", fail_send_after_body=True)
        await _wait_until(lambda: _slot_is_free(app))
        return await _drive_chat_stream(app, spec="2.4")

    second_status, second_body = asyncio.run(scenario())

    assert second_status == 200
    assert b"turn2" in second_body
    assert _slot_is_free(app)


def test_chat_stream_disconnect_during_blocked_chunk_frees_slot_without_stealing_next(tmp_path, monkeypatch):
    """Disconnect mid-model-call frees the slot, and that release is one-shot."""
    lock = threading.Lock()
    blocks: list[threading.Event] = []
    entered: list[threading.Event] = []

    def chunks(*args, **kwargs):
        with lock:
            index = len(blocks)
            block = threading.Event()
            started = threading.Event()
            blocks.append(block)
            entered.append(started)
        yield {"type": "token", "text": f"n{index}"}
        if index < 2:
            started.set()
            assert block.wait(5)
        yield {"type": "done", "done": True}

    monkeypatch.setattr("terminal.api.fastapi_app._iter_chat_chunks", chunks)
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda *args, **kwargs: None)
    monkeypatch.setattr("terminal.api.fastapi_app.check_rate_limit", lambda *args, **kwargs: True)
    app = _streaming_app(tmp_path)

    async def scenario():
        disconnect = asyncio.Event()
        first = asyncio.create_task(_drive_chat_stream(app, spec="2.3", disconnect=disconnect))
        await _wait_until(lambda: bool(entered) and entered[0].is_set())
        busy_status, busy_body = await _drive_chat_stream(app, spec="2.3")
        disconnect.set()
        await _wait_until(lambda: _slot_is_free(app))

        second = asyncio.create_task(_drive_chat_stream(app, spec="2.3"))
        await _wait_until(lambda: len(entered) > 1 and entered[1].is_set())
        blocks[0].set()
        first_status, first_body = await asyncio.wait_for(first, timeout=2)
        # Request 1 has finished and must not have released request 2's slot.
        overlap_status, overlap_body = await _drive_chat_stream(app, spec="2.3")
        blocks[1].set()
        second_status, second_body = await asyncio.wait_for(second, timeout=2)
        third_status, third_body = await _drive_chat_stream(app, spec="2.3")
        return (
            busy_status,
            busy_body,
            first_status,
            first_body,
            overlap_status,
            overlap_body,
            second_status,
            second_body,
            third_status,
            third_body,
        )

    try:
        (
            busy_status,
            busy_body,
            first_status,
            first_body,
            overlap_status,
            overlap_body,
            second_status,
            second_body,
            third_status,
            third_body,
        ) = asyncio.run(scenario())
    finally:
        for block in blocks:
            block.set()

    assert busy_status == 429
    assert b"chat_busy" in busy_body
    assert first_status == 200
    assert b"n0" in first_body
    assert overlap_status == 429
    assert b"chat_busy" in overlap_body
    assert second_status == 200
    assert b"n1" in second_body
    assert third_status == 200
    assert b"n2" in third_body
    assert _slot_is_free(app)


def test_chat_stream_generator_error_then_second_request_succeeds(tmp_path, monkeypatch):
    calls = {"n": 0}

    def chunks(*args, **kwargs):
        calls["n"] += 1
        yield {"type": "token", "text": "partial"}
        if calls["n"] == 1:
            raise RuntimeError("boom")
        yield {"type": "done", "done": True}

    monkeypatch.setattr("terminal.api.fastapi_app._iter_chat_chunks", chunks)
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda *args, **kwargs: None)
    monkeypatch.setattr("terminal.api.fastapi_app.check_rate_limit", lambda *args, **kwargs: True)
    app = _streaming_app(tmp_path)

    async def scenario():
        first_error: Exception | None = None
        try:
            await _drive_chat_stream(app)
        except Exception as exc:  # stream may surface the generator error
            first_error = exc
        await _wait_until(lambda: _slot_is_free(app))
        second_status, second_body = await _drive_chat_stream(app)
        return first_error, second_status, second_body

    first_error, second_status, second_body = asyncio.run(scenario())

    assert first_error is None or "boom" in str(first_error)
    assert second_status == 200
    assert b"partial" in second_body
    assert _slot_is_free(app)


def test_chat_stream_testclient_early_close_then_second_request_succeeds(client, monkeypatch):
    def endless(*args, **kwargs):
        yield {"type": "token", "text": "first"}
        while True:
            time.sleep(0.01)
            yield {"type": "statusEvent", "statusEvent": {"id": "still-running"}}

    monkeypatch.setattr("terminal.api.fastapi_app._iter_chat_chunks", endless)
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda *args, **kwargs: None)
    monkeypatch.setattr("terminal.api.fastapi_app.check_rate_limit", lambda *args, **kwargs: True)

    for _ in range(2):
        with client.stream(
            "POST",
            "/chat/stream",
            headers={"Authorization": "Bearer test-token"},
            json=_CHAT_JSON,
        ) as response:
            assert response.status_code == 200
            chunk = next(response.iter_text())
            assert "first" in chunk

    assert _slot_is_free(client.app)


def test_chat_stream_uvicorn_disconnect_during_blocked_call_allows_next_request(tmp_path, monkeypatch):
    """Live uvicorn (ASGI spec 2.3) must accept a new chat after the client drops mid-call."""
    release = threading.Event()
    started = threading.Event()
    calls = {"n": 0}
    lock = threading.Lock()

    def chunks(*args, **kwargs):
        with lock:
            index = calls["n"]
            calls["n"] += 1
        yield {"type": "token", "text": f"n{index}"}
        if index == 0:
            started.set()
            assert release.wait(5)
        yield {"type": "done", "done": True}

    monkeypatch.setattr("terminal.api.fastapi_app._iter_chat_chunks", chunks)
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda *args, **kwargs: None)
    monkeypatch.setattr("terminal.api.fastapi_app.check_rate_limit", lambda *args, **kwargs: True)
    app = _streaming_app(tmp_path)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="archer-chat-stream-test-uvicorn", daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/chat/stream"
    headers = {"Authorization": "Bearer test-token"}
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                health = httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.2)
            except httpx.HTTPError:
                health = None
            if health is not None and health.status_code == 200:
                break
            if time.monotonic() >= deadline:
                raise AssertionError("uvicorn did not start")
            time.sleep(0.05)

        with httpx.stream("POST", url, headers=headers, json=_CHAT_JSON, timeout=5) as response:
            assert response.status_code == 200
            assert "n0" in next(response.iter_text())
            assert started.wait(2)
        # Connection is closed while the first generator is still blocked in the model call.
        second = httpx.post(url, headers=headers, json=_CHAT_JSON, timeout=5)
    finally:
        release.set()
        server.should_exit = True
        thread.join(5)

    assert second.status_code == 200
    assert "n1" in second.text
    assert "chat_busy" not in second.text
    assert not thread.is_alive()


def test_websocket_chat_streams_events(client, monkeypatch):
    monkeypatch.setattr(
        "terminal.api.fastapi_app._iter_chat_chunks",
        lambda *args, **kwargs: iter([{"type": "token", "text": "ws"}]),
    )
    monkeypatch.setattr("terminal.api.fastapi_app._bg_extract_api", lambda history, **kwargs: None)

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
    assert response.json() == {
        "contractVersion": 1,
        "ok": True,
        "path": "/memory?include_rejected=true",
    }
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
    assert response.json() == {"contractVersion": 1, "path": "/memory"}
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
    assert response.json() == {"contractVersion": 1, "ok": True}
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
    assert response.json() == {
        "contractVersion": 1,
        "path": "/settings/validate",
        "body": {"apiKey": "sk-test"},
    }
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
