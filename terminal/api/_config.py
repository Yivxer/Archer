"""Shared constants, configuration, and utility functions for the Archer Desktop API."""

from __future__ import annotations

import json
import hashlib
import re
import sys
import time
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
PENDING_TOOL_RESULTS: dict[str, dict] = {}
PENDING_TOOL_FINGERPRINT_RESULTS: dict[str, dict] = {}
_DRAFT_LOCK = threading.Lock()
TOOL_DRAFTS_DIR = Path.home() / "Library/Application Support/archer-desktop/tool-drafts"
TOOL_APPROVAL_AUDIT_LOG_PATH = Path.home() / "Library/Application Support/archer-desktop/tool-approval-audit.jsonl"
from core.cache_policy import CACHE_POLICY

TOOL_DRAFT_TTL_SECONDS = CACHE_POLICY.tool_draft_ttl_seconds
TOOL_RESULT_TTL_SECONDS = CACHE_POLICY.tool_result_ttl_seconds
TOOL_FINGERPRINT_RESULT_TTL_SECONDS = CACHE_POLICY.tool_fingerprint_result_ttl_seconds
CACHE_CREATED_AT_FIELD = "_cacheCreatedAt"


def _draft_path(event_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", event_id)
    return TOOL_DRAFTS_DIR / f"{safe}.json"


def _persist_tool_draft(event_id: str, request: dict) -> None:
    try:
        TOOL_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        _draft_path(event_id).write_text(
            json.dumps(request, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def _load_persisted_tool_draft(event_id: str) -> dict | None:
    path = _draft_path(event_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _delete_persisted_tool_draft(event_id: str) -> None:
    try:
        _draft_path(event_id).unlink(missing_ok=True)
    except OSError:
        pass


def _stamp_cache_entry(entry: dict) -> dict:
    stamped = dict(entry)
    stamped.setdefault(CACHE_CREATED_AT_FIELD, time.time())
    return stamped


def _cache_entry_expired(entry: dict, ttl_seconds: int) -> bool:
    created_at = entry.get(CACHE_CREATED_AT_FIELD)
    if created_at is None:
        return False
    try:
        age = time.time() - float(created_at)
    except (TypeError, ValueError):
        return True
    return age > ttl_seconds


def set_tool_draft(event_id: str, request: dict) -> None:
    stamped = _stamp_cache_entry(request)
    with _DRAFT_LOCK:
        PENDING_TOOL_DRAFTS[event_id] = stamped
    _persist_tool_draft(event_id, stamped)


def get_tool_draft(event_id: str) -> dict | None:
    with _DRAFT_LOCK:
        draft = PENDING_TOOL_DRAFTS.get(event_id)
    if draft:
        if _cache_entry_expired(draft, TOOL_DRAFT_TTL_SECONDS):
            with _DRAFT_LOCK:
                PENDING_TOOL_DRAFTS.pop(event_id, None)
            _delete_persisted_tool_draft(event_id)
            return None
        return draft
    draft = _load_persisted_tool_draft(event_id)
    if draft:
        if _cache_entry_expired(draft, TOOL_DRAFT_TTL_SECONDS):
            _delete_persisted_tool_draft(event_id)
            return None
        with _DRAFT_LOCK:
            PENDING_TOOL_DRAFTS[event_id] = draft
    return draft


def pop_tool_draft(event_id: str) -> dict | None:
    with _DRAFT_LOCK:
        draft = PENDING_TOOL_DRAFTS.pop(event_id, None)
    _delete_persisted_tool_draft(event_id)
    return draft


def get_tool_result(event_id: str) -> dict | None:
    with _DRAFT_LOCK:
        result = PENDING_TOOL_RESULTS.get(event_id)
        if result and _cache_entry_expired(result, TOOL_RESULT_TTL_SECONDS):
            PENDING_TOOL_RESULTS.pop(event_id, None)
            result = None
    return dict(result) if result else None


def set_tool_result(event_id: str, result: dict) -> None:
    stamped = _stamp_cache_entry(result)
    with _DRAFT_LOCK:
        PENDING_TOOL_RESULTS[event_id] = stamped


def tool_request_fingerprint(skill_name: str, args: dict | None) -> str:
    payload = {
        "skillName": str(skill_name or "").strip(),
        "args": _normalize_for_fingerprint(args or {}),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_for_fingerprint(value):
    if isinstance(value, dict):
        return {
            str(key): _normalize_for_fingerprint(value[key])
            for key in sorted(value)
            if str(key) not in {"traceId", "eventId"}
        }
    if isinstance(value, list):
        return [_normalize_for_fingerprint(item) for item in value]
    if isinstance(value, str):
        return value.strip()
    return value


def get_tool_fingerprint_result(fingerprint: str) -> dict | None:
    if not fingerprint:
        return None
    with _DRAFT_LOCK:
        result = PENDING_TOOL_FINGERPRINT_RESULTS.get(fingerprint)
        if result and _cache_entry_expired(result, TOOL_FINGERPRINT_RESULT_TTL_SECONDS):
            PENDING_TOOL_FINGERPRINT_RESULTS.pop(fingerprint, None)
            result = None
    return dict(result) if result else None


def set_tool_fingerprint_result(fingerprint: str, result: dict) -> None:
    if not fingerprint:
        return
    stamped = _stamp_cache_entry(result)
    with _DRAFT_LOCK:
        PENDING_TOOL_FINGERPRINT_RESULTS[fingerprint] = stamped


def record_tool_approval_audit(*, event_id: str, decision: str, draft: dict | None, response: dict) -> None:
    policy = draft.get("policy", {}) if isinstance(draft, dict) else {}
    permission_level = str(response.get("permissionLevel") or (draft or {}).get("permissionLevel") or "")
    record = {
        "timestamp": time.time(),
        "eventId": event_id,
        "decision": decision,
        "skillName": str((draft or {}).get("skillName", "")),
        "risk": str(policy.get("risk", "")),
        "policyDecision": str(policy.get("decision", "")),
        "policyReason": str(policy.get("reason", "")),
        "executed": bool(response.get("executed")),
        "message": str(response.get("message", "")),
        "reused": bool(response.get("reused", False)),
        "fingerprint": str(response.get("fingerprint", "")),
        "idempotencyReason": str(response.get("idempotencyReason", "")),
        "permissionLevel": permission_level,
    }
    try:
        TOOL_APPROVAL_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TOOL_APPROVAL_AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_tool_approval_audit(limit: int = 20) -> dict:
    clean_limit = max(1, min(int(limit or 20), 100))
    records: list[dict] = []
    try:
        lines = TOOL_APPROVAL_AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in reversed(lines):
        if len(records) >= clean_limit:
            break
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return {
        "ok": True,
        "path": str(TOOL_APPROVAL_AUDIT_LOG_PATH),
        "limit": clean_limit,
        "items": records,
    }

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SETTINGS_ALLOWED_FIELDS = {
    "activeProfile",
    "provider",
    "baseUrl",
    "model",
    "apiKey",
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

_CONFIG_LOCK = threading.Lock()


def read_config_text() -> str:
    with _CONFIG_LOCK:
        if not CONFIG_PATH.exists():
            return ""
        return CONFIG_PATH.read_text(encoding="utf-8")


def mutate_config_text(mutator) -> None:
    with _CONFIG_LOCK:
        text = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else ""
        updated = mutator(text)
        tmp_path = CONFIG_PATH.with_suffix(".toml.tmp")
        tmp_path.write_text(updated, encoding="utf-8")
        tmp_path.replace(CONFIG_PATH)


def write_config_text(text: str) -> None:
    mutate_config_text(lambda _current: text)


def _load_config() -> dict:
    with _CONFIG_LOCK:
        try:
            with open(CONFIG_PATH, "rb") as f:
                return tomllib.load(f)
        except FileNotFoundError:
            return {}
        except Exception:
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


def _inject_thread_context(messages: list[dict], raw: object) -> list[dict]:
    if not isinstance(raw, dict):
        return messages
    title = str(raw.get("title", "") or "").strip()
    summary = str(raw.get("summary", "") or "").strip()
    project_summary = str(raw.get("projectSummary", "") or "").strip()
    if not title and not summary and not project_summary:
        return messages
    parts = ["[当前话题上下文]"]
    if title:
        parts.append(f"话题：{title[:120]}")
    if summary:
        parts.append(f"话题记忆：{summary[:1200]}")
    if project_summary:
        parts.append(f"项目记忆：{project_summary[:600]}")
    return [{"role": "system", "content": "\n".join(parts)}] + messages


def _clean_session_messages(raw: object, *, min_messages: int = 2) -> list[dict]:
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
    if len(messages) < min_messages:
        if min_messages <= 1:
            raise ValueError("session must include at least one message")
        raise ValueError("session must include at least two messages")
    return messages
