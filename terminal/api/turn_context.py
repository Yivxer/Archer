"""Pure request normalization for one Desktop chat turn."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from terminal.api._config import _clean_chat_messages, _inject_thread_context


def clean_context_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not all(char.isalnum() or char in "_-" for char in text) or len(text) > 96:
        raise ValueError(f"{field} is invalid")
    return text


def _inject_stored_thread_context(messages: list[dict], thread_id: str) -> list[dict]:
    from memory.thread_context import format_context_capsule, get_thread_context, latest_thread_context

    latest_user = next((str(item.get("content", "")) for item in reversed(messages) if item.get("role") == "user"), "")
    resume_query = any(marker in latest_user for marker in ("上次聊到", "之前聊到", "继续之前", "接着上次"))
    state = get_thread_context(thread_id) if thread_id else None
    if state is None and resume_query and not thread_id:
        state = latest_thread_context()
    if state is None:
        return messages
    return [{"role": "system", "content": format_context_capsule(state)}, *messages]


def clean_memory_mode(value: object) -> str:
    if value in ("off", "conservative", "full"):
        return str(value)
    return "conservative"


def clean_obsidian_mode(value: object) -> str:
    if value in ("off", "summary", "full"):
        return str(value)
    return "summary"


def clean_file_refs(raw: object) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("fileRefs must be a list")
    refs: list[dict] = []
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if not path:
            continue
        name = str(item.get("name", "")).strip() or Path(path).name
        size = item.get("size")
        try:
            clean_size = int(size) if size is not None else 0
        except (TypeError, ValueError):
            clean_size = 0
        clean_ref = {"path": path, "name": name[:180], "size": max(0, clean_size)}
        content = item.get("content")
        if isinstance(content, str) and content:
            clean_ref["content"] = content[:12000]
            clean_ref["contentChars"] = len(clean_ref["content"])
            clean_ref["truncated"] = bool(item.get("truncated"))
        refs.append(clean_ref)
    return refs


def merge_inline_markdown_refs(query: str, refs: list[dict] | None) -> list[dict]:
    """Treat explicit local Markdown paths as bounded, read-only context refs."""
    merged = list(refs or [])
    known = {str(ref.get("path", "")) for ref in merged if isinstance(ref, dict)}
    for raw_path in re.findall(r"(?:~|/Users)/[^\n\r`'\"]+?\.md\b", query):
        path = raw_path.strip()
        if path not in known:
            merged.append({"path": path, "name": Path(path).name, "size": 0})
            known.add(path)
    return merged[:5]


@dataclass(frozen=True, slots=True)
class TurnContext:
    messages: list[dict]
    memory_mode: str
    obsidian_mode: str
    file_refs: list[dict]
    thread_id: str = ""
    session_id: str = ""

    @classmethod
    def from_payload(cls, payload: dict) -> "TurnContext":
        messages = _clean_chat_messages(payload.get("messages"))
        thread_id = clean_context_id(payload.get("threadId"), "threadId")
        session_id = clean_context_id(payload.get("sessionId"), "sessionId")
        messages = _inject_thread_context(messages, payload.get("threadContext"))
        return cls(
            messages=_inject_stored_thread_context(messages, thread_id),
            memory_mode=clean_memory_mode(payload.get("memoryMode")),
            obsidian_mode=clean_obsidian_mode(payload.get("obsidianMode")),
            file_refs=clean_file_refs(payload.get("fileRefs")),
            thread_id=thread_id,
            session_id=session_id,
        )
