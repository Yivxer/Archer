"""Shared constants, configuration, and utility functions for the Archer Desktop API."""

from __future__ import annotations

import re
import sys
from pathlib import Path
import tomllib

# ---------------------------------------------------------------------------
# Project root & sys.path
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

ROOT = _PROJECT_ROOT
CONFIG_PATH = ROOT / "archer.toml"

# ---------------------------------------------------------------------------
# Shared mutable state
# ---------------------------------------------------------------------------
import threading

PENDING_TOOL_DRAFTS: dict[str, dict] = {}
_DRAFT_LOCK = threading.Lock()


def set_tool_draft(event_id: str, request: dict) -> None:
    with _DRAFT_LOCK:
        PENDING_TOOL_DRAFTS[event_id] = request


def get_tool_draft(event_id: str) -> dict | None:
    with _DRAFT_LOCK:
        return PENDING_TOOL_DRAFTS.get(event_id)


def pop_tool_draft(event_id: str) -> dict | None:
    with _DRAFT_LOCK:
        return PENDING_TOOL_DRAFTS.pop(event_id, None)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SETTINGS_ALLOWED_FIELDS = {
    "provider",
    "baseUrl",
    "model",
    "configPath",
    "memoryDbPath",
    "sessionsPath",
}

TEXT_FILE_EXTENSIONS = {
    ".cfg", ".conf", ".css", ".csv", ".env", ".html", ".ini",
    ".js", ".json", ".jsx", ".log", ".md", ".mjs", ".py",
    ".rs", ".sh", ".toml", ".ts", ".tsx", ".txt", ".xml",
    ".yaml", ".yml",
}

ALLOWED_DESKTOP_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "null",
}

# ---------------------------------------------------------------------------
# Configuration & utility helpers
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    try:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return f"{value[:3]}-••••••••{value[-4:]}"


def _read_text(path_value: str | None) -> str:
    if not path_value:
        return ""
    try:
        path = Path(path_value).expanduser()
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _valid_session_id(session_id: str) -> bool:
    return bool(re.fullmatch(r"[0-9]{8}_[0-9]{6}(?:_[0-9]+)?", session_id))


def _clean_chat_messages(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("messages must be a list")
    messages: list[dict] = []
    for item in raw[-20:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content", item.get("text"))
        if role not in ("system", "user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        messages.append({"role": role, "content": content.strip()[:8000]})
    if not any(m["role"] == "user" for m in messages):
        raise ValueError("messages must include at least one user message")
    return messages


def _clean_session_messages(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("messages must be a list")
    messages: list[dict] = []
    for item in raw[-100:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content", item.get("text"))
        if role not in ("system", "user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        messages.append({"role": role, "content": content.strip()})
    if len(messages) < 2:
        raise ValueError("session must include at least two messages")
    return messages
