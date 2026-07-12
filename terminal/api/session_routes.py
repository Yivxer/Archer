"""Session and conversation-thread route domain helpers."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from terminal.api._config import _clean_session_messages, _valid_session_id


def sessions(limit: int = 20) -> list[dict]:
    from core.session import SESSIONS_DIR
    from core.session_store import read_session_file

    sessions_dir = Path(SESSIONS_DIR)
    if not sessions_dir.exists():
        return []
    items: list[dict] = []
    for path in sorted(sessions_dir.glob("*.json"), reverse=True)[:limit]:
        messages, _usage, meta = read_session_file(path)
        first_user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        item = {
            "id": path.stem,
            "title": str(first_user).strip().replace("\n", " ")[:42] or path.stem,
            "date": path.stem[:8],
            "turns": max(1, len(messages) // 2),
            "tone": "saved",
            "preview": str(first_user).strip().replace("\n", " ")[:60],
        }
        _add_meta(item, meta)
        items.append(item)
    return items


def sessions_search(query: str, limit: int = 30) -> list[dict]:
    from core.session import SESSIONS_DIR
    from core.session_store import read_session_file

    query_lower = query.strip().lower()
    sessions_dir = Path(SESSIONS_DIR)
    if not query_lower or not sessions_dir.exists():
        return []
    results: list[dict] = []
    for path in sorted(sessions_dir.glob("*.json"), reverse=True)[:limit * 3]:
        messages, _usage, meta = read_session_file(path)
        first_user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        snippet = ""
        match_role = ""
        for message in messages:
            content = str(message.get("content", "") or "")
            if query_lower in content.lower():
                index = content.lower().find(query_lower)
                start = max(0, index - 30)
                end = min(len(content), index + len(query) + 30)
                snippet = ("…" if start else "") + content[start:end] + ("…" if end < len(content) else "")
                match_role = str(message.get("role", ""))
                break
        if not snippet:
            continue
        item = {
            "id": path.stem,
            "title": str(first_user).strip().replace("\n", " ")[:42] or path.stem,
            "date": path.stem[:8],
            "turns": max(1, len(messages) // 2),
            "tone": "saved",
            "preview": str(first_user).strip().replace("\n", " ")[:60],
            "snippet": snippet,
            "matchRole": match_role,
        }
        _add_meta(item, meta)
        results.append(item)
        if len(results) >= limit:
            break
    return results


def session_detail(session_id: str) -> dict | None:
    from core.session import SESSIONS_DIR
    from core.session_store import read_session_file

    if not _valid_session_id(session_id):
        return None
    path = Path(SESSIONS_DIR) / f"{session_id}.json"
    if not path.exists() or not path.is_file():
        return None
    messages, token_usage, meta = read_session_file(path)
    clean_messages = [
        {"id": index + 1, "role": item["role"], "text": item["content"]}
        for index, item in enumerate(messages if isinstance(messages, list) else [])
        if isinstance(item, dict)
        and item.get("role") in ("user", "assistant", "system")
        and isinstance(item.get("content"), str)
    ]
    first_user = next((item["text"] for item in clean_messages if item["role"] == "user"), "")
    detail = {
        "id": session_id,
        "title": first_user.strip().replace("\n", " ")[:42] or session_id,
        "date": session_id[:8],
        "turns": max(1, len(clean_messages) // 2),
        "tone": "saved",
        "messages": clean_messages,
    }
    if token_usage:
        detail["tokenUsage"] = token_usage
    _add_meta(detail, meta)
    return detail


def session_meta_from_payload(payload: dict) -> dict[str, str]:
    meta: dict[str, str] = {}
    expert_id = str(payload.get("expertId", "") or "").strip()
    expert_label = str(payload.get("expertLabel", "") or "").strip()
    thread_id = str(payload.get("threadId", "") or "").strip()
    if expert_id and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", expert_id):
        meta["expertId"] = expert_id
    if expert_label:
        meta["expertLabel"] = expert_label[:64]
    if thread_id and re.fullmatch(r"[A-Za-z0-9_-]{1,96}", thread_id):
        meta["threadId"] = thread_id
    return meta


def save_session(payload: dict) -> dict:
    from core.session import SESSIONS_DIR
    from core.session_store import dump_session_file
    from core.thread_store import add_session_to_thread, create_thread, get_thread
    from core.token_usage import session_usage_for_file

    messages = _clean_session_messages(payload.get("messages"))
    sessions_dir = Path(SESSIONS_DIR)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = sessions_dir / f"{session_id}.json"
    counter = 1
    while path.exists():
        path = sessions_dir / f"{session_id}_{counter}.json"
        counter += 1
    meta = session_meta_from_payload(payload)
    thread_id = str(meta.get("threadId", "") or "")
    if thread_id and not get_thread(thread_id):
        thread_id = ""
        meta.pop("threadId", None)
    if not thread_id:
        thread = create_thread(messages, path.stem)
        thread_id = thread["id"]
        meta["threadId"] = thread_id
    else:
        add_session_to_thread(thread_id, path.stem, messages)
    path.write_text(dump_session_file(messages, token_usage=session_usage_for_file(), meta=meta or None), encoding="utf-8")
    return {"id": path.stem, "path": str(path), "messages": len(messages), "threadId": thread_id}


def _clean_append_messages(raw: object) -> list[dict]:
    messages = _clean_session_messages(raw, min_messages=1)
    if len(messages) == 1:
        if messages[0]["role"] != "assistant":
            raise ValueError("single-message append must be assistant")
        return messages
    if len(messages) != 2:
        raise ValueError("append requires exactly one user/assistant turn or one assistant result")
    if messages[0]["role"] != "user" or messages[1]["role"] != "assistant":
        raise ValueError("append messages must be user then assistant")
    return messages


def delete_session(session_id: str) -> dict:
    from core.session import SESSIONS_DIR
    from core.thread_store import remove_session_from_thread

    if not _valid_session_id(session_id):
        raise ValueError("invalid session id")
    path = Path(SESSIONS_DIR) / f"{session_id}.json"
    existed = path.exists() and path.is_file()
    if existed:
        path.unlink()
    removed_thread = remove_session_from_thread(session_id)
    return {"ok": True, "id": session_id, "fileDeleted": existed, "threadRemoved": removed_thread.get("id") if removed_thread else None}


def append_session(session_id: str, payload: dict) -> dict:
    from core.session import SESSIONS_DIR
    from core.session_store import dump_session_file, read_session_file
    from core.thread_store import add_session_to_thread, create_thread

    if not _valid_session_id(session_id):
        raise ValueError("invalid session id")
    new_messages = _clean_append_messages(payload.get("messages"))
    path = Path(SESSIONS_DIR) / f"{session_id}.json"
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"session not found: {session_id}")
    existing, token_usage, meta = read_session_file(path)
    existing = existing if isinstance(existing, list) else []
    existing.extend(new_messages)
    meta = meta if isinstance(meta, dict) else {}
    thread_id = str(meta.get("threadId", "") or "")
    if thread_id:
        add_session_to_thread(thread_id, session_id, existing)
    else:
        thread = create_thread(existing, session_id)
        thread_id = thread["id"]
        meta["threadId"] = thread_id
    path.write_text(dump_session_file(existing, token_usage=token_usage, meta=meta), encoding="utf-8")
    return {"id": session_id, "path": str(path), "messages": len(existing), "appended": len(new_messages), "threadId": thread_id}


def threads() -> list[dict]:
    from core.thread_store import read_threads
    return read_threads()


def thread_detail(thread_id: str) -> dict | None:
    from core.thread_store import get_thread
    return get_thread(thread_id)


def create_thread(payload: dict) -> dict:
    from core.thread_store import create_thread as create, update_thread
    thread = create(_clean_session_messages(payload.get("messages")))
    if isinstance(payload.get("title"), str) and payload["title"].strip():
        return update_thread(thread["id"], {"title": payload["title"]}) or thread
    return thread


def update_thread(thread_id: str, payload: dict) -> dict:
    from core.thread_store import update_thread as update
    updated = update(thread_id, payload)
    if updated is None:
        raise FileNotFoundError(f"thread not found: {thread_id}")
    return updated


def add_thread_session(thread_id: str, payload: dict) -> dict:
    from core.thread_store import add_session_to_thread
    updated = add_session_to_thread(thread_id, str(payload.get("sessionId", "") or "").strip())
    if updated is None:
        raise FileNotFoundError(f"thread not found: {thread_id}")
    return updated


def _add_meta(item: dict, meta: object) -> None:
    if not isinstance(meta, dict):
        return
    for key in ("threadId", "expertId", "expertLabel"):
        value = str(meta.get(key, "") or "").strip()
        if value:
            item[key] = value
