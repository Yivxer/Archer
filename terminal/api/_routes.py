"""Route handler functions and domain logic for the Archer Desktop API."""

from __future__ import annotations

import re
import urllib.parse

from terminal.api._config import (
    CONFIG_PATH,
    _load_config,
    read_tool_approval_audit,
)
from terminal.api._tools import _chat
from terminal.api.job_approval import approve_legacy_job_tool_response
from terminal.api.job_cancellation import request_legacy_job_cancellation_response
from terminal.api.job_retry import retry_legacy_job_response

# ---------------------------------------------------------------------------
# Background job compatibility facade
# ---------------------------------------------------------------------------
from terminal.api.job_routes import (
    BACKGROUND_JOB_LOCK,
    BACKGROUND_JOB_STALE_SECONDS,
    BACKGROUND_JOBS,
    BACKGROUND_JOBS_LOADED,
    BACKGROUND_JOBS_PATH,
    DEFAULT_BACKGROUND_JOB_TIMEOUT_SECONDS,
    _active_child_job_count_locked,
    _can_start_child_job_locked,
    _clean_job_record,
    _clean_job_stale_seconds,
    _clean_job_timeout,
    _create_job,
    _create_job_response,
    _job_detail,
    _job_failure_keyword,
    _kick_queued_children,
    _list_jobs,
    _load_jobs_locked,
    _mark_stale_jobs_locked,
    _parse_job_datetime,
    _pause_job_for_approval,
    _persist_jobs_locked,
    _run_isolated_child_job_chat,
    _run_job,
    _run_job_chat_with_tools,
    _spawn_child_jobs,
    _start_job,
    _try_rollup_parent_result,
    _update_job,
)

# ---------------------------------------------------------------------------
# Memory, Vault Bridge, and sensor compatibility facade
# ---------------------------------------------------------------------------
from terminal.api.memory_routes import (
    _archive_memory,
    _batch_resolve_pending,
    _create_hypothesis,
    _hypotheses,
    _import_obsidian_hypotheses,
    _list_recent_reflections,
    _memory,
    _remember_memory,
    _resolve_pending_memory,
    _sensor_obsidian_focus,
    _sensors_status,
    _vault_current_focus,
    _vault_reflection,
    _vault_refresh_index,
    _vault_search_index,
)

# ---------------------------------------------------------------------------
# Session routes
# ---------------------------------------------------------------------------
# Compatibility aliases: dispatch keeps the historic private names while the
# session/thread implementation lives in its own domain module.
from terminal.api.session_routes import (
    add_thread_session as _add_thread_session,
    append_session as _append_session,
    create_thread as _create_thread,
    delete_session as _delete_session,
    save_session as _save_session,
    session_detail as _session_detail,
    session_meta_from_payload as _session_meta_from_payload,
    sessions as _sessions,
    sessions_search as _sessions_search,
    thread_detail as _thread_detail,
    threads as _threads,
    update_thread as _update_thread,
)

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
# Profiles, settings, and skills compatibility facade
# ---------------------------------------------------------------------------

from terminal.api.profile_routes import (
    _available_experts,
    _available_modes,
    _disabled_skills_path,
    _expert_catalog_items,
    _journal_review,
    _load_disabled_skills,
    _mode_label_from_file,
    _model_test_config_from_draft,
    _period_review,
    _persist_active_profile,
    _persist_current_expert,
    _persist_current_mode,
    _persist_mode_auto,
    _save_disabled_skills,
    _save_profile_settings,
    _save_settings_draft,
    _settings,
    _skills,
    _soul_files,
    _soul_profile_summary,
    _switch_active_profile,
    _switch_current_expert,
    _switch_current_mode,
    _test_model_profile,
    _toggle_skill,
    _validate_settings_draft,
)

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
    persona = cfg.get("persona", {})
    mode_auto = persona.get("mode_auto", True) is not False
    mode = "auto" if mode_auto else persona.get("current_mode", persona.get("default_mode", "listener"))
    from core.experts import active_expert, active_expert_id
    from core.model_profiles import active_model_profile_id
    from core.model_select import status_model_label
    from core.token_usage import status_payload
    token_limit = int(cfg.get("context", {}).get("token_limit", 1_000_000))
    expert = active_expert(cfg)
    from core.persona_sources import persona_source_status

    return {
        "adapter": "local",
        "model": status_model_label(cfg),
        "modelProfile": active_model_profile_id(cfg),
        "expertId": active_expert_id(cfg),
        "expertLabel": str(expert.get("label", "")),
        "mode": mode,
        "memoryCount": confirmed,
        "pendingMemoryCount": pending,
        "skillCount": len(skill_items),
        "accountName": cfg.get("account", {}).get("name", ""),
        "isLoggedIn": bool(access_token and archer_id),
        "archerId": archer_id[:8] if archer_id else "",
        "tokenUsage": status_payload(token_limit=token_limit),
        "persona": persona_source_status(cfg),
    }


