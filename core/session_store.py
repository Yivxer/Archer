"""Read/write helpers for session JSON files (messages + optional tokenUsage)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_session_payload(raw: object) -> tuple[list[dict], dict[str, Any] | None, dict[str, Any] | None]:
    if isinstance(raw, list):
        messages = [m for m in raw if isinstance(m, dict)]
        return messages, None, None
    if isinstance(raw, dict):
        messages_raw = raw.get("messages", [])
        messages = [m for m in messages_raw if isinstance(m, dict)] if isinstance(messages_raw, list) else []
        usage = raw.get("tokenUsage")
        meta = raw.get("meta")
        return (
            messages,
            usage if isinstance(usage, dict) else None,
            meta if isinstance(meta, dict) else None,
        )
    return [], None, None


def read_session_file(path: Path) -> tuple[list[dict], dict[str, Any] | None, dict[str, Any] | None]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], None, None
    return load_session_payload(raw)


def dump_session_file(
    messages: list[dict],
    *,
    token_usage: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> str:
    if token_usage or meta:
        payload: dict[str, Any] = {"messages": messages}
        if token_usage:
            payload["tokenUsage"] = token_usage
        if meta:
            payload["meta"] = meta
    else:
        payload = messages
    return json.dumps(payload, ensure_ascii=False, indent=2)
