"""FastAPI runtime for Archer Desktop API (P5.8)."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response

from terminal.api._config import ALLOWED_DESKTOP_ORIGINS, _clean_chat_messages
from terminal.api._routes import payload_get, payload_post
from terminal.api._security import (
    MAX_CONTENT_LENGTH,
    check_rate_limit,
    constant_time_compare,
    error_response,
)
from terminal.api._tools import (
    _bg_extract_api,
    _clean_file_refs,
    _clean_memory_mode,
    _clean_obsidian_mode,
    _iter_chat_chunks,
)

logger = logging.getLogger("archer_api")

PUBLIC_PATHS = frozenset({"/health", "/openapi.json", "/docs", "/redoc"})


def _authorized(path: str, authorization: str, desktop_token: str) -> bool:
    if path == "/health":
        return True
    if not desktop_token:
        return False
    expected = f"Bearer {desktop_token}"
    return constant_time_compare(authorization or "", expected)


def _authorized_token(raw_token: str, desktop_token: str) -> bool:
    if not desktop_token:
        return False
    return constant_time_compare(raw_token or "", desktop_token)


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def _path_with_query(request: Request) -> str:
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    return path


def _json_response(status: int, payload: dict | list) -> JSONResponse:
    return JSONResponse(status_code=status, content=payload)


def _handle_dispatch_error(path: str, exc: Exception) -> JSONResponse:
    if isinstance(exc, ValueError):
        logger.error("ERROR %s: ValidationError | %s", path, exc)
        return _json_response(400, {"error": "validation_error", "message": str(exc)})
    if isinstance(exc, FileNotFoundError):
        logger.error("ERROR %s: NotFoundError | %s", path, exc)
        return _json_response(404, {"error": "not_found", "message": str(exc)})
    logger.error("ERROR %s: ServerError | %s", path, exc)
    return _json_response(500, {"error": "server_error", "message": str(exc)})


def _dispatch_get(path: str) -> JSONResponse:
    try:
        status, payload = payload_get(path)
        return _json_response(status, payload)
    except Exception as exc:
        return _handle_dispatch_error(path, exc)


def _dispatch_post(path: str, body: dict) -> JSONResponse:
    try:
        status, payload = payload_post(path, body)
        return _json_response(status, payload)
    except Exception as exc:
        return _handle_dispatch_error(path, exc)


def _chat_stream_events(payload: dict) -> Iterator[str]:
    messages = _clean_chat_messages(payload.get("messages"))
    memory_mode = _clean_memory_mode(payload.get("memoryMode"))
    obsidian_mode = _clean_obsidian_mode(payload.get("obsidianMode"))
    file_refs = _clean_file_refs(payload.get("fileRefs"))
    reply_chunks: list[str] = []
    for event in _iter_chat_chunks(messages, memory_mode, obsidian_mode, file_refs):
        if event.get("type") == "token" and event.get("text"):
            reply_chunks.append(str(event["text"]))
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    if reply_chunks:
        full_history = list(messages) + [{"role": "assistant", "content": "".join(reply_chunks)}]
        _bg_extract_api(full_history)


def create_app(desktop_api_token: str = "") -> FastAPI:
    app = FastAPI(
        title="Archer Desktop API",
        version="0.2.0",
        description="Local API for Archer Desktop client",
    )
    app.state.desktop_api_token = desktop_api_token

    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(ALLOWED_DESKTOP_ORIGINS),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        path = request.url.path
        token = str(getattr(request.app.state, "desktop_api_token", ""))
        auth_header = request.headers.get("Authorization", "")

        if request.method != "OPTIONS" and path not in PUBLIC_PATHS and not _authorized(path, auth_header, token):
            return _json_response(401, {"error": "unauthorized", "message": "desktop API token is required"})

        client_ip = _client_ip(request)
        if request.method != "OPTIONS" and not check_rate_limit(client_ip, path):
            status, body = error_response(429, "rate_limited", "请求过于频繁，请稍后重试")
            return _json_response(status, body)

        if request.method == "POST" and path != "/chat/stream":
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                length = 0
            if length > MAX_CONTENT_LENGTH:
                return _json_response(
                    413,
                    {"error": "payload_too_large", "message": "请求体过大（最大 128KB）"},
                )

        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/chat/stream")
    async def chat_stream(request: Request) -> StreamingResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            return _json_response(400, {"error": "validation_error", "message": "payload must be an object"})
        return StreamingResponse(
            _chat_stream_events(payload),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    @app.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket) -> None:
        token = str(getattr(websocket.app.state, "desktop_api_token", ""))
        query_token = websocket.query_params.get("token", "")
        auth_header = websocket.headers.get("authorization", "")
        bearer = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        if not (
            _authorized_token(query_token, token)
            or _authorized_token(bearer, token)
        ):
            await websocket.close(code=4401)
            return

        await websocket.accept()
        try:
            payload = await websocket.receive_json()
        except WebSocketDisconnect:
            return
        except Exception:
            await websocket.send_json({"type": "error", "message": "invalid websocket payload"})
            await websocket.close(code=4400)
            return

        if not isinstance(payload, dict):
            await websocket.send_json({"type": "error", "message": "payload must be an object"})
            await websocket.close(code=4400)
            return

        try:
            for frame in _chat_stream_events(payload):
                if not frame.startswith("data: "):
                    continue
                event = json.loads(frame.removeprefix("data: ").strip())
                await websocket.send_json(event)
        except WebSocketDisconnect:
            return
        except Exception as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
        finally:
            await websocket.close()

    @app.api_route("/{full_path:path}", methods=["GET"])
    async def get_route(full_path: str, request: Request) -> Response:
        if full_path == "health":
            return await health()
        path = _path_with_query(request)
        return _dispatch_get(path)

    @app.api_route("/{full_path:path}", methods=["POST"])
    async def post_route(full_path: str, request: Request) -> Response:
        path = request.url.path
        if path == "/chat/stream":
            return await chat_stream(request)
        try:
            payload = await request.json()
        except json.JSONDecodeError as exc:
            return _json_response(400, {"error": "validation_error", "message": str(exc)})
        if not isinstance(payload, dict):
            return _json_response(400, {"error": "validation_error", "message": "payload must be an object"})
        return _dispatch_post(path, payload)

    return app


def run_fastapi_server(host: str, port: int, desktop_api_token: str = "") -> None:
    import uvicorn

    app = create_app(desktop_api_token)
    logger.info("Archer Desktop API (FastAPI) listening on http://%s:%s", host, port)
    print(f"Archer Desktop API (FastAPI) listening on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