# ---------------------------------------------------------------------------
# Part 8 proactive and initiative-shadow compatibility facade
# ---------------------------------------------------------------------------

from terminal.api.initiative_routes import (
    _companion_pending,
    _companion_respond,
    _initiative_delivery_opt_in,
    _initiative_exposure_report,
    _initiative_presence,
    _initiative_review_candidate,
    _initiative_shadow,
    _initiative_shadow_delivery_gate,
    _initiative_shadow_failure,
    _initiative_shadow_feedback,
    _initiative_shadow_long_term_report,
    _initiative_shadow_report,
    _initiative_shadow_review_packet,
    _proactive_touch,
    _safe_initiative_shadow,
)

# ---------------------------------------------------------------------------
# Tool approval compatibility facade
# ---------------------------------------------------------------------------
from terminal.api.tool_approval_routes import (
    IDEMPOTENT_TOOL_SKILLS,
    _build_hugo_approval_draft,
    _finalize_approval,
    _outbox_receipt,
    _prepare_tool_outbox,
    _retry_tool_outbox,
    _run_approved_draft,
    _run_hugo_deploy_followup,
    _tool_approval,
    _tool_draft_from_approval_fallback,
)

# ---------------------------------------------------------------------------
# Route dispatchers
# ---------------------------------------------------------------------------

