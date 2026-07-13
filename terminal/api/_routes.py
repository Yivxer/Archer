"""Route handler functions and domain logic for the Archer Desktop API."""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
import tomllib

from terminal.api._config import (
    CONFIG_PATH,
    PENDING_TOOL_DRAFTS,
    ROOT,
    get_tool_draft,
    get_tool_fingerprint_result,
    get_tool_result,
    pop_tool_draft,
    read_tool_approval_audit,
    record_tool_approval_audit,
    set_tool_fingerprint_result,
    set_tool_result,
    set_tool_draft,
    SETTINGS_ALLOWED_FIELDS,
    _clean_session_messages,
    _load_config,
    _mask_key,
    _read_text,
    tool_request_fingerprint,
    _valid_session_id,
    mutate_config_text,
    write_config_text,
)
from terminal.api._tools import (
    _append_obsidian_draft,
    _chat,
    _execute_github_operation,
    _execute_shell_command,
    _failure_hint_event,
    _run_hugo_publish_workflow,
)
from core.permission_levels import permission_level_for_tool

IDEMPOTENT_TOOL_SKILLS = {"obsidian_write", "hugo_blog", "file_ops"}


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
    session_detail as _session_detail,
    session_meta_from_payload as _session_meta_from_payload,
    sessions as _sessions,
    sessions_search as _sessions_search,
    save_session as _save_session,
    thread_detail as _thread_detail,
    threads as _threads,
    update_thread as _update_thread,
)

# ---------------------------------------------------------------------------
# Background job compatibility facade
# ---------------------------------------------------------------------------

