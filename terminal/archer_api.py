"""Localhost API for Archer Desktop.

The API keeps chat streaming conservative, but tool drafts now share the
terminal policy/runtime path before execution.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from terminal.api._config import (
    ALLOWED_DESKTOP_ORIGINS,
    PENDING_TOOL_DRAFTS,
    ROOT,
)
from terminal.api._routes import (
    _append_session,
    _session_detail,
    _tool_approval,
    _validate_settings_draft,
    payload_get,
    payload_post,
)
from terminal.api._security import (
    MAX_CONTENT_LENGTH,
    check_rate_limit,
    constant_time_compare,
    error_response,
    normalize_error_payload,
)
from terminal.api import _tools as _api_tools
from terminal.api import desktop_tool_execution as _desktop_tool_execution
from terminal.api.contract import CONTRACT_VERSION, CONTRACT_VERSION_HEADER, versioned_dict
from terminal.api._tools import (
    _bg_extract_api,
    _extract_github_args,
    _file_reference_context,
    _iter_chat_chunks,
    _is_dangerous_shell,
    _make_api_tool_request,
    _select_api_skills,
    _should_trigger_github,
    _should_trigger_shell,
)
from terminal.api.turn_context import (
    TurnContext,
    clean_file_refs as _clean_file_refs,
    clean_memory_mode as _clean_memory_mode,
    clean_obsidian_mode as _clean_obsidian_mode,
)


def _request_path_with_query(raw_path: str) -> str:
    parsed = urlparse(raw_path)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def _with_legacy_tool_bindings(fn, *args, **kwargs):
    """Run split API helpers with old archer_api monkeypatch points honored."""
    patched = {
        "_make_api_tool_request": _make_api_tool_request,
        "_select_api_skills": _select_api_skills,
        "_should_trigger_shell": _should_trigger_shell,
        "_should_trigger_github": _should_trigger_github,
    }
    original = {name: getattr(_api_tools, name) for name in patched}
    try:
        for name, value in patched.items():
            setattr(_api_tools, name, value)
        return fn(*args, **kwargs)
    finally:
        for name, value in original.items():
            setattr(_api_tools, name, value)


def _iter_api_tool_events(query: str):
    patched = {
        "_make_api_tool_request": _make_api_tool_request,
        "_select_api_skills": _select_api_skills,
        "_should_trigger_shell": _should_trigger_shell,
        "_should_trigger_github": _should_trigger_github,
    }
    targets = (_api_tools, _desktop_tool_execution)
    original = {
        (target, name): getattr(target, name)
        for target in targets
        for name in patched
        if hasattr(target, name)
    }
    try:
        for target in targets:
            for name, value in patched.items():
                if hasattr(target, name):
                    setattr(target, name, value)
        yield from _api_tools._iter_api_tool_events(query)
    finally:
        for (target, name), value in original.items():
            setattr(target, name, value)


def _execute_api_tool_preview(*args, **kwargs):
    return _with_legacy_tool_bindings(_api_tools._execute_api_tool_preview, *args, **kwargs)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "archer_api.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("archer_api")


def _log_error(endpoint: str, error: str, details: str = "") -> None:
    """统一错误日志记录。"""
    msg = f"ERROR {endpoint}: {error}"
    if details:
        msg += f" | {details}"
    logger.error(msg)


def _log_info(endpoint: str, message: str) -> None:
    """统一信息日志记录。"""
    logger.info(f"INFO {endpoint}: {message}")


# ---------------------------------------------------------------------------
# Desktop API token (set at startup)
# ---------------------------------------------------------------------------
DESKTOP_API_TOKEN = ""


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "ArcherDesktopAPI/0.1"

    def _origin(self) -> str:
        return self.headers.get("Origin", "")

    def _allow_origin(self) -> str:
        origin = self._origin()
        if origin in ALLOWED_DESKTOP_ORIGINS:
            return origin
        return "http://localhost:5173"

    def _send_auth_error(self) -> None:
        self._send(401, {"error": "unauthorized", "message": "desktop API token is required"})

    def _authorized(self) -> bool:
        if urlparse(self.path).path in {"/health", "/ready"}:
            return True
        if not DESKTOP_API_TOKEN:
            return False
        expected = f"Bearer {DESKTOP_API_TOKEN}"
        return constant_time_compare(self.headers.get("Authorization", ""), expected)

    def _send(self, status: int, payload: dict | list) -> None:
        payload = normalize_error_payload(status, payload)
        payload = versioned_dict(payload) if isinstance(payload, dict) else payload
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._allow_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header(CONTRACT_VERSION_HEADER, str(CONTRACT_VERSION))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(
        self,
        messages: list[dict],
        memory_mode: str = "conservative",
        obsidian_mode: str = "summary",
        file_refs: list[dict] | None = None,
    ) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", self._allow_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        reply_chunks: list[str] = []
        for event in _iter_chat_chunks(messages, memory_mode, obsidian_mode, file_refs):
            if event.get("type") == "token" and event.get("text"):
                reply_chunks.append(event["text"])
            frame = f"data: {json.dumps(versioned_dict(event), ensure_ascii=False)}\n\n".encode("utf-8")
            self.wfile.write(frame)
            self.wfile.flush()
        if reply_chunks:
            full_history = list(messages) + [{"role": "assistant", "content": "".join(reply_chunks)}]
            _bg_extract_api(full_history)

    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_GET(self) -> None:
        if not self._authorized():
            self._send_auth_error()
            return
        client_ip = self.client_address[0]
        path = _request_path_with_query(self.path)
        if not check_rate_limit(client_ip, path):
            code, body = error_response(429, "rate_limited", "请求过于频繁，请稍后重试")
            self._send(code, body)
            return
        try:
            status, payload = payload_get(path)
        except ValueError as exc:
            _log_error(path, "ValidationError", str(exc))
            status, payload = 400, {"error": "validation_error", "message": str(exc)}
        except FileNotFoundError as exc:
            _log_error(path, "NotFoundError", str(exc))
            status, payload = 404, {"error": "not_found", "message": str(exc)}
        except Exception as exc:
            _log_error(path, "ServerError", str(exc))
            status, payload = 500, {"error": "server_error", "message": str(exc)}
        self._send(status, payload)

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_auth_error()
            return
        client_ip = self.client_address[0]
        path = urlparse(self.path).path
        if not check_rate_limit(client_ip, path):
            code, body = error_response(429, "rate_limited", "请求过于频繁，请稍后重试")
            self._send(code, body)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_CONTENT_LENGTH:
                _log_error(path, "PayloadTooLarge", f"size: {length}")
                self._send(413, {"error": "payload_too_large", "message": "请求体过大（最大 128KB）"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            if path == "/chat/stream":
                turn = TurnContext.from_payload(payload)
                self._send_sse(
                    turn.messages,
                    turn.memory_mode,
                    turn.obsidian_mode,
                    turn.file_refs,
                )
                return
            status, response = payload_post(path, payload)
        except ValueError as exc:
            _log_error(path, "ValidationError", str(exc))
            status, response = 400, {"error": "validation_error", "message": str(exc)}
        except FileNotFoundError as exc:
            _log_error(path, "NotFoundError", str(exc))
            status, response = 404, {"error": "not_found", "message": str(exc)}
        except Exception as exc:
            _log_error(path, "ServerError", str(exc))
            status, response = 500, {"error": "server_error", "message": str(exc)}
        self._send(status, response)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[archer-api] {self.address_string()} - {fmt % args}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global DESKTOP_API_TOKEN
    parser = argparse.ArgumentParser(description="Run Archer Desktop read-only API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default="")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use legacy BaseHTTPRequestHandler server instead of FastAPI",
    )
    args = parser.parse_args()
    DESKTOP_API_TOKEN = args.token or os.environ.get("ARCHER_DESKTOP_TOKEN", "")

    if args.legacy:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
        _log_info("server", f"Archer Desktop API (legacy) listening on http://{args.host}:{args.port}")
        print(f"Archer Desktop API (legacy) listening on http://{args.host}:{args.port}")
        server.serve_forever()
        return

    from terminal.api.fastapi_app import run_fastapi_server

    run_fastapi_server(args.host, args.port, DESKTOP_API_TOKEN)


if __name__ == "__main__":
    main()