def payload_get(path: str, runtime_context=None) -> tuple[int, dict | list]:
    """Handle GET request routing."""
    if path == "/health":
        return 200, {"ok": True}
    if path == "/ready":
        from core.persona_sources import persona_source_status

        return 200, {
            "ok": True,
            "ready": True,
            "runtime": "legacy",
            "persona": persona_source_status(_load_config()),
        }
    cfg = _load_config()
    if path == "/status":
        return 200, _status(cfg)
    if path == "/sessions":
        return 200, _sessions()
    if path == "/threads":
        return 200, _threads()
    if path.startswith("/threads/"):
        thread_id = path.removeprefix("/threads/")
        detail = _thread_detail(thread_id)
        if detail is None:
            return 404, {"error": "thread_not_found", "id": thread_id}
        return 200, detail
    if path.startswith("/sessions/search"):
        match = re.search(r"(?:\?|&)q=([^&]*)", path)
        query = match.group(1) if match else ""
        query = urllib.parse.unquote(query)
        return 200, _sessions_search(query)
    if path.startswith("/sessions/"):
        session_id = path.removeprefix("/sessions/")
        detail = _session_detail(session_id)
        if detail is None:
            return 404, {"error": "session_not_found", "id": session_id}
        return 200, detail
    if path == "/memory" or path.startswith("/memory?"):
        include_rejected = "include_rejected=true" in path or "include_rejected=1" in path
        return 200, _memory(include_rejected=include_rejected)
    if path == "/hypotheses" or path.startswith("/hypotheses?"):
        status = "all" if "status=all" in path else "active"
        limit_match = re.search(r"(?:\?|&)limit=([0-9]+)", path)
        limit = int(limit_match.group(1)) if limit_match else 50
        return 200, _hypotheses(limit=limit, status=status)
    if path == "/vault/reflection/recent" or path.startswith("/vault/reflection/recent?"):
        limit_match = re.search(r"(?:\?|&)limit=([0-9]+)", path)
        limit = int(limit_match.group(1)) if limit_match else 20
        return 200, _list_recent_reflections(limit)
    if path == "/vault/current-focus" or path.startswith("/vault/current-focus?"):
        detect = "detect=1" in path or "detect=true" in path.lower()
        return 200, _vault_current_focus(detect=detect)
    if path == "/sensors/status":
        return 200, _sensors_status()
    if path == "/vault/search" or path.startswith("/vault/search?"):
        kw_match = re.search(r"(?:\?|&)q=([^&]+)", path)
        keyword = kw_match.group(1) if kw_match else ""
        from urllib.parse import unquote
        keyword = unquote(keyword)
        limit_match = re.search(r"(?:\?|&)limit=([0-9]+)", path)
        limit = int(limit_match.group(1)) if limit_match else 20
        return 200, _vault_search_index(keyword=keyword, limit=limit)
    if path == "/skills":
        return 200, _skills()
    if path == "/modes":
        return 200, _available_modes(cfg)
    if path == "/experts":
        return 200, _available_experts(cfg)
    if path == "/proactive-touch":
        return 200, _proactive_touch(cfg)
    if path == "/companion/pending":
        return _companion_pending(runtime_context)
    if path == "/initiative-shadow/exposure-report" or path.startswith("/initiative-shadow/exposure-report?"):
        return 200, _initiative_exposure_report(path, runtime_context)
    if path == "/initiative-shadow/long-term-report":
        return 200, _initiative_shadow_long_term_report(runtime_context)
    if path == "/initiative-shadow/delivery-gate":
        return 200, _initiative_shadow_delivery_gate(runtime_context)
    if path == "/initiative-shadow/review-packet":
        return 200, _initiative_shadow_review_packet(runtime_context)
    if path == "/initiative-shadow/report":
        return 200, _initiative_shadow_report(runtime_context)
    if path == "/initiative-shadow" or path.startswith("/initiative-shadow?"):
        return 200, _initiative_shadow(path, runtime_context)
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
        from memory.store import DB_PATH, count_by_groups, count_contradictions, count_pending, count_stale
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
                "memories": [
                    {
                        "id": m["id"],
                        "content": m["content"],
                        "type": m["type"],
                        "importance": m["importance"],
                        "depth": m["depth"],
                        "confidence": m["confidence"],
                        "blockType": m.get("block_type", "insight"),
                        "label": m.get("label", ""),
                    }
                    for m in memories_by_group(key, limit=30)
                ],
            }
        return 200, groups_data
    if path == "/soul-profile":
        return 200, _soul_profile_summary(cfg)
    if path == "/settings":
        return 200, _settings(cfg)
    if path == "/config/doctor":
        from core.doctor import run_config_doctor
        return 200, run_config_doctor(cfg, config_path=CONFIG_PATH)
    if path.startswith("/tool-approval-audit"):
        limit_match = re.search(r"(?:\?|&)limit=([0-9]+)", path)
        limit = int(limit_match.group(1)) if limit_match else 20
        return 200, read_tool_approval_audit(limit)
    if path == "/outbox" or path.startswith("/outbox?"):
        from infrastructure.outbox import list_items
        from memory.store import DB_PATH

        db_path = getattr(runtime_context, "db_path", DB_PATH)
        status_match = re.search(r"(?:\?|&)status=([^&]+)", path)
        statuses = None
        if status_match:
            statuses = {
                value for value in urllib.parse.unquote(status_match.group(1)).split(",") if value
            }
        limit_match = re.search(r"(?:\?|&)limit=([0-9]+)", path)
        limit = int(limit_match.group(1)) if limit_match else 100
        return 200, {
            "ok": True,
            "items": [
                _outbox_receipt(item)
                for item in list_items(db_path, statuses=statuses, limit=limit)
            ],
        }
    if path == "/jobs":
        return 200, _list_jobs()
    if path == "/schedules":
        from terminal.api.schedule_routes import list_schedules
        return 200, list_schedules(runtime_context)
    if path.startswith("/jobs/"):
        job_id = path.removeprefix("/jobs/")
        job = _job_detail(job_id)
        if job is None:
            return 404, {"error": "job_not_found", "id": job_id}
        from terminal.api.job_cutover_shadow import observe_legacy_job_result

        observe_legacy_job_result(runtime_context, {"job": job})
        return 200, {"ok": True, "job": job}
    return 404, {"error": "not_found", "path": path}
