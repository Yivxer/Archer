"""Pure request normalization for one Desktop chat turn."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from terminal.api._config import _clean_chat_messages, _inject_thread_context


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


@dataclass(frozen=True, slots=True)
class TurnContext:
    messages: list[dict]
    memory_mode: str
    obsidian_mode: str
    file_refs: list[dict]

    @classmethod
    def from_payload(cls, payload: dict) -> "TurnContext":
        messages = _clean_chat_messages(payload.get("messages"))
        return cls(
            messages=_inject_thread_context(messages, payload.get("threadContext")),
            memory_mode=clean_memory_mode(payload.get("memoryMode")),
            obsidian_mode=clean_obsidian_mode(payload.get("obsidianMode")),
            file_refs=clean_file_refs(payload.get("fileRefs")),
        )
