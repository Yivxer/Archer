"""Local conversation thread index for Desktop sessions."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.paths import ROOT

THREADS_PATH = ROOT / "memory" / "conversation_threads.json"


def read_threads(path: Path | None = None) -> list[dict[str, Any]]:
    path = thread_store_path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [thread for item in raw if (thread := normalize_thread(item))]


def write_threads(threads: list[dict[str, Any]], path: Path | None = None) -> list[dict[str, Any]]:
    path = thread_store_path(path)
    normalized = [thread for item in threads if (thread := normalize_thread(item))]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def get_thread(thread_id: str, path: Path | None = None) -> dict[str, Any] | None:
    if not valid_thread_id(thread_id):
        return None
    return next((thread for thread in read_threads(path) if thread["id"] == thread_id), None)


def create_thread(messages: list[dict], session_id: str | None = None, path: Path | None = None) -> dict[str, Any]:
    now = now_iso()
    threads = read_threads(path)
    thread = {
        "id": unique_thread_id(threads, now),
        "title": title_from_messages(messages),
        "summary": summary_from_messages(messages),
        "createdAt": now,
        "updatedAt": now,
        "sessionIds": [session_id] if session_id else [],
        "archived": False,
    }
    threads.insert(0, thread)
    write_threads(threads, path)
    return thread


def update_thread(thread_id: str, patch: dict[str, Any], path: Path | None = None) -> dict[str, Any] | None:
    if not valid_thread_id(thread_id):
        return None
    threads = read_threads(path)
    updated: dict[str, Any] | None = None
    for index, thread in enumerate(threads):
        if thread["id"] != thread_id:
            continue
        next_thread = {**thread}
        if isinstance(patch.get("title"), str) and patch["title"].strip():
            next_thread["title"] = compact_text(patch["title"], 80)
        if isinstance(patch.get("summary"), str):
            next_thread["summary"] = compact_text(patch["summary"], 500)
        if isinstance(patch.get("projectId"), str):
            next_thread["projectId"] = patch["projectId"].strip()
        if isinstance(patch.get("archived"), bool):
            next_thread["archived"] = patch["archived"]
        next_thread["updatedAt"] = now_iso()
        threads[index] = next_thread
        updated = next_thread
        break
    if updated is None:
        return None
    write_threads(threads, path)
    return updated


def add_session_to_thread(
    thread_id: str,
    session_id: str,
    messages: list[dict] | None = None,
    path: Path | None = None,
) -> dict[str, Any] | None:
    if not valid_thread_id(thread_id) or not session_id:
        return None
    threads = read_threads(path)
    updated: dict[str, Any] | None = None
    for index, thread in enumerate(threads):
        if thread["id"] != thread_id:
            continue
        session_ids = list(thread.get("sessionIds") or [])
        if session_id not in session_ids:
            session_ids.append(session_id)
        next_thread = {
            **thread,
            "sessionIds": session_ids,
            "updatedAt": now_iso(),
        }
        if messages:
            next_thread["summary"] = summary_from_messages(messages)
        threads[index] = next_thread
        updated = next_thread
        break
    if updated is None:
        return None
    write_threads(threads, path)
    return updated


def normalize_thread(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    thread_id = str(value.get("id", "") or "").strip()
    title = str(value.get("title", "") or "").strip()
    if not valid_thread_id(thread_id) or not title:
        return None
    session_ids = value.get("sessionIds")
    return {
        "id": thread_id,
        "title": compact_text(title, 80),
        "summary": compact_text(str(value.get("summary", "") or ""), 500),
        "createdAt": str(value.get("createdAt", "") or ""),
        "updatedAt": str(value.get("updatedAt", "") or ""),
        "sessionIds": list(dict.fromkeys(
            item.strip() for item in session_ids if isinstance(item, str) and item.strip()
        )) if isinstance(session_ids, list) else [],
        **({"projectId": str(value.get("projectId")).strip()} if isinstance(value.get("projectId"), str) and str(value.get("projectId")).strip() else {}),
        "archived": bool(value.get("archived", False)),
    }


def title_from_messages(messages: list[dict]) -> str:
    first_user = next((str(item.get("content", "") or "") for item in messages if item.get("role") == "user"), "")
    return compact_text(first_user, 42) or "未命名话题"


def summary_from_messages(messages: list[dict]) -> str:
    first_user = next((str(item.get("content", "") or "") for item in messages if item.get("role") == "user"), "")
    recent_user = next((str(item.get("content", "") or "") for item in reversed(messages) if item.get("role") == "user"), "")
    recent_assistant = next((str(item.get("content", "") or "") for item in reversed(messages) if item.get("role") == "assistant"), "")
    parts = []
    if first_user:
        parts.append(f"目标：{compact_text(first_user, 120)}")
    if recent_user and recent_user != first_user:
        parts.append(f"最近问题：{compact_text(recent_user, 120)}")
    if recent_assistant:
        parts.append(f"最近结论：{compact_text(recent_assistant, 180)}")
    return "\n".join(parts)


def compact_text(value: str, limit: int) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit]


def valid_thread_id(thread_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,96}", thread_id))


def unique_thread_id(threads: list[dict[str, Any]], timestamp: str) -> str:
    base = "thread-" + re.sub(r"[^0-9]", "", timestamp)[:14]
    existing = {thread.get("id") for thread in threads}
    if base not in existing:
        return base
    counter = 1
    while f"{base}_{counter}" in existing:
        counter += 1
    return f"{base}_{counter}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def thread_store_path(path: Path | None = None) -> Path:
    return path or THREADS_PATH