def payload_post(path: str, payload: dict, runtime_context=None) -> tuple[int, dict | list]:
    """Handle POST request routing."""
    if path == "/exports/portable":
        from memory.portable_export import write_portable_export
        from memory.store import DB_PATH

        db_path = getattr(runtime_context, "db_path", DB_PATH)
        config = getattr(runtime_context, "config", None) or _load_config()
        output_dir = db_path.parent / "exports" / "portable"
        result = write_portable_export(db_path, config, output_dir)
        return 200, {
            "ok": True,
            "jsonPath": str(result.json_path),
            "markdownPath": str(result.markdown_path),
        }
    initiative_feedback = re.fullmatch(r"/initiative-shadow/([0-9]+)/feedback", path)
    if initiative_feedback:
        return _initiative_shadow_feedback(initiative_feedback.group(1), payload, runtime_context)
    if path == "/initiative-shadow/review-candidate":
        return _initiative_review_candidate(payload, runtime_context)
    if path == "/initiative-shadow/presence":
        return _initiative_presence(payload, runtime_context)
    if path == "/initiative-shadow/opt-in":
        return _initiative_delivery_opt_in(payload, runtime_context)
    companion_response = re.fullmatch(r"/companion/([0-9]+)/respond", path)
    if companion_response:
        return _companion_respond(companion_response.group(1), payload, runtime_context)
    if path == "/jobs":
        return _create_job_response(payload, runtime_context)
    if path == "/schedules":
        from terminal.api.schedule_routes import add_schedule
        status, body = add_schedule(payload, runtime_context)
        return status, body
    schedule_action_match = re.fullmatch(r"/schedules/([0-9]+)/(remove|enable|disable|run)", path)
    if schedule_action_match:
        from terminal.api.schedule_routes import schedule_action
        status, body = schedule_action(
            schedule_action_match.group(1), schedule_action_match.group(2), payload, runtime_context
        )
        return status, body
    job_cancel = re.fullmatch(r"/jobs/([^/]+)/cancel", path)
    if job_cancel:
        return request_legacy_job_cancellation_response(job_cancel.group(1), payload, runtime_context)
    job_retry = re.fullmatch(r"/jobs/([^/]+)/retry", path)
    if job_retry:
        return retry_legacy_job_response(job_retry.group(1), payload, runtime_context)
    job_approve = re.fullmatch(r"/jobs/([^/]+)/approve", path)
    if job_approve:
        return approve_legacy_job_tool_response(job_approve.group(1), payload, runtime_context)
    job_spawn = re.fullmatch(r"/jobs/([^/]+)/spawn", path)
    if job_spawn:
        result = _spawn_child_jobs(job_spawn.group(1), payload)
        return (200 if result.get("ok") else 404), result
    if path == "/chat":
        return 200, _chat(payload)
    if path == "/tool-approvals":
        return 200, _tool_approval(payload, runtime_context)
    outbox_retry = re.fullmatch(r"/outbox/([^/]+)/retry", path)
    if outbox_retry:
        result = _retry_tool_outbox(outbox_retry.group(1), runtime_context)
        return (200 if result.get("ok") else 409), result
    if path == "/sessions":
        return 200, _save_session(payload)
    if path == "/threads":
        return 200, _create_thread(payload)
    thread_add_session = re.fullmatch(r"/threads/([^/]+)/sessions", path)
    if thread_add_session:
        return 200, _add_thread_session(thread_add_session.group(1), payload)
    thread_update = re.fullmatch(r"/threads/([^/]+)", path)
    if thread_update:
        return 200, _update_thread(thread_update.group(1), payload)
    session_append = re.fullmatch(r"/sessions/([^/]+)/append", path)
    if session_append:
        return 200, _append_session(session_append.group(1), payload)
    session_delete = re.fullmatch(r"/sessions/([^/]+)/delete", path)
    if session_delete:
        return 200, _delete_session(session_delete.group(1))
    if path == "/soul/import":
        return 200, _import_soul(payload)
    if path == "/hypotheses":
        try:
            return 200, _create_hypothesis(payload)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
    if path == "/hypotheses/import-obsidian":
        return 200, _import_obsidian_hypotheses(payload, _load_config())
    if path == "/vault/reflection":
        return 200, _vault_reflection(payload)
    if path == "/vault/refresh-index":
        return 200, _vault_refresh_index(force=bool(payload.get("force", False)))
    if path == "/sensors/obsidian/focus":
        return 200, _sensor_obsidian_focus(payload)
    if path == "/modes/current":
        return 200, _switch_current_mode(payload, _load_config())
    if path == "/experts/current":
        try:
            return 200, _switch_current_expert(payload, _load_config())
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
    if path == "/settings/validate":
        return 200, _validate_settings_draft(payload)
    if path == "/settings/save":
        return 200, _save_settings_draft(payload)
    if path == "/settings/profile/save":
        return 200, _save_profile_settings(payload)
    if path == "/settings/profile/switch":
        return 200, _switch_active_profile(payload)
    if path == "/settings/test-model":
        return 200, _test_model_profile(payload, _load_config())
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
    if path == "/memory/remember":
        try:
            return 200, _remember_memory(payload)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
    if path == "/memory/archive":
        try:
            result = _archive_memory(payload)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
        return (200 if result["ok"] else 404), result
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
