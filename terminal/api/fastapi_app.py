"""FastAPI runtime for Archer Desktop API (P5.8)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from core.runtime_context import RuntimeContext, create_runtime_context
from terminal.api._config import ALLOWED_DESKTOP_ORIGINS, ROOT, _load_config
from terminal.api._routes import payload_get, payload_post
from terminal.api._security import (
    MAX_CONTENT_LENGTH,
    check_rate_limit,
    constant_time_compare,
    error_response,
    normalize_error_payload,
)
from terminal.api._tools import _iter_chat_chunks
from terminal.api.contract import (
    CONTRACT_VERSION,
    CONTRACT_VERSION_HEADER,
    versioned_dict,
    versioned_payload,
)
from terminal.api.memory_extraction import (
    MemoryExtractionSubscriber,
    _bg_extract_api,
    publish_memory_extraction_receipt,
)
from terminal.api.turn_context import TurnContext

logger = logging.getLogger("archer_api")

PUBLIC_PATHS = frozenset({"/health", "/ready", "/openapi.json", "/docs", "/redoc"})
RATE_LIMIT_EXEMPT_PATHS = frozenset({"/health", "/ready", "/status"})
DEFAULT_MAX_CHAT_STREAMS = max(1, int(os.environ.get("ARCHER_MAX_CHAT_STREAMS", "1") or "1"))


def _authorized(path: str, authorization: str, desktop_token: str) -> bool:
    if path in {"/health", "/ready"}:
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
    payload = normalize_error_payload(status, payload)
    content = versioned_payload(payload)
    return JSONResponse(
        status_code=status,
        content=content,
        headers={CONTRACT_VERSION_HEADER: str(CONTRACT_VERSION)},
    )


def _handle_dispatch_error(path: str, exc: Exception) -> JSONResponse:
    if isinstance(exc, ValueError):
        logger.error("ERROR %s: ValidationError | %s", path, exc)
        return _json_response(400, {"error": "validation_error", "message": str(exc)})
    if isinstance(exc, FileNotFoundError):
        logger.error("ERROR %s: NotFoundError | %s", path, exc)
        return _json_response(404, {"error": "not_found", "message": str(exc)})
    logger.error("ERROR %s: ServerError | %s", path, exc)
    return _json_response(500, {"error": "server_error", "message": str(exc)})


def _dispatch_get(path: str, runtime_context: RuntimeContext | None = None) -> JSONResponse:
    try:
        status, payload = payload_get(path, runtime_context)
        return _json_response(status, payload)
    except Exception as exc:
        return _handle_dispatch_error(path, exc)


def _dispatch_post(
    path: str,
    body: dict,
    runtime_context: RuntimeContext | None = None,
) -> JSONResponse:
    try:
        status, payload = payload_post(path, body, runtime_context)
        return _json_response(status, payload)
    except Exception as exc:
        return _handle_dispatch_error(path, exc)


def _chat_stream_events(
    payload: dict,
    release_slot=None,
    runtime_context: RuntimeContext | None = None,
) -> Iterator[str]:
    turn = TurnContext.from_payload(payload)
    messages = turn.messages
    reply_chunks: list[str] = []
    has_error = False
    trace_id = ""
    receipt_summary: dict = {}
    chunk_iter = _iter_chat_chunks(
        messages, turn.memory_mode, turn.obsidian_mode, turn.file_refs, runtime_context
    )
    try:
        try:
            for event in chunk_iter:
                event_payload = event.get("runtimeContextEvent") or event.get("statusEvent") or {}
                if not trace_id and isinstance(event_payload, dict):
                    trace_id = str(event_payload.get("traceId", "") or "")
                if event.get("type") == "token" and event.get("text"):
                    reply_chunks.append(str(event["text"]))
                elif event.get("type") == "error":
                    # 流式出错：标记，跳过后续记忆提取，避免从不完整/错误回复中提取垃圾记忆
                    has_error = True
                yield f"data: {json.dumps(versioned_dict(event), ensure_ascii=False)}\n\n"
        except GeneratorExit:
            # 客户端断开连接：优雅关闭内层 generator，避免 Broken pipe 噪音
            # Starlette 会在客户端断开时向 generator 抛 GeneratorExit
            logger.info("[chat/stream] client disconnected, cleaning up generator")
            _close_iter(chunk_iter)
            raise
        finally:
            _close_iter(chunk_iter)
        # 只在流式正常结束且无错误时提取记忆
        if reply_chunks and not has_error:
            full_history = list(messages) + [{"role": "assistant", "content": "".join(reply_chunks)}]
            if runtime_context is None:
                _bg_extract_api(full_history)
            else:
                publish_memory_extraction_receipt(
                    runtime_context,
                    full_history,
                    receipt_id=trace_id or f"turn-{uuid4().hex}",
                    trace_id=trace_id,
                    receipt=receipt_summary,
                )
    finally:
        if callable(release_slot):
            release_slot()


def _close_iter(iter_obj) -> None:
    """安全关闭 generator/iterator，兼容 mock 返回的普通 list_iterator。"""
    close_fn = getattr(iter_obj, "close", None)
    if callable(close_fn):
        try:
            close_fn()
        except Exception:
            pass


class _ChatStreamPermit:
    """One acquire of the chat-stream semaphore, releasable once from any thread.

    A second release must be a no-op. BoundedSemaphore.release() would otherwise
    either raise or free a *later* request's acquire after this stream's cleanup
    races with the next one.
    """

    def __init__(self, semaphore: threading.BoundedSemaphore) -> None:
        self._semaphore = semaphore
        self._lock = threading.Lock()
        self._released = False

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._semaphore.release()


def _close_chat_stream(generator: object) -> bool:
    """Close a sync chat generator. Return False if another thread is inside it."""
    close = getattr(generator, "close", None)
    if not callable(close):
        return True
    try:
        close()
    except ValueError:
        # generator already executing; caller retries once it is suspended again
        return False
    except Exception:
        logger.warning("[chat/stream] closing stream generator failed", exc_info=True)
    return True


def _close_chat_stream_when_idle(generator: object) -> None:
    # In-flight model calls can run for the stream timeout; keep trying until
    # the generator is suspended so its finally (and chunk-iterator close) run.
    deadline = time.monotonic() + 300.0
    while True:
        if _close_chat_stream(generator):
            return
        if time.monotonic() >= deadline:
            logger.warning(
                "[chat/stream] stream generator still executing; chat slot was already released"
            )
            return
        time.sleep(0.05)


def _finish_chat_stream(permit: _ChatStreamPermit, generator: object) -> None:
    permit.release()
    if _close_chat_stream(generator):
        return
    threading.Thread(
        target=_close_chat_stream_when_idle,
        args=(generator,),
        name="archer-chat-stream-close",
        daemon=True,
    ).start()


class _ChatStreamResponse(StreamingResponse):
    """SSE response that frees the chat-stream slot when the client goes away.

    Starlette cancels ``stream_response`` on ``http.disconnect`` (ASGI spec
    2.3, which uvicorn advertises for HTTP) but does not ``close()`` a sync
    body generator. ``_chat_stream_events`` releases the slot in its
    ``finally``, so an abandoned generator keeps ``BoundedSemaphore(1)``
    forever and every later ``POST /chat/stream`` returns 429 ``chat_busy``.
    """

    def __init__(self, content: Iterator[str], permit: _ChatStreamPermit, **kwargs) -> None:
        super().__init__(content, **kwargs)
        self._permit = permit
        self._generator = content

    async def listen_for_disconnect(self, receive: Receive) -> None:
        try:
            await super().listen_for_disconnect(receive)
        finally:
            # Free the slot as soon as the client is gone, even if the current
            # chunk is still blocked in a worker thread. StreamingResponse
            # waits for that thread before __call__ returns.
            self._permit.release()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # spec >= 2.4 never calls listen_for_disconnect; send() raises and
            # the body iterator is dropped without close(). Always finish here.
            _finish_chat_stream(self._permit, self._generator)


def _read_desktop_pid_from_env() -> int | None:
    """从环境变量 ARCHER_DESKTOP_PID 读 Desktop 主进程 PID (L0 用)."""
    raw = os.environ.get("ARCHER_DESKTOP_PID", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def create_app(
    desktop_api_token: str = "",
    active_context_mgr=None,
    runtime_context: RuntimeContext | None = None,
) -> FastAPI:
    from memory.llm_port import configure_llm_client

    resolved_runtime_context = runtime_context
    if resolved_runtime_context is None:
        from core.llm_client import DefaultLLMClient

        resolved_runtime_context = create_runtime_context(llm_client=DefaultLLMClient())
    elif resolved_runtime_context.llm_client is None:
        from core.llm_client import DefaultLLMClient

        resolved_runtime_context = create_runtime_context(
            db_path=resolved_runtime_context.db_path,
            config=resolved_runtime_context.config,
            clock=resolved_runtime_context.clock,
            event_bus=resolved_runtime_context.event_bus,
            llm_client=DefaultLLMClient(),
            cancellations=resolved_runtime_context.cancellations,
        )
    configure_llm_client(resolved_runtime_context.llm_client)
    memory_extraction_subscriber = MemoryExtractionSubscriber(
        resolved_runtime_context,
        schedule=lambda history, active_context: _bg_extract_api(
            history,
            runtime_context=active_context,
        ),
    )
    memory_extraction_subscriber.subscribe()

    app = FastAPI(
        title="Archer Desktop API",
        version="0.2.0",
        description="Local API for Archer Desktop client",
    )
    app.state.desktop_api_token = desktop_api_token
    app.state.chat_stream_semaphore = threading.BoundedSemaphore(DEFAULT_MAX_CHAT_STREAMS)
    app.state.active_context_mgr = active_context_mgr
    app.state.runtime_context = resolved_runtime_context
    app.state.memory_extraction_subscriber = memory_extraction_subscriber

    @app.on_event("startup")
    def _on_startup() -> None:
        from memory.migrations import run_migrations

        migration_result = run_migrations(
            app.state.runtime_context.db_path,
            clock=app.state.runtime_context.clock,
        )
        app.state.schema_version = migration_result.version
        from core.runtime_recovery import coordinate_startup_recovery

        runtime_recovery = coordinate_startup_recovery(
            app.state.runtime_context.db_path,
            now=app.state.runtime_context.now().isoformat(),
        )
        app.state.runtime_recovery_runs = list(runtime_recovery.scanned_runs)
        app.state.runtime_recovery_report = runtime_recovery
        from memory.embedder import warmup

        embedding_thread = threading.Thread(
            target=warmup,
            name="archer-embedding-warmup",
            daemon=True,
        )
        embedding_thread.start()
        app.state.embedding_warmup = embedding_thread
        from infrastructure.outbox import recover_interrupted

        app.state.outbox_recovered = recover_interrupted(
            app.state.runtime_context.db_path,
            now=app.state.runtime_context.now(),
        )
        from core.initiative_delivery import process_thread_resume_outbox

        app.state.initiative_outbox_sent = process_thread_resume_outbox(
            app.state.runtime_context.db_path,
            now=app.state.runtime_context.now(),
        )

        try:
            from memory.portable_export import create_rotating_backup

            context = app.state.runtime_context
            create_rotating_backup(
                context.db_path,
                context.config or _load_config(),
                context.db_path.parent / "backups" / "portable",
                now=context.now(),
            )
            logger.info("[startup] portable Soul/Memory backup refreshed")
        except Exception as exc:
            logger.warning("[startup] portable backup failed: %s", exc)

        # L0 active_context: 启动时判定崩溃 + 写新 active_context + 启动心跳
        if active_context_mgr is not None:
            try:
                desktop_pid = _read_desktop_pid_from_env()
                is_crash, reason, crash_count = active_context_mgr.on_startup(desktop_pid=desktop_pid)
                active_context_mgr.start_heartbeat()
                app.state.startup_crash_info = (is_crash, reason, crash_count)
                logger.info(
                    "[startup] active_context initialized: is_crash=%s reason=%s crash_count=%d",
                    is_crash, reason, crash_count,
                )
            except Exception as exc:
                logger.warning("[startup] active_context init failed: %s", exc)
                app.state.startup_crash_info = (False, "init_failed", 0)

        # 初始化定时任务：确保假设扫描任务存在，并执行到期的定时任务
        # 移植自 terminal/archer.py:336-337，API 进程之前缺失此逻辑导致定时任务失效
        try:
            from core.reflection_scheduler import ensure_hypothesis_scan_schedule
            from core.scheduler import run_due_tasks
            from skills.loader import load_skills
            schedule_json = app.state.runtime_context.db_path.parent / "schedules.json"
            ensure_hypothesis_scan_schedule(
                db_path=app.state.runtime_context.db_path,
                now=app.state.runtime_context.now(),
                output_path=schedule_json,
            )
            run_due_tasks(
                load_skills(),
                db_path=app.state.runtime_context.db_path,
                now=app.state.runtime_context.now(),
                output_path=schedule_json,
            )
            logger.info("[startup] scheduled tasks initialized")
        except Exception as exc:
            logger.warning("[startup] scheduled tasks init failed: %s", exc)

    @app.on_event("shutdown")
    def _on_shutdown() -> None:
        # L0 active_context: 正常退出时写 exit_status.clean=True
        if active_context_mgr is not None:
            try:
                active_context_mgr.on_shutdown(clean=True, reason="user_quit")
                logger.info("[shutdown] active_context written with clean exit")
            except Exception as exc:
                logger.warning("[shutdown] active_context shutdown write failed: %s", exc)

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
        rate_limit_required = (
            request.method not in {"OPTIONS", "GET"}
            and path not in RATE_LIMIT_EXEMPT_PATHS
        )
        if rate_limit_required and not check_rate_limit(client_ip, path):
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
    async def health() -> dict[str, object]:
        return {"contractVersion": CONTRACT_VERSION, "ok": True}

    @app.get("/ready")
    async def ready() -> dict[str, object]:
        from core.persona_sources import persona_source_status
        from terminal.api._config import _load_config

        persona = persona_source_status(_load_config())
        return {
            "contractVersion": CONTRACT_VERSION,
            "ok": True,
            "ready": True,
            "runtime": "fastapi",
            "persona": persona,
        }

    @app.get("/active-context")
    async def active_context_endpoint() -> dict:
        """L0 active_context: 返回当前 active_context + 启动时崩溃判定结果."""
        mgr = app.state.active_context_mgr
        if mgr is None:
            return {"ok": False, "error": "active_context not configured"}
        snapshot = mgr.get_snapshot()
        startup_crash_info = getattr(app.state, "startup_crash_info", (False, "no_previous_context", 0))
        is_crash, reason, crash_count = startup_crash_info
        return {
            "ok": True,
            "active_context": snapshot,
            "is_crash": is_crash,
            "crash_reason": reason,
            "crash_count": crash_count,
        }

    @app.post("/chat/stream")
    async def chat_stream(request: Request):
        payload = await request.json()
        if not isinstance(payload, dict):
            return _json_response(400, {"error": "validation_error", "message": "payload must be an object"})
        semaphore = request.app.state.chat_stream_semaphore
        if not semaphore.acquire(blocking=False):
            return _json_response(429, {
                "error": "chat_busy",
                "message": "上一轮对话仍在处理中，请等待它结束后再发送。",
            })
        permit = _ChatStreamPermit(semaphore)
        try:
            generator = _chat_stream_events(
                payload,
                release_slot=permit.release,
                runtime_context=request.app.state.runtime_context,
            )
            return _ChatStreamResponse(
                generator,
                permit,
                media_type="text/event-stream; charset=utf-8",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )
        except BaseException:
            permit.release()
            raise

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
            for frame in _chat_stream_events(
                payload, runtime_context=websocket.app.state.runtime_context
            ):
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

    from terminal.api.runtime_run_routes import register_runtime_run_routes

    register_runtime_run_routes(app)

    @app.api_route("/{full_path:path}", methods=["GET"])
    async def get_route(full_path: str, request: Request) -> Response:
        if full_path == "health":
            return await health()
        if full_path == "ready":
            return await ready()
        path = _path_with_query(request)
        return await run_in_threadpool(_dispatch_get, path, app.state.runtime_context)

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
        return await run_in_threadpool(
            _dispatch_post, path, payload, app.state.runtime_context
        )

    return app


def run_fastapi_server(host: str, port: int, desktop_api_token: str = "") -> None:
    import uvicorn

    from core.active_context import ActiveContextManager

    active_context_mgr = ActiveContextManager()
    app = create_app(desktop_api_token, active_context_mgr=active_context_mgr)
    logger.info("Archer Desktop API (FastAPI) listening on http://%s:%s", host, port)
    print(f"Archer Desktop API (FastAPI) listening on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


def configure_logging() -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "archer_api.log"),
            logging.StreamHandler(),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Archer Desktop FastAPI runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    configure_logging()
    run_fastapi_server(args.host, args.port, args.token)


if __name__ == "__main__":
    main()