from terminal.api.job_routes import (
    BACKGROUND_JOBS,
    BACKGROUND_JOB_LOCK,
    BACKGROUND_JOBS_LOADED,
    BACKGROUND_JOBS_PATH,
    BACKGROUND_JOB_STALE_SECONDS,
    DEFAULT_BACKGROUND_JOB_TIMEOUT_SECONDS,
    _active_child_job_count_locked,
    _approve_job_tool,
    _can_start_child_job_locked,
    _cancel_job,
    _clean_job_record,
    _clean_job_stale_seconds,
    _clean_job_timeout,
    _create_job,
    _job_detail,
    _job_failure_keyword,
    _kick_queued_children,
    _list_jobs,
    _load_jobs_locked,
    _mark_stale_jobs_locked,
    _parse_job_datetime,
    _pause_job_for_approval,
    _persist_jobs_locked,
    _retry_job,
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
    _batch_resolve_pending,
    _create_hypothesis,
    _hypotheses,
    _import_obsidian_hypotheses,
    _list_recent_reflections,
    _memory,
    _resolve_pending_memory,
    _sensor_obsidian_focus,
    _sensors_status,
    _vault_current_focus,
    _vault_reflection,
    _vault_refresh_index,
    _vault_search_index,
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
    from core.model_select import status_model_label
    from core.model_profiles import active_model_profile_id
    from core.token_usage import status_payload
    token_limit = int(cfg.get("context", {}).get("token_limit", 1_000_000))
    expert = active_expert(cfg)
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


def _initiative_shadow(path: str) -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.initiative_shadow import is_global_throttle_active, list_shadow_logs
        from core.presence import get_presence_state

        limit_match = re.search(r"(?:\?|&)limit=([0-9]+)", path)
        try:
            limit = int(limit_match.group(1)) if limit_match else 20
        except Exception:
            limit = 20
        limit = max(1, min(limit, 100))
        store.init_db()
        return {
            "ok": True,
            "shadow": True,
            "delivered": False,
            "limit": limit,
            "globalThrottleActive": is_global_throttle_active(store.DB_PATH),
            "presenceState": get_presence_state(store.DB_PATH),
            "items": list_shadow_logs(store.DB_PATH, limit=limit),
        }

    return _safe_initiative_shadow("list", _build)


def _initiative_shadow_failure(exc: Exception, *, operation: str) -> dict:
    hint = _failure_hint_event(exc, stage=f"initiative_shadow.{operation}")
    return {
        "ok": False,
        "shadow": True,
        "delivered": False,
        "stage": f"initiative_shadow.{operation}",
        "error": str(exc) or type(exc).__name__,
        "failureKeyword": hint.get("keyword", "runtime_failure"),
        "failureHint": hint,
    }


def _safe_initiative_shadow(operation: str, producer) -> dict:
    try:
        return producer()
    except Exception as exc:
        return _initiative_shadow_failure(exc, operation=operation)


def _initiative_shadow_report() -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_shadow_validation

        store.init_db()
        report = evaluate_shadow_validation(list_shadow_logs(store.DB_PATH, limit=100))
        return {"ok": True, "shadow": True, "report": report.to_dict()}

    return _safe_initiative_shadow("report", _build)


def _initiative_shadow_long_term_report() -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_long_term_validation

        store.init_db()
        report = evaluate_long_term_validation(list_shadow_logs(store.DB_PATH, limit=500))
        return {"ok": True, "shadow": True, "report": report.to_dict()}

    return _safe_initiative_shadow("long_term_report", _build)


def _initiative_shadow_delivery_gate() -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.delivery_opt_in import get_delivery_opt_in
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_delivery_gate, evaluate_long_term_validation, evaluate_shadow_validation

        store.init_db()
        logs = list_shadow_logs(store.DB_PATH, limit=500)
        manual_report = evaluate_shadow_validation(logs)
        long_term_report = evaluate_long_term_validation(logs)
        opt_in = get_delivery_opt_in(store.DB_PATH)
        gate = evaluate_delivery_gate(manual_report, long_term_report, explicit_opt_in=opt_in.enabled)
        return {"ok": True, "shadow": True, "optIn": opt_in.to_dict(), "gate": gate.to_dict()}

    return _safe_initiative_shadow("delivery_gate", _build)


def _initiative_shadow_review_packet() -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.delivery_opt_in import get_delivery_opt_in
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_delivery_gate, evaluate_long_term_validation, evaluate_shadow_validation

        store.init_db()
        logs = list_shadow_logs(store.DB_PATH, limit=500)
        manual_report = evaluate_shadow_validation(logs)
        long_term_report = evaluate_long_term_validation(logs)
        opt_in = get_delivery_opt_in(store.DB_PATH)
        delivery_gate = evaluate_delivery_gate(manual_report, long_term_report, explicit_opt_in=opt_in.enabled)
        recommended_action = "manual_opt_in_available" if delivery_gate.can_enable_delivery else "keep_shadow"
        return {
            "ok": True,
            "shadow": True,
            "optIn": opt_in.to_dict(),
            "recommendedAction": recommended_action,
            "manualReport": manual_report.to_dict(),
            "longTermReport": long_term_report.to_dict(),
            "deliveryGate": delivery_gate.to_dict(),
        }

    return _safe_initiative_shadow("review_packet", _build)


def _initiative_shadow_feedback(log_id: str, payload: dict) -> tuple[int, dict]:
    import memory.store as store
    from core.initiative_shadow import record_shadow_feedback

    feedback = str(payload.get("feedback") or "").strip()
    if feedback not in {"acknowledged", "too_frequent"}:
        return 400, {"ok": False, "error": "feedback must be acknowledged or too_frequent"}
    try:
        numeric_id = int(log_id)
    except ValueError:
        return 400, {"ok": False, "error": "invalid initiative id"}
    ok = record_shadow_feedback(db_path=store.DB_PATH, log_id=numeric_id, feedback=feedback)
    return (200, {"ok": True, "id": numeric_id, "feedback": feedback}) if ok else (404, {"ok": False, "error": "initiative not found"})


def _initiative_presence(payload: dict) -> tuple[int, dict]:
    import memory.store as store
    from core.presence import set_presence_state

    state = str(payload.get("state") or "").strip()
    if state not in {"idle", "muted", "engaged"}:
        return 400, {"ok": False, "error": "state must be idle, engaged, or muted"}
    result = set_presence_state(store.DB_PATH, state)
    return 200, {"ok": True, "state": result.state, "reason": result.reason}


def _initiative_delivery_opt_in(payload: dict) -> tuple[int, dict]:
    import memory.store as store
    from core.delivery_opt_in import set_delivery_opt_in
    from core.initiative_shadow import list_shadow_logs
    from core.shadow_validation import evaluate_delivery_gate, evaluate_long_term_validation, evaluate_shadow_validation

    if "enabled" not in payload or not isinstance(payload.get("enabled"), bool):
        return 400, {"ok": False, "error": "enabled must be a boolean"}
    opt_in = set_delivery_opt_in(
        store.DB_PATH,
        enabled=bool(payload.get("enabled")),
        reason=str(payload.get("reason") or ""),
    )
    logs = list_shadow_logs(store.DB_PATH, limit=500)
    manual_report = evaluate_shadow_validation(logs)
    long_term_report = evaluate_long_term_validation(logs)
    gate = evaluate_delivery_gate(manual_report, long_term_report, explicit_opt_in=opt_in.enabled)
    return 200, {"ok": True, "shadow": True, "optIn": opt_in.to_dict(), "gate": gate.to_dict()}


# ---------------------------------------------------------------------------
# Tool approval route
# ---------------------------------------------------------------------------

def _run_hugo_deploy_followup(*, title: str, deploy_args: dict) -> tuple[str, str]:
    workflow_events, workflow_summary = _run_hugo_publish_workflow(
        title=title,
        actions=[("deploy", deploy_args)],
    )
    deploy_output = ""
    for event in reversed(workflow_events):
        tool_event = event.get("toolEvent", {})
        if tool_event.get("name") == "hugo_blog":
            deploy_output = str(tool_event.get("detail") or "")
            break
    return deploy_output, workflow_summary


def _build_hugo_approval_draft(event_id: str) -> dict:
    from core.api_tool_service import make_tool_request
    from skills.loader import load_skills
    return make_tool_request(
        "hugo_blog", {"action": "deploy"}, load_skills(), cfg=_load_config(),
        event_id=event_id, display_name="hugo_blog",
        extra={"action": "deploy", "title": "部署枫弋札记"}, force_approval=False,
    )


def _run_approved_draft(draft: dict):
    from core.api_tool_service import execute_tool_request
    from skills.loader import load_skills
    from terminal.api.tool_stage import apply_approval_followup, execute_approved_draft
    execution = execute_approved_draft(
        draft,
        execute_tool_request=lambda request: execute_tool_request(
            request, load_skills(), cfg=_load_config()
        ),
        append_obsidian=_append_obsidian_draft,
        execute_shell=_execute_shell_command,
        execute_github=_execute_github_operation,
    )
    return apply_approval_followup(draft, execution, deploy=_run_hugo_deploy_followup)


def _finalize_approval(event_id: str, decision: str, draft: dict, execution, fingerprint: str) -> dict:
    from terminal.api.tool_stage import build_approval_response, persist_approval_response
    permission_level = ""
    if draft.get("kind") == "tool_request":
        args = draft.get("args") if isinstance(draft.get("args"), dict) else {}
        permission_level = permission_level_for_tool(str(draft.get("skillName", "")), args)
    response = build_approval_response(
        event_id=event_id, decision=decision, execution=execution, draft=draft,
        fingerprint=fingerprint, permission_level=permission_level,
    )
    return persist_approval_response(
        response, event_id=event_id, decision=decision, draft=draft,
        fingerprint=fingerprint, record_audit=record_tool_approval_audit,
        set_event_result=set_tool_result, set_fingerprint_result=set_tool_fingerprint_result,
    )


def _tool_approval(payload: dict) -> dict:
    from terminal.api.tool_stage import build_denied_response, parse_approval_decision, reuse_cached_approval
    event_id, decision = parse_approval_decision(payload)

    cached_result = reuse_cached_approval(event_id, get_tool_result)
    if cached_result:
        return cached_result

    from terminal.api.tool_stage import resolve_approval_draft
    draft = resolve_approval_draft(
        event_id,
        payload.get("draftFallback"),
        get_draft=get_tool_draft,
        build_fallback=_tool_draft_from_approval_fallback,
        build_hugo_deploy=_build_hugo_approval_draft,
    )
    if draft:
        pop_tool_draft(event_id)
        from terminal.api.tool_stage import prepare_approval_draft
        prepared = prepare_approval_draft(
            event_id=event_id,
            decision=decision,
            draft=draft,
            idempotent_skills=IDEMPOTENT_TOOL_SKILLS,
            fingerprint_for=tool_request_fingerprint,
            get_fingerprint_result=get_tool_fingerprint_result,
            permission_for=permission_level_for_tool,
        )
        request_fingerprint = prepared.fingerprint
        if prepared.reused_response:
            record_tool_approval_audit(event_id=event_id, decision=decision, draft=draft, response=prepared.reused_response)
            set_tool_result(event_id, prepared.reused_response)
            return prepared.reused_response
        executed = False
        result_output = ""
        work_receipt = None
        if decision == "approved":
            execution = _run_approved_draft(draft)
            executed = execution.executed
            result_output = execution.output
            message = execution.message
            work_receipt = execution.work_receipt
        else:
            response = build_denied_response(event_id)
            record_tool_approval_audit(event_id=event_id, decision=decision, draft=draft, response=response)
            set_tool_result(event_id, response)
            return response
        from terminal.api.tool_stage import ApprovalExecution
        return _finalize_approval(
            event_id, decision, draft,
            ApprovalExecution(executed, result_output, message, work_receipt),
            request_fingerprint,
        )

    return {
        "ok": True, "eventId": event_id, "decision": decision,
        "executed": False,
        "message": (
            "未找到待执行草稿（可能 API 已重启或确认卡已过期）。"
            "请重新说「部署枫弋札记」，或直接点当前确认卡上的发布按钮。"
        ),
    }


def _tool_draft_from_approval_fallback(event_id: str, fallback: object) -> dict | None:
    if not isinstance(fallback, dict):
        return None
    skill_name = str(fallback.get("skillName") or "").strip()
    args = fallback.get("args")
    if not skill_name or not isinstance(args, dict):
        return None

    from core.api_tool_service import make_tool_request
    from skills.loader import load_skills

    skills = load_skills()
    if skill_name not in skills:
        return None
    display_name = str(fallback.get("displayName") or skill_name)
    extra = {
        key: value
        for key, value in fallback.items()
        if key not in {"kind", "eventId", "skillName", "displayName", "args", "argsPreview", "policy", "permissionLevel", "requiresApproval", "blocked"}
    }
    return make_tool_request(
        skill_name,
        args,
        skills,
        cfg=_load_config(),
        event_id=event_id,
        display_name=display_name,
        extra=extra,
        force_approval=False,
    )


# ---------------------------------------------------------------------------
# Route dispatchers
# ---------------------------------------------------------------------------

def payload_get(path: str, runtime_context=None) -> tuple[int, dict | list]:
    """Handle GET request routing."""
    if path == "/health":
        return 200, {"ok": True}
    if path == "/ready":
        return 200, {"ok": True, "ready": True, "runtime": "legacy"}
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
    if path == "/initiative-shadow/long-term-report":
        return 200, _initiative_shadow_long_term_report()
    if path == "/initiative-shadow/delivery-gate":
        return 200, _initiative_shadow_delivery_gate()
    if path == "/initiative-shadow/review-packet":
        return 200, _initiative_shadow_review_packet()
    if path == "/initiative-shadow/report":
        return 200, _initiative_shadow_report()
    if path == "/initiative-shadow" or path.startswith("/initiative-shadow?"):
        return 200, _initiative_shadow(path)
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
        return 200, {"ok": True, "job": job}
    return 404, {"error": "not_found", "path": path}
def payload_post(path: str, payload: dict, runtime_context=None) -> tuple[int, dict | list]:
    """Handle POST request routing."""
    initiative_feedback = re.fullmatch(r"/initiative-shadow/([0-9]+)/feedback", path)
    if initiative_feedback:
        return _initiative_shadow_feedback(initiative_feedback.group(1), payload)
    if path == "/initiative-shadow/presence":
        return _initiative_presence(payload)
    if path == "/initiative-shadow/opt-in":
        return _initiative_delivery_opt_in(payload)
    if path == "/jobs":
        return 200, _create_job(payload)
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
        result = _cancel_job(job_cancel.group(1))
        return (200 if result.get("ok") else 404), result
    job_retry = re.fullmatch(r"/jobs/([^/]+)/retry", path)
    if job_retry:
        result = _retry_job(job_retry.group(1))
        return (200 if result.get("ok") else 404), result
    job_approve = re.fullmatch(r"/jobs/([^/]+)/approve", path)
    if job_approve:
        result = _approve_job_tool(job_approve.group(1), payload)
        return (200 if result.get("ok") else 404), result
    job_spawn = re.fullmatch(r"/jobs/([^/]+)/spawn", path)
    if job_spawn:
        result = _spawn_child_jobs(job_spawn.group(1), payload)
        return (200 if result.get("ok") else 404), result
    if path == "/chat":
        return 200, _chat(payload)
    if path == "/tool-approvals":
        return 200, _tool_approval(payload)
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
