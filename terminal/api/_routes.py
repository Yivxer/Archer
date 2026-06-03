"""Route handler functions and domain logic for the Archer Desktop API."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
import tomllib
import tomli_w

from terminal.api._config import (
    CONFIG_PATH,
    PENDING_TOOL_DRAFTS,
    ROOT,
    get_tool_draft,
    pop_tool_draft,
    set_tool_draft,
    SETTINGS_ALLOWED_FIELDS,
    _clean_session_messages,
    _load_config,
    _mask_key,
    _read_text,
    _valid_session_id,
)
from terminal.api._tools import (
    _append_obsidian_draft,
    _chat,
    _execute_github_operation,
    _execute_shell_command,
)

BACKGROUND_JOBS: dict[str, dict] = {}
BACKGROUND_JOB_LOCK = threading.Lock()
BACKGROUND_JOBS_LOADED = False
BACKGROUND_JOBS_PATH = ROOT / "memory" / "background_jobs.json"
DEFAULT_BACKGROUND_JOB_TIMEOUT_SECONDS = 300


# ---------------------------------------------------------------------------
# Session routes
# ---------------------------------------------------------------------------

def _sessions(limit: int = 20) -> list[dict]:
    from core.session import SESSIONS_DIR
    sessions_dir = Path(SESSIONS_DIR)
    if not sessions_dir.exists():
        return []
    items: list[dict] = []
    for path in sorted(sessions_dir.glob("*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = []
        first_user = next((m.get("content", "") for m in data if m.get("role") == "user"), "")
        title = str(first_user).strip().replace("\n", " ")[:42] or path.stem
        preview = str(first_user).strip().replace("\n", " ")[:60]
        items.append({
            "id": path.stem, "title": title, "date": path.stem[:8],
            "turns": max(1, len(data) // 2), "tone": "saved", "preview": preview,
        })
    return items


def _session_detail(session_id: str) -> dict | None:
    from core.session import SESSIONS_DIR
    if not _valid_session_id(session_id):
        return None
    path = Path(SESSIONS_DIR) / f"{session_id}.json"
    if not path.exists() or not path.is_file():
        return None
    try:
        messages = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        messages = []
    if not isinstance(messages, list):
        messages = []
    clean_messages = []
    for idx, item in enumerate(messages):
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant", "system") or not isinstance(content, str):
            continue
        clean_messages.append({"id": idx + 1, "role": role, "text": content})
    first_user = next((m["text"] for m in clean_messages if m["role"] == "user"), "")
    return {
        "id": session_id,
        "title": first_user.strip().replace("\n", " ")[:42] or session_id,
        "date": session_id[:8],
        "turns": max(1, len(clean_messages) // 2),
        "tone": "saved",
        "messages": clean_messages,
    }


def _save_session(payload: dict) -> dict:
    from core.session import SESSIONS_DIR
    messages = _clean_session_messages(payload.get("messages"))
    sessions_dir = Path(SESSIONS_DIR)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = sessions_dir / f"{session_id}.json"
    counter = 1
    while path.exists():
        path = sessions_dir / f"{session_id}_{counter}.json"
        counter += 1
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": path.stem, "path": str(path), "messages": len(messages)}


def _append_session(session_id: str, payload: dict) -> dict:
    from core.session import SESSIONS_DIR
    if not _valid_session_id(session_id):
        raise ValueError("invalid session id")
    new_messages = _clean_session_messages(payload.get("messages"))
    if len(new_messages) != 2:
        raise ValueError("append requires exactly one user/assistant turn")
    if new_messages[0]["role"] != "user" or new_messages[1]["role"] != "assistant":
        raise ValueError("append messages must be user then assistant")
    path = Path(SESSIONS_DIR) / f"{session_id}.json"
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"session not found: {session_id}")
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        existing = []
    if not isinstance(existing, list):
        existing = []
    existing.extend(new_messages)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": session_id, "path": str(path), "messages": len(existing), "appended": len(new_messages)}


# ---------------------------------------------------------------------------
# Background job routes
# ---------------------------------------------------------------------------

def _clean_job_record(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    job_id = str(raw.get("id", "")).strip()
    title = str(raw.get("title", "")).strip()
    prompt = str(raw.get("prompt", "")).strip()
    if not job_id or not title or not prompt:
        return None
    status = str(raw.get("status", "queued")).strip()
    if status not in {"queued", "running", "waiting_approval", "complete", "failed", "cancelled"}:
        status = "failed"
    created_at = str(raw.get("createdAt", "")).strip() or datetime.now().isoformat()
    updated_at = str(raw.get("updatedAt", "")).strip() or created_at
    job = {
        "id": job_id,
        "title": title,
        "kind": str(raw.get("kind", "analysis")).strip() or "analysis",
        "prompt": prompt,
        "status": status,
        "result": str(raw.get("result", "")),
        "createdAt": created_at,
        "updatedAt": updated_at,
        "timeoutSeconds": _clean_job_timeout(raw.get("timeoutSeconds")),
    }
    if raw.get("error"):
        job["error"] = str(raw.get("error"))
    if status in {"running", "waiting_approval"}:
        job["status"] = "failed"
        job["error"] = "job interrupted by API restart"
        job["updatedAt"] = datetime.now().isoformat()
    return job


def _clean_job_timeout(value: object) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = DEFAULT_BACKGROUND_JOB_TIMEOUT_SECONDS
    return max(1, min(timeout, 3600))


def _load_jobs_locked() -> None:
    global BACKGROUND_JOBS_LOADED
    if BACKGROUND_JOBS_LOADED:
        return
    BACKGROUND_JOBS_LOADED = True
    try:
        data = json.loads(BACKGROUND_JOBS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception:
        return
    raw_jobs = data.get("jobs", []) if isinstance(data, dict) else data
    if not isinstance(raw_jobs, list):
        return
    BACKGROUND_JOBS.clear()
    changed = False
    for raw in raw_jobs:
        job = _clean_job_record(raw)
        if not job:
            changed = True
            continue
        if isinstance(raw, dict) and job.get("status") != raw.get("status"):
            changed = True
        BACKGROUND_JOBS[job["id"]] = job
    if changed:
        _persist_jobs_locked()


def _persist_jobs_locked() -> None:
    jobs = sorted(
        BACKGROUND_JOBS.values(),
        key=lambda job: str(job.get("createdAt", "")),
        reverse=True,
    )
    BACKGROUND_JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = BACKGROUND_JOBS_PATH.with_suffix(f"{BACKGROUND_JOBS_PATH.suffix}.tmp")
    tmp_path.write_text(
        json.dumps({"jobs": jobs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(BACKGROUND_JOBS_PATH)


def _create_job(payload: dict) -> dict:
    from uuid import uuid4

    title = str(payload.get("title", "")).strip()
    kind = str(payload.get("kind", "")).strip() or "analysis"
    prompt = str(payload.get("prompt", "")).strip()
    if not title or not prompt:
        raise ValueError("title and prompt are required")
    timeout_seconds = _clean_job_timeout(payload.get("timeoutSeconds"))

    job_id = f"job-{uuid4().hex[:8]}"
    created_at = datetime.now().isoformat()
    job = {
        "id": job_id,
        "title": title,
        "kind": kind,
        "prompt": prompt,
        "status": "queued",
        "result": "",
        "createdAt": created_at,
        "updatedAt": created_at,
        "timeoutSeconds": timeout_seconds,
    }
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        BACKGROUND_JOBS[job_id] = job
        _persist_jobs_locked()
    response_job = dict(job)
    if payload.get("autoStart", True) is not False:
        _start_job(job_id)
    return {"ok": True, "job": response_job}


def _list_jobs() -> dict:
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        jobs = [dict(job) for job in BACKGROUND_JOBS.values()]
    jobs.sort(key=lambda job: str(job.get("createdAt", "")), reverse=True)
    return {"ok": True, "jobs": jobs}


def _job_detail(job_id: str) -> dict | None:
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        job = BACKGROUND_JOBS.get(job_id)
        return dict(job) if job else None


def _update_job(job_id: str, **updates: object) -> None:
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        job = BACKGROUND_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updatedAt"] = datetime.now().isoformat()
        _persist_jobs_locked()


def _run_job(job_id: str) -> None:
    with BACKGROUND_JOB_LOCK:
        job = dict(BACKGROUND_JOBS.get(job_id) or {})
    if not job:
        return
    _update_job(job_id, status="running")
    result_holder: dict[str, object] = {}

    def _execute_chat() -> None:
        try:
            response = _chat({
                "messages": [
                    {
                        "role": "user",
                        "content": str(job.get("prompt", "")),
                    }
                ]
            })
            result_holder["ok"] = True
            result_holder["text"] = str(response.get("text", "")).strip()
        except Exception as exc:
            result_holder["ok"] = False
            result_holder["error"] = str(exc)

    timeout_seconds = _clean_job_timeout(job.get("timeoutSeconds"))
    chat_thread = threading.Thread(target=_execute_chat, daemon=True)
    chat_thread.start()
    chat_thread.join(timeout=timeout_seconds)

    if chat_thread.is_alive():
        with BACKGROUND_JOB_LOCK:
            current_status = str(BACKGROUND_JOBS.get(job_id, {}).get("status", ""))
        if current_status == "cancelled":
            return
        _update_job(
            job_id,
            status="failed",
            result="",
            error=f"job timed out after {timeout_seconds}s",
        )
        return

    try:
        with BACKGROUND_JOB_LOCK:
            current_status = str(BACKGROUND_JOBS.get(job_id, {}).get("status", ""))
        if current_status == "cancelled":
            return
        if result_holder.get("ok") is True:
            _update_job(job_id, status="complete", result=str(result_holder.get("text", "")))
        else:
            _update_job(job_id, status="failed", result="", error=str(result_holder.get("error", "unknown error")))
    except Exception as exc:
        with BACKGROUND_JOB_LOCK:
            current_status = str(BACKGROUND_JOBS.get(job_id, {}).get("status", ""))
        if current_status == "cancelled":
            return
        _update_job(job_id, status="failed", result="", error=str(exc))


def _start_job(job_id: str) -> None:
    worker = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    worker.start()


def _cancel_job(job_id: str) -> dict:
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        job = BACKGROUND_JOBS.get(job_id)
        if not job:
            return {"ok": False, "error": "job_not_found", "id": job_id}
        if job.get("status") in {"complete", "failed", "cancelled"}:
            return {"ok": True, "job": dict(job), "message": "job already finished"}
        job["status"] = "cancelled"
        job["error"] = "job cancelled by user"
        job["updatedAt"] = datetime.now().isoformat()
        _persist_jobs_locked()
        return {"ok": True, "job": dict(job), "message": "job cancelled"}


def _retry_job(job_id: str) -> dict:
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        job = BACKGROUND_JOBS.get(job_id)
        if not job:
            return {"ok": False, "error": "job_not_found", "id": job_id}
        if job.get("status") in {"queued", "running", "waiting_approval"}:
            return {"ok": True, "job": dict(job), "message": "job is already active"}
        job["status"] = "queued"
        job["result"] = ""
        job.pop("error", None)
        job["updatedAt"] = datetime.now().isoformat()
        _persist_jobs_locked()
        response_job = dict(job)
    _start_job(job_id)
    return {"ok": True, "job": response_job, "message": "job retry queued"}


# ---------------------------------------------------------------------------
# Memory routes
# ---------------------------------------------------------------------------

def _memory(limit: int = 50, include_rejected: bool = False) -> list[dict]:
    from memory.store import init_db, list_all, list_pending
    init_db()
    confirmed = [
        {
            "id": int(item["id"]),
            "status": "confirmed",
            "type": item.get("type", "insight"),
            "content": item.get("content", ""),
            "confidence": f"{float(item.get('confidence') or 0):.2f}",
            "source": item.get("source", ""),
            "depth": int(item.get("depth") or item.get("importance") or 3),
        }
        for item in list_all(limit=limit)
    ]
    pending = [
        {
            "id": int(item["id"]),
            "status": item.get("status", "pending"),
            "type": item.get("type", "insight"),
            "content": item.get("content", ""),
            "confidence": f"{float(item.get('confidence') or 0):.2f}",
            "source": item.get("source", ""),
            "depth": int(item.get("depth") or item.get("importance") or 3),
        }
        for item in list_pending(limit=limit, include_rejected=include_rejected)
    ]
    return [*pending, *confirmed]


def _resolve_pending_memory(memory_id: str, accepted: bool) -> dict:
    from memory.store import accept_pending, reject_pending
    if not re.fullmatch(r"[0-9]+", memory_id):
        raise ValueError("memory id must be numeric")
    if accepted:
        written_ids = accept_pending(int(memory_id))
        if not written_ids:
            return {"ok": False, "id": int(memory_id), "accepted": True, "writtenIds": []}
        return {"ok": True, "id": int(memory_id), "accepted": True, "writtenIds": written_ids}
    deleted = reject_pending(int(memory_id))
    return {"ok": bool(deleted), "id": int(memory_id), "accepted": False, "deleted": deleted}


def _batch_resolve_pending(accepted: bool) -> dict:
    from memory.store import accept_pending, reject_pending
    if accepted:
        written_ids = accept_pending("all")
        return {"ok": True, "accepted": True, "writtenIds": written_ids, "count": len(written_ids)}
    deleted = reject_pending("all")
    return {"ok": True, "accepted": False, "deleted": deleted}


# ---------------------------------------------------------------------------
# Soul import route
# ---------------------------------------------------------------------------

_SOUL_TYPE_MAP = {
    "1": "identity",    # 称呼 → 身份
    "2": "preference",  # 最近常想 → 偏好
    "3": "preference",  # 希望如何 → 偏好
}


def _import_soul(payload: dict) -> dict:
    """导入 Soul JSON 数据，将回答映射为 pending_memories。"""
    soul_data = payload.get("soulData")
    if not isinstance(soul_data, dict):
        raise ValueError("soulData must be an object")

    from memory.store import add_pending
    soul_answers = soul_data.get("soulAnswers", {})
    initial_answers = soul_data.get("initialAnswers", [])
    deep_answers = soul_data.get("deepAnswers", [])

    imported = 0
    pending_ids: list[int] = []

    # 初始3问
    for key, value in soul_answers.items():
        if not isinstance(value, str) or not value.strip():
            continue
        q_map = {"1": "称呼", "2": "最近常想", "3": "希望 Archer 如何对你"}
        question = q_map.get(str(key), f"初始问题 {key}")
        content = f"{question}：{value.strip()}"
        mem_type = _SOUL_TYPE_MAP.get(str(key), "preference")
        pid = add_pending(content, type=mem_type, source="soul-import", confidence=0.9, depth=2)
        imported += 1
        pending_ids.append(pid)

    # 灵魂十问
    for item in initial_answers:
        if not isinstance(item, dict):
            continue
        q = str(item.get("q", "")).strip()
        a = str(item.get("a", "")).strip()
        if not a:
            continue
        content = f"{q}：{a}" if q else a
        pid = add_pending(content, type="preference", source="soul-import", confidence=0.8, depth=3)
        imported += 1
        pending_ids.append(pid)

    # 深度问题
    for item in deep_answers:
        if not isinstance(item, dict):
            continue
        q = str(item.get("q", "")).strip()
        a = str(item.get("a", "")).strip()
        if not a:
            continue
        content = f"{q}：{a}" if q else a
        pid = add_pending(content, type="insight", source="soul-import", confidence=0.7, depth=4)
        imported += 1
        pending_ids.append(pid)

    return {
        "ok": True,
        "imported": imported,
        "pendingIds": pending_ids,
        "message": f"已导入 {imported} 条待确认记忆，来源：soul-import"
    }


# ---------------------------------------------------------------------------
# Skill routes
# ---------------------------------------------------------------------------

def _disabled_skills_path() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "memory", "disabled_skills.json")


def _load_disabled_skills() -> set:
    path = _disabled_skills_path()
    if not os.path.exists(path):
        return set()
    try:
        with open(path) as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def _save_disabled_skills(disabled: set) -> None:
    path = _disabled_skills_path()
    with open(path, "w") as f:
        json.dump(sorted(disabled), f)


def _toggle_skill(name: str, enabled: bool) -> dict:
    disabled = _load_disabled_skills()
    if enabled:
        disabled.discard(name)
    else:
        disabled.add(name)
    _save_disabled_skills(disabled)
    return {"ok": True, "name": name, "enabled": enabled}


def _skills() -> list[dict]:
    from skills.loader import load_skills
    disabled = _load_disabled_skills()
    result = []
    for name, mod in sorted(load_skills().items()):
        meta = getattr(mod, "SKILL", {})
        result.append({
            "name": name,
            "description": meta.get("description", ""),
            "risk": meta.get("risk", "low"),
            "enabled": name not in disabled,
        })
    return result


# ---------------------------------------------------------------------------
# Settings routes
# ---------------------------------------------------------------------------

def _mode_label_from_file(path: Path, fallback: str) -> str:
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        return fallback
    match = re.search(r"[模式：:]\s*([^\\]）\]]+)", first_line)
    return match.group(1).strip() if match else fallback


def _available_modes(cfg: dict) -> dict:
    persona = cfg.get("persona", {})
    current = persona.get("current_mode", persona.get("default_mode", "listener"))
    default = persona.get("default_mode", "listener")
    raw_modes = persona.get("modes", {})
    toml_modes = raw_modes if isinstance(raw_modes, dict) else {}
    modes_dir = Path(str(persona.get("modes_dir", ""))).expanduser()

    items: list[dict] = []
    seen: set[str] = set()
    if modes_dir.is_dir():
        for path in sorted(modes_dir.glob("*.md")):
            mode_id = path.stem
            seen.add(mode_id)
            items.append({
                "id": mode_id,
                "label": _mode_label_from_file(path, mode_id),
                "source": "file",
                "active": mode_id == current,
            })

    for mode_id, meta in sorted(toml_modes.items()):
        if mode_id in seen:
            continue
        label = meta.get("name", mode_id) if isinstance(meta, dict) else mode_id
        items.append({
            "id": mode_id,
            "label": label,
            "source": "toml",
            "active": mode_id == current,
        })

    return {"current": current, "default": default, "modes": items}


def _persist_current_mode(mode: str) -> None:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    new_line = f'current_mode = "{mode}"'
    if re.search(r'^current_mode\s*=', text, re.MULTILINE):
        text = re.sub(r'^current_mode\s*=.*$', new_line, text, flags=re.MULTILINE)
    elif re.search(r'^default_mode\s*=', text, re.MULTILINE):
        text = re.sub(r'^(default_mode\s*=.*)$', rf'\1\n{new_line}', text, flags=re.MULTILINE)
    elif "[persona]" in text:
        text = re.sub(r'^\[persona\]\s*$', f"[persona]\n{new_line}", text, count=1, flags=re.MULTILINE)
    else:
        text = text.rstrip() + f'\n\n[persona]\n{new_line}\n'
    CONFIG_PATH.write_text(text, encoding="utf-8")


def _switch_current_mode(payload: dict, cfg: dict) -> dict:
    mode = str(payload.get("mode", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", mode):
        raise ValueError("mode must be a short identifier")
    available = _available_modes(cfg)
    modes = {item["id"]: item for item in available["modes"]}
    if mode not in modes:
        raise ValueError(f"unknown mode: {mode}")
    _persist_current_mode(mode)
    return {
        "ok": True,
        "current": mode,
        "label": modes[mode]["label"],
        "modes": [{**item, "active": item["id"] == mode} for item in available["modes"]],
    }


def _soul_files(cfg: dict) -> dict:
    persona = cfg.get("persona", {})
    return {
        "SOUL.md": _read_text(persona.get("soul_path")),
        "MEMORY.md": _read_text(persona.get("memory_path")),
        "COVENANT.md": _read_text(persona.get("covenant_path")),
        "PRESENCE.md": _read_text(persona.get("presence_path")),
    }


def _soul_profile_summary(cfg: dict) -> dict:
    from memory.soul_profile import _FIELD_LABELS, load_soul_profile
    from memory.store import list_by_type

    profile = load_soul_profile(cfg.get("persona", {}).get("soul_profile_path"))
    section_fields = [
        "core_values",
        "emotional_patterns",
        "life_themes",
        "creative_identity",
        "current_life_stage",
    ]
    sections = [
        {
            "id": field_name,
            "label": _FIELD_LABELS.get(field_name, field_name),
            "items": list(getattr(profile, field_name, []))[:4],
        }
        for field_name in section_fields
    ]
    growth_markers = [
        item.get("content", "")
        for item in list_by_type("growth_marker", min_importance=1, limit=4)
        if item.get("content")
    ]
    sections.append({
        "id": "growth_markers",
        "label": "成长标记",
        "items": growth_markers,
    })
    return {
        "empty": not any(section["items"] for section in sections),
        "sections": sections,
    }


def _period_review(period: str) -> dict:
    from core.session import SESSIONS_DIR
    from memory.period_review import build_period_review
    from memory.store import DB_PATH

    return build_period_review(
        db_path=Path(DB_PATH),
        sessions_dir=Path(SESSIONS_DIR),
        period=period,
    )


def _journal_review(cfg: dict, days: int) -> dict:
    from memory.journal_review import build_journal_review
    from memory.store import DB_PATH

    return build_journal_review(
        vault_path=cfg.get("obsidian", {}).get("vault_path"),
        db_path=Path(DB_PATH),
        days=days,
    )


def _settings(cfg: dict) -> dict:
    api = cfg.get("api", {})
    memory = cfg.get("memory", {})
    paths = cfg.get("paths", {})
    return {
        "provider": "OpenAI-compatible",
        "baseUrl": api.get("base_url", ""),
        "model": api.get("model", ""),
        "apiKeyPreview": _mask_key(api.get("api_key", "")),
        "configPath": str(CONFIG_PATH),
        "memoryDbPath": memory.get("db_path", ""),
        "sessionsPath": paths.get("sessions_dir", ""),
    }


def _validate_settings_draft(payload: dict) -> dict:
    draft = payload.get("settings")
    if not isinstance(draft, dict):
        raise ValueError("settings must be an object")
    errors: list[str] = []
    allowed: dict[str, str] = {}
    blocked = sorted(key for key in draft.keys() if key not in SETTINGS_ALLOWED_FIELDS and key != "apiKeyPreview")
    for key in sorted(SETTINGS_ALLOWED_FIELDS):
        value = draft.get(key, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            errors.append(f"{key} must be a string")
            continue
        clean = value.strip()
        if len(clean) > 2048:
            errors.append(f"{key} is too long")
            continue
        allowed[key] = clean
    base_url = allowed.get("baseUrl", "")
    if base_url and not re.fullmatch(r"https?://[^\s]+", base_url):
        errors.append("baseUrl must start with http:// or https://")
    model = allowed.get("model", "")
    if model and not re.fullmatch(r"[A-Za-z0-9._:/@+-]{1,160}", model):
        errors.append("model contains unsupported characters")
    for key in ("configPath", "memoryDbPath", "sessionsPath"):
        value = allowed.get(key, "")
        if "\x00" in value:
            errors.append(f"{key} contains an invalid character")
    return {
        "ok": not errors,
        "dryRun": True,
        "writable": False,
        "allowedFields": sorted(SETTINGS_ALLOWED_FIELDS),
        "blockedFields": blocked,
        "errors": errors,
        "message": (
            "settings draft passed validation; archer.toml write is intentionally disabled"
            if not errors
            else "settings draft has validation errors; archer.toml was not changed"
        ),
    }


def _save_settings_draft(payload: dict) -> dict:
    """Validate and save settings draft to archer.toml."""
    validation = _validate_settings_draft(payload)
    if not validation["ok"]:
        return {
            **validation,
            "savedFields": [],
            "restartRequired": False,
            "message": f"验证未通过，未保存；{validation['message']}",
        }
    draft = payload.get("settings", {})
    allowed_fields = validation["allowedFields"]
    backup_path = CONFIG_PATH.with_suffix(".toml.bak")
    if CONFIG_PATH.exists():
        backup_path.write_bytes(CONFIG_PATH.read_bytes())
    try:
        cfg = _load_config()
        if "api" not in cfg:
            cfg["api"] = {}
        if "memory" not in cfg:
            cfg["memory"] = {}
        if "paths" not in cfg:
            cfg["paths"] = {}
        cfg["api"]["base_url"] = draft.get("baseUrl", cfg["api"].get("base_url", ""))
        cfg["api"]["model"] = draft.get("model", cfg["api"].get("model", ""))
        cfg["memory"]["db_path"] = draft.get("memoryDbPath", cfg["memory"].get("db_path", ""))
        cfg["paths"]["sessions_dir"] = draft.get("sessionsPath", cfg["paths"].get("sessions_dir", ""))
        CONFIG_PATH.write_bytes(tomli_w.dumps(cfg))
        try:
            _load_config()
        except Exception as parse_exc:
            if backup_path.exists():
                CONFIG_PATH.write_bytes(backup_path.read_bytes())
            return {
                "ok": False, "savedFields": [], "restartRequired": False,
                "errors": [f"写入后配置文件损坏：{parse_exc}"],
                "message": "保存失败：配置文件写回损坏，已回滚",
            }
        restart_required = bool(
            draft.get("memoryDbPath") or draft.get("configPath") or draft.get("sessionsPath")
        )
        return {
            "ok": True,
            "savedFields": sorted(allowed_fields),
            "restartRequired": restart_required,
            "errors": [],
            "message": f"已保存 {len(allowed_fields)} 个字段到 archer.toml" + ("；需要重启 Archer API" if restart_required else ""),
        }
    except Exception as exc:
        if backup_path.exists():
            CONFIG_PATH.write_bytes(backup_path.read_bytes())
        return {
            "ok": False, "savedFields": [], "restartRequired": False,
            "errors": [str(exc)],
            "message": f"保存失败：{exc}；已回滚到备份",
        }
    finally:
        if backup_path.exists() and CONFIG_PATH.exists():
            try:
                if backup_path.read_bytes() == CONFIG_PATH.read_bytes():
                    backup_path.unlink()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Status route
# ---------------------------------------------------------------------------

def _status(cfg: dict) -> dict:
    memory_items = _memory(limit=100)
    skill_items = _skills()
    auth = cfg.get("auth", {})
    access_token = auth.get("access_token", "")
    archer_id = auth.get("archer_id", "")
    pending = len([m for m in memory_items if m["status"] == "pending"])
    confirmed = len(memory_items) - pending
    return {
        "adapter": "local",
        "model": cfg.get("api", {}).get("model", ""),
        "mode": cfg.get("persona", {}).get("current_mode", "operator"),
        "memoryCount": confirmed,
        "pendingMemoryCount": pending,
        "skillCount": len(skill_items),
        "accountName": cfg.get("account", {}).get("name", ""),
        "isLoggedIn": bool(access_token and archer_id),
        "archerId": archer_id[:8] if archer_id else "",
    }


# ---------------------------------------------------------------------------
# Proactive touch route
# ---------------------------------------------------------------------------

def _proactive_touch(cfg: dict) -> dict:
    from core.proactive import scan_proactive_touch
    from core.session import SESSIONS_DIR
    from memory.store import DB_PATH

    proactive_cfg = cfg.get("proactive", {}) if isinstance(cfg.get("proactive", {}), dict) else {}
    enabled = proactive_cfg.get("enabled", True) is not False
    return {
        "enabled": enabled,
        "items": scan_proactive_touch(DB_PATH, Path(SESSIONS_DIR), cfg=cfg) if enabled else [],
    }


# ---------------------------------------------------------------------------
# Tool approval route
# ---------------------------------------------------------------------------

def _tool_approval(payload: dict) -> dict:
    event_id = str(payload.get("eventId", "")).strip()
    decision = str(payload.get("decision", "")).strip()
    if not event_id:
        raise ValueError("eventId is required")
    if decision not in ("approved", "denied"):
        raise ValueError("decision must be approved or denied")

    draft = get_tool_draft(event_id)
    if draft:
        pop_tool_draft(event_id)
        executed = False
        result_output = ""
        if decision == "approved":
            if draft.get("kind") == "tool_request":
                from core.api_tool_service import execute_tool_request
                from skills.loader import load_skills
                result = execute_tool_request(draft, load_skills(), cfg=_load_config())
                executed = bool(result.get("executed"))
                result_output = str(result.get("output", ""))
                message = result.get("summary") or (
                    "tool executed" if executed else "tool execution failed"
                )
                if executed and draft.get("skillName") == "hugo_blog":
                    args = draft.get("args", {})
                    action = str(args.get("action", ""))
                    if action == "new":
                        try:
                            from skills.hugo_blog import run as hugo_run
                            deploy_result = hugo_run({"action": "deploy"})
                            result_output += "\n\n" + str(deploy_result)
                            if "部署成功" in str(deploy_result):
                                message += " | hugo deploy 已自动执行"
                            else:
                                message += " | hugo deploy 执行完成但可能失败"
                        except Exception as deploy_exc:
                            result_output += f"\n\n部署失败：{deploy_exc}"
                            message += " | 部署失败"
                # 自动跟进：file_ops 写入博客目录后 → hugo build + rsync deploy
                if executed and draft.get("skillName") == "file_ops":
                    args = draft.get("args", {})
                    target_path = str(args.get("path", ""))
                    if "/yivxer-blog/content/posts/" in target_path and args.get("action") == "write":
                        try:
                            from skills.hugo_blog import run as hugo_run
                            deploy_result = hugo_run({"action": "deploy"})
                            result_output += "\n\n" + str(deploy_result)
                            message += " | hugo deploy 已自动执行"
                        except Exception as deploy_exc:
                            result_output += f"\n\n部署失败：{deploy_exc}"
                            message += " | 部署失败"
            elif "path" in draft:  # legacy obsidian_write draft
                result_output = _append_obsidian_draft(draft)
                executed = True
                message = "draft approved and appended to Obsidian"
            elif "command" in draft and "action" not in draft:  # shell.execute draft
                result = _execute_shell_command(draft["command"], draft.get("timeout", 30))
                executed = result["ok"]
                result_output = result["output"]
                message = "shell command executed" if result["ok"] else "shell command failed"
            elif "action" in draft:  # github draft
                result_output = _execute_github_operation(draft)
                executed = True
                message = "github operation executed"
        else:
            message = "draft denied and discarded"
        return {
            "ok": True, "eventId": event_id, "decision": decision,
            "executed": executed, "output": result_output, "message": message,
        }

    return {
        "ok": True, "eventId": event_id, "decision": decision,
        "executed": False,
        "message": "approval recorded; tool execution is not connected in this phase",
    }


# ---------------------------------------------------------------------------
# Route dispatchers
# ---------------------------------------------------------------------------

def payload_get(path: str) -> tuple[int, dict | list]:
    """Handle GET request routing."""
    cfg = _load_config()
    if path == "/status":
        return 200, _status(cfg)
    if path == "/sessions":
        return 200, _sessions()
    if path.startswith("/sessions/"):
        session_id = path.removeprefix("/sessions/")
        detail = _session_detail(session_id)
        if detail is None:
            return 404, {"error": "session_not_found", "id": session_id}
        return 200, detail
    if path == "/memory" or path.startswith("/memory?"):
        include_rejected = "include_rejected=true" in path or "include_rejected=1" in path
        return 200, _memory(include_rejected=include_rejected)
    if path == "/skills":
        return 200, _skills()
    if path == "/modes":
        return 200, _available_modes(cfg)
    if path == "/proactive-touch":
        return 200, _proactive_touch(cfg)
    if path == "/reviews" or path.startswith("/reviews?"):
        match = re.search(r"(?:\?|&)period=([^&]+)", path)
        period = match.group(1) if match else "weekly"
        return 200, _period_review(period)
    if path == "/journal-review" or path.startswith("/journal-review?"):
        match = re.search(r"(?:\?|&)days=([0-9]+)", path)
        days = int(match.group(1)) if match else 30
        return 200, _journal_review(cfg, days)
    if path == "/soul-files":
        return 200, _soul_files(cfg)
    if path == "/memory/stats":
        from memory.store import DB_PATH, count_pending, count_by_groups, count_contradictions, count_stale
        conn = None
        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            active_count = conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'").fetchone()[0]
            rejected_count = conn.execute("SELECT COUNT(*) FROM pending_memories WHERE status = 'rejected'").fetchone()[0]
        except Exception:
            active_count = 0
            rejected_count = 0
        finally:
            if conn:
                conn.close()
        return 200, {
            "dbPath": str(DB_PATH),
            "activeCount": active_count,
            "pendingCount": count_pending(),
            "rejectedCount": rejected_count,
            "groups": count_by_groups(),
            "contradictions": count_contradictions(),
            "stale": count_stale(),
        }
    if path == "/memory/groups":
        from memory.store import MEMORY_GROUPS, count_by_groups, memories_by_group
        groups_data = {}
        counts = count_by_groups()
        for key, group in MEMORY_GROUPS.items():
            groups_data[key] = {
                **group,
                "count": counts.get(key, 0),
                "memories": memories_by_group(key, limit=30),
            }
        return 200, groups_data
    if path == "/soul-profile":
        return 200, _soul_profile_summary(cfg)
    if path == "/settings":
        return 200, _settings(cfg)
    if path == "/health":
        return 200, {"ok": True}
    if path == "/jobs":
        return 200, _list_jobs()
    if path.startswith("/jobs/"):
        job_id = path.removeprefix("/jobs/")
        job = _job_detail(job_id)
        if job is None:
            return 404, {"error": "job_not_found", "id": job_id}
        return 200, {"ok": True, "job": job}
    return 404, {"error": "not_found", "path": path}


def payload_post(path: str, payload: dict) -> tuple[int, dict | list]:
    """Handle POST request routing."""
    if path == "/jobs":
        return 200, _create_job(payload)
    job_cancel = re.fullmatch(r"/jobs/([^/]+)/cancel", path)
    if job_cancel:
        result = _cancel_job(job_cancel.group(1))
        return (200 if result.get("ok") else 404), result
    job_retry = re.fullmatch(r"/jobs/([^/]+)/retry", path)
    if job_retry:
        result = _retry_job(job_retry.group(1))
        return (200 if result.get("ok") else 404), result
    if path == "/chat":
        return 200, _chat(payload)
    if path == "/tool-approvals":
        return 200, _tool_approval(payload)
    if path == "/sessions":
        return 200, _save_session(payload)
    session_append = re.fullmatch(r"/sessions/([^/]+)/append", path)
    if session_append:
        return 200, _append_session(session_append.group(1), payload)
    if path == "/soul/import":
        return 200, _import_soul(payload)
    if path == "/modes/current":
        return 200, _switch_current_mode(payload, _load_config())
    if path == "/settings/validate":
        return 200, _validate_settings_draft(payload)
    if path == "/settings/save":
        return 200, _save_settings_draft(payload)
    match = re.fullmatch(r"/memory/pending/([0-9]+)/(accept|reject)", path)
    if match:
        return 200, _resolve_pending_memory(match.group(1), match.group(2) == "accept")
    batch_match = re.fullmatch(r"/memory/pending/batch/(accept|reject)", path)
    if batch_match:
        return 200, _batch_resolve_pending(batch_match.group(1) == "accept")
    if path == "/skills/toggle":
        name = payload.get("name", "")
        enabled = bool(payload.get("enabled", True))
        if not name:
            return 400, {"error": "name required"}
        return 200, _toggle_skill(name, enabled)
    if path == "/memory/update":
        mid = int(payload.get("id", 0))
        content = str(payload.get("content", "")).strip()
        if not mid or not content:
            return 400, {"error": "id and content required"}
        from memory.store import update_memory_content
        ok = update_memory_content(mid, content)
        return 200, {"ok": ok, "id": mid} if ok else (404, {"error": "memory not found or update failed"})
    if path == "/memory/evolve":
        mid = int(payload.get("id", 0))
        content = str(payload.get("content", "")).strip()
        if not mid or not content:
            return 400, {"error": "id and content required"}
        from memory.store import evolve_memory
        ok = evolve_memory(
            mid, content,
            mtype=payload.get("type"),
            importance=payload.get("importance"),
            depth=payload.get("depth"),
        )
        return 200, {"ok": ok, "id": mid} if ok else (404, {"error": "memory not found or update failed"})
    return 404, {"error": "not_found", "path": path}
