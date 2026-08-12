"""Background job domain for the Archer Desktop API."""

from __future__ import annotations

import json
import threading
from datetime import datetime

from core.job_execution_adapter import (
    JobCommand,
    JobCommandCollisionError,
    claim_legacy_job_start,
    job_command_id,
    legacy_create_command_identity,
    legacy_job_attempt_identity,
    reconcile_legacy_job_restart,
    restore_legacy_job_command_metadata,
)
from core.job_result_evidence import restore_legacy_job_result_evidence
from core.job_terminal_finalize import JobTerminalFinalizeStaleError
from infrastructure.observability import (
    bind_trace_context,
    clear_trace_context,
    get_logger,
)
from terminal.api import job_approval, job_cancellation
from terminal.api._config import ROOT, _load_config
from terminal.api._tools import _failure_hint_event
from terminal.api.job_result_evidence import complete_legacy_job_result
from terminal.api.job_terminal_finalize import (
    finalize_legacy_job_failure,
    restore_legacy_job_terminal_finalize,
    try_rollup_legacy_parent_result as _try_rollup_parent_result,
)

BACKGROUND_JOBS: dict[str, dict] = {}
BACKGROUND_JOB_LOCK = threading.Lock()
BACKGROUND_JOBS_LOADED = False
BACKGROUND_JOBS_PATH = ROOT / "memory" / "background_jobs.json"
DEFAULT_BACKGROUND_JOB_TIMEOUT_SECONDS = 300
BACKGROUND_JOB_STALE_SECONDS = 15 * 60

_log = get_logger("archer.job")


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
    if raw.get("failureKeyword"):
        job["failureKeyword"] = str(raw.get("failureKeyword"))
    stale_seconds = _clean_job_stale_seconds(raw.get("staleSeconds"))
    if stale_seconds is not None:
        job["staleSeconds"] = stale_seconds
    vault_args = raw.get("vaultArgs")
    if isinstance(vault_args, dict) and vault_args:
        job["vaultArgs"] = vault_args
    restore_legacy_job_command_metadata(raw, job)
    restore_legacy_job_result_evidence(raw, job)
    reconcile_legacy_job_restart(raw, job, reconciled_at=datetime.now().isoformat())
    job_approval.restore_legacy_job_approval(raw, job)
    restore_legacy_job_terminal_finalize(raw, job)
    job_cancellation.restore_legacy_job_cancellation(
        raw, job, reconciled_at=datetime.now().isoformat()
    )
    return job


def _clean_job_timeout(value: object) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = DEFAULT_BACKGROUND_JOB_TIMEOUT_SECONDS
    return max(1, min(timeout, 3600))


def _clean_job_stale_seconds(value: object) -> int | None:
    if value is None:
        return None
    try:
        stale_seconds = int(value)
    except (TypeError, ValueError):
        return None
    return max(1, min(stale_seconds, 24 * 60 * 60))


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


def _parse_job_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _mark_stale_jobs_locked() -> bool:
    now = datetime.now()
    changed = False
    for job in BACKGROUND_JOBS.values():
        if job.get("status") not in {"queued", "running", "waiting_approval"}:
            continue
        updated_at = _parse_job_datetime(job.get("updatedAt"))
        if updated_at is None:
            continue
        stale_seconds = max(1, int(job.get("staleSeconds") or BACKGROUND_JOB_STALE_SECONDS))
        elapsed = (now - updated_at).total_seconds()
        if elapsed <= stale_seconds:
            continue
        job["status"] = "cancelled"
        job["stale"] = True
        job["error"] = f"job stale: no progress for {int(elapsed)}s"
        job["updatedAt"] = now.isoformat()
        changed = True
    if changed:
        _persist_jobs_locked()
    return changed


def _create_job(payload: dict) -> dict:
    from uuid import uuid4

    title = str(payload.get("title", "")).strip()
    kind = str(payload.get("kind", "")).strip() or "analysis"
    prompt = str(payload.get("prompt", "")).strip()
    if not title or not prompt:
        raise ValueError("title and prompt are required")
    timeout_seconds = _clean_job_timeout(payload.get("timeoutSeconds"))
    stale_seconds = _clean_job_stale_seconds(payload.get("staleSeconds"))
    parent_job_id = str(payload.get("parentJobId", "")).strip() or None
    command_id, payload_fingerprint = legacy_create_command_identity(
        payload,
        timeout_seconds=timeout_seconds,
        stale_seconds=stale_seconds,
    )

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
    if stale_seconds is not None:
        job["staleSeconds"] = stale_seconds
    vault_args = payload.get("vaultArgs")
    if isinstance(vault_args, dict) and vault_args:
        job["vaultArgs"] = vault_args
    if command_id and payload_fingerprint:
        job["createCommandId"] = command_id
        job["createPayloadFingerprint"] = payload_fingerprint

    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        if command_id and payload_fingerprint:
            existing = next((
                item for item in BACKGROUND_JOBS.values()
                if item.get("createCommandId") == command_id
            ), None)
            if existing is not None:
                if existing.get("createPayloadFingerprint") != payload_fingerprint:
                    raise JobCommandCollisionError(command_id)
                return {"ok": True, "job": dict(existing), "replayed": True}

        # Link to parent if specified
        if parent_job_id and parent_job_id in BACKGROUND_JOBS:
            parent = BACKGROUND_JOBS[parent_job_id]
            job["parentJobId"] = parent_job_id
            job["isolated"] = True
            child_ids: list = parent.setdefault("childJobIds", [])
            child_ids.append(job_id)
            parent["updatedAt"] = created_at

        BACKGROUND_JOBS[job_id] = job
        _persist_jobs_locked()

    response_job = dict(job)
    if payload.get("autoStart", True) is not False:
        shadow_run_id = str(payload.get("runtimeShadowRunId", "")).strip()
        shadow_step_id = str(payload.get("runtimeShadowStepId", "")).strip()
        start_command_id = (
            job_command_id(
                shadow_run_id,
                shadow_step_id,
                JobCommand.START,
                command_id,
            )
            if command_id and shadow_run_id and shadow_step_id
            else None
        )
        if start_command_id:
            _start_job(
                job_id,
                command_id=start_command_id,
                expected_status="queued",
                expected_updated_at=created_at,
            )
            response_job["startCommandId"] = start_command_id
        else:
            _start_job(job_id)
    return {"ok": True, "job": response_job, "replayed": False}


def _create_job_response(
    payload: dict,
    runtime_context=None,
) -> tuple[int, dict]:
    prepared = payload
    if runtime_context is not None:
        from terminal.api.job_cutover_shadow import prepare_shadow_create_payload

        try:
            prepared = prepare_shadow_create_payload(payload, runtime_context)
        except Exception as exc:
            if (
                str(payload.get("kind", "")).strip() == "vault_reflection"
                and str(payload.get("runtimeShadowRunId", "")).strip()
            ):
                return 409, {
                    "ok": False,
                    "error": "invalid_vault_reflection_shadow_handoff",
                    "message": str(exc),
                }
            prepared = payload
    try:
        return 200, _create_job(prepared)
    except JobCommandCollisionError as exc:
        return 409, {
            "ok": False,
            "error": "job_command_collision",
            "message": str(exc),
            "commandId": exc.command_id,
        }


def _list_jobs() -> dict:
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        _mark_stale_jobs_locked()
        jobs = [dict(job) for job in BACKGROUND_JOBS.values()]
    jobs.sort(key=lambda job: str(job.get("createdAt", "")), reverse=True)
    return {"ok": True, "jobs": jobs}


def _job_detail(job_id: str) -> dict | None:
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        _mark_stale_jobs_locked()
        job = BACKGROUND_JOBS.get(job_id)
        if not job:
            return None
        result = dict(job)
        # Include child job summaries
        child_ids = result.get("childJobIds") or []
        if child_ids:
            children = []
            for cid in child_ids:
                child = BACKGROUND_JOBS.get(cid)
                if child:
                    children.append({
                        "id": child.get("id"),
                        "title": child.get("title"),
                        "status": child.get("status"),
                        "createdAt": child.get("createdAt"),
                        "parentJobId": child.get("parentJobId"),
                        "isolated": child.get("isolated"),
                        "result": child.get("result") or "",
                        "error": child.get("error") or "",
                    })
            if children:
                result["children"] = children
        return result


def _update_job(job_id: str, **updates: object) -> None:
    if updates.get("status") in {"complete", "failed", "cancelled"}:
        raise ValueError("terminal Job state requires terminal finalize authority")
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        job = BACKGROUND_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updatedAt"] = datetime.now().isoformat()
        _persist_jobs_locked()


def _job_failure_keyword(error: object, *, stage: str) -> str:
    exc = error if isinstance(error, Exception) else RuntimeError(str(error or "unknown error"))
    hint = _failure_hint_event(exc, stage=stage)
    return str(hint.get("keyword") or "runtime_failure")


def _finalize_job_failure_safely(
    job_id: str,
    *,
    attempt_id: str,
    error: str,
    failure_keyword: str,
    source: str,
) -> None:
    try:
        finalize_legacy_job_failure(
            job_id,
            error=error,
            failure_keyword=failure_keyword,
            source=source,
            expected_attempt_id=attempt_id,
        )
    except JobTerminalFinalizeStaleError:
        _log.warning(
            "job_failure_finalize_stale",
            job_id=job_id,
            source=source,
        )


def _active_child_job_count_locked() -> int:
    _mark_stale_jobs_locked()
    return sum(
        1
        for job in BACKGROUND_JOBS.values()
        if job.get("parentJobId")
        and job.get("status") in ("running", "waiting_approval")
    )


def _can_start_child_job_locked() -> bool:
    from core.subagent_context import MAX_PARALLEL_CHILD_JOBS

    return _active_child_job_count_locked() < MAX_PARALLEL_CHILD_JOBS


def _kick_queued_children(parent_id: str | None = None) -> None:
    from core.subagent_context import MAX_PARALLEL_CHILD_JOBS

    to_start: list[str] = []
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        slots = MAX_PARALLEL_CHILD_JOBS - _active_child_job_count_locked()
        if slots <= 0:
            return
        queued = [
            job["id"]
            for job in BACKGROUND_JOBS.values()
            if job.get("parentJobId")
            and job.get("status") == "queued"
            and (parent_id is None or job.get("parentJobId") == parent_id)
        ]
        to_start = queued[:slots]
    for child_id in to_start:
        worker = threading.Thread(target=_run_job, args=(child_id,), daemon=True)
        worker.start()


def _run_isolated_child_job_chat(prompt: str, job: dict) -> dict:
    """Execute a child background job with isolated context (no memory, read-only tools)."""
    from core.llm import stream_chat
    from core.subagent_context import (
        build_subagent_system_prompt,
        select_subagent_enrichment_skills,
    )
    from terminal.api.job_enrichment import enrich_with_web_fetch, enrich_with_web_search

    config = _load_config()
    title = str(job.get("title", "")).replace("[子] ", "").strip()
    system = build_subagent_system_prompt(config, title, prompt)
    job_id = str(job.get("id", ""))

    tool_parts: list[str] = []
    system_parts = [system]

    # 子任务隔离模式按 subagent skill selector 选择性执行 web 类只读工具
    for skill_name in select_subagent_enrichment_skills(prompt):
        if skill_name == "web_search":
            ws_sys, ws_tools = enrich_with_web_search(prompt, job_id=job_id)
            system_parts.extend(ws_sys)
            tool_parts.extend(ws_tools)
        elif skill_name == "web_fetch":
            wf_sys, wf_tools = enrich_with_web_fetch(prompt, job_id=job_id)
            system_parts.extend(wf_sys)
            tool_parts.extend(wf_tools)

    messages = [
        {"role": "system", "content": "\n\n".join(system_parts)},
        {"role": "user", "content": prompt},
    ]

    chunks: list[str] = []
    for chunk in stream_chat(messages):
        chunks.append(chunk)
    text = "".join(chunks)

    if tool_parts:
        text += "\n\n---\n*子任务隔离模式自动执行了以下工具：*\n" + "\n".join(f"- {p}" for p in tool_parts)

    return {"role": "assistant", "text": text}


def _run_job_chat_with_tools(prompt: str, job_id: str) -> dict:
    """Execute a background job with tool-loop enrichment.

    Auto-executes low-risk tools (memory, obsidian, web search, web fetch)
    to enrich the context before the LLM call. Reports tool results in the
    response alongside the LLM answer.

    Medium+ risk tools (shell, github, file_ops, obsidian_write, hugo_blog)
    are skipped — they require user approval which isn't available in background.
    """
    from core.subagent_context import is_isolated_job
    from terminal.api.job_enrichment import enrich_context_for_chat

    # structlog contextvars 不跨线程继承，进入工作线程后必须重新 bind
    trace_id = f"trace-{job_id}"
    bind_trace_context(trace_id=trace_id, job_id=job_id, stage="job_chat")
    _log.info("job_chat_start", job_id=job_id, prompt_len=len(prompt))
    try:
        with BACKGROUND_JOB_LOCK:
            job = dict(BACKGROUND_JOBS.get(job_id) or {})
        if is_isolated_job(job):
            _log.info("job_chat_isolated", job_id=job_id)
            return _run_isolated_child_job_chat(prompt, job)

        from core.context import classify_query_intent
        from core.llm import stream_chat
        from terminal.api._tools import _filter_api_skills_for_intent, _select_api_skills

        config = _load_config()
        intent_info = classify_query_intent(prompt)
        selected_skills = _filter_api_skills_for_intent(prompt, _select_api_skills(prompt))

        system_context, tool_parts = enrich_context_for_chat(
            prompt, config, intent_info, selected_skills, job_id=job_id,
        )

        enriched_messages: list[dict] = [{"role": "user", "content": prompt}]
        if system_context:
            enriched_messages = [
                {"role": "system", "content": "\n\n".join(system_context)},
                *enriched_messages,
            ]

        chunks: list[str] = []
        for chunk in stream_chat(enriched_messages):
            chunks.append(chunk)
        text = "".join(chunks)

        if tool_parts:
            text += "\n\n---\n*后台任务自动执行了以下工具：*\n" + "\n".join(f"- {p}" for p in tool_parts)

        _log.info(
            "job_chat_complete", job_id=job_id,
            reply_len=len(text), tool_count=len(tool_parts),
        )
        return {"role": "assistant", "text": text}
    except Exception as exc:
        _log.error("job_chat_failed", job_id=job_id, error=str(exc))
        raise
    finally:
        clear_trace_context("trace_id", "job_id", "stage")


def _run_job(job_id: str) -> None:
    trace_id = f"trace-{job_id}"
    bind_trace_context(trace_id=trace_id, job_id=job_id, stage="job_run")
    _log.info("job_run_start", job_id=job_id)
    try:
        with BACKGROUND_JOB_LOCK:
            job = dict(BACKGROUND_JOBS.get(job_id) or {})
        if not job:
            _log.warning("job_run_missing", job_id=job_id)
            return
        if job_cancellation.job_cancellation_checkpoint(
            job_id,
            stage="before_worker",
            side_effect_started=False,
        ):
            return
        _update_job(job_id, status="running")
        with BACKGROUND_JOB_LOCK:
            current_job = dict(BACKGROUND_JOBS.get(job_id) or {})
        attempt_id, _ = legacy_job_attempt_identity(current_job)
        result_holder: dict[str, object] = {}
        cancel_flag = {"cancelled": False}  # 共享标志，超时后置 True，_execute_chat 内部检查

        def _execute_chat() -> None:
            # structlog contextvars 不跨线程继承，子线程内重新 bind
            bind_trace_context(trace_id=trace_id, job_id=job_id, stage="job_chat")
            try:
                if cancel_flag["cancelled"] or job_cancellation.job_cancellation_checkpoint(job_id, stage="before_model", side_effect_started=False):
                    return  # 超时后不再发起 LLM 调用，避免泄漏 API 配额
                prompt = str(job.get("prompt", ""))
                response = _run_job_chat_with_tools(prompt, job_id)
                if cancel_flag["cancelled"]:
                    return  # LLM 返回后再次检查，避免向已超时任务写入结果
                result_holder["ok"] = True
                result_holder["text"] = str(response.get("text", "")).strip()
            except Exception as exc:
                if not cancel_flag["cancelled"]:
                    result_holder["ok"] = False
                    result_holder["error"] = str(exc)
            finally:
                clear_trace_context("trace_id", "job_id", "stage")

        def _execute_vault_reflection() -> None:
            """后台执行 vault_reflection，不走 LLM 对话链路。"""
            bind_trace_context(trace_id=trace_id, job_id=job_id, stage="vault_reflection")
            try:
                if cancel_flag["cancelled"]:
                    return
                from workflows.vault_reflection import reflect_on_note, reflect_on_recent
                args = job.get("vaultArgs") or {}
                progress_log: list[dict] = []
                def _on_progress(p: dict) -> None:
                    progress_log.append(p)
                    # 实时更新 job 的 progress 字段，供前端轮询
                    try:
                        with BACKGROUND_JOB_LOCK:
                            j = BACKGROUND_JOBS.get(job_id)
                            if j and j.get("status") == "running":
                                j["progress"] = progress_log.copy()
                                j["updatedAt"] = datetime.now().isoformat()
                                _persist_jobs_locked()
                    except Exception:
                        pass
                if args.get("note_path"):
                    result = reflect_on_note(
                        str(args["note_path"]),
                        force=bool(args.get("force", False)),
                    )
                else:
                    result = reflect_on_recent(
                        days=int(args.get("days", 7)),
                        max_notes=int(args.get("maxNotes", 5)),
                        force=bool(args.get("force", False)),
                        progress_callback=_on_progress,
                    )
                if cancel_flag["cancelled"]:
                    return
                result_holder["ok"] = bool(result.get("ok"))
                result_holder["text"] = json.dumps(result, ensure_ascii=False)
                if not result_holder["ok"]:
                    result_holder["error"] = str(
                        result.get("error")
                        or result.get("reason")
                        or "vault reflection failed"
                    )
            except Exception as exc:
                if not cancel_flag["cancelled"]:
                    result_holder["ok"] = False
                    result_holder["error"] = str(exc)
            finally:
                clear_trace_context("trace_id", "job_id", "stage")

        # 按 kind 分派
        job_kind = str(job.get("kind", ""))
        if job_kind == "vault_reflection":
            execute_fn = _execute_vault_reflection
        else:
            execute_fn = _execute_chat

        timeout_seconds = _clean_job_timeout(job.get("timeoutSeconds"))
        chat_thread = threading.Thread(target=execute_fn, daemon=True)
        chat_thread.start()
        wait_outcome = job_cancellation.wait_for_legacy_job_worker(
            job_id,
            chat_thread,
            timeout_seconds=timeout_seconds,
            cancel_flag=cancel_flag,
        )

        if wait_outcome == "cancelled":
            return
        if wait_outcome == "timeout":
            # 超时：设置取消标志，通知 _execute_chat 不再写入结果
            cancel_flag["cancelled"] = True
            with BACKGROUND_JOB_LOCK:
                current_status = str(BACKGROUND_JOBS.get(job_id, {}).get("status", ""))
            if current_status == "cancelled":
                return
            _log.warning("job_run_timeout", job_id=job_id, timeout_seconds=timeout_seconds)
            _finalize_job_failure_safely(
                job_id,
                attempt_id=attempt_id,
                error=f"job timed out after {timeout_seconds}s",
                failure_keyword="command_timeout",
                source="worker_timeout",
            )
            return

        try:
            with BACKGROUND_JOB_LOCK:
                current_status = str(BACKGROUND_JOBS.get(job_id, {}).get("status", ""))
            if current_status == "cancelled":
                return
            if result_holder.get("ok") is True:
                _log.info(
                    "job_run_complete", job_id=job_id,
                    result_len=len(str(result_holder.get("text", ""))),
                )
                complete_legacy_job_result(
                    job_id,
                    str(result_holder.get("text", "")),
                    expected_attempt_id=attempt_id,
                )
            else:
                error = str(result_holder.get("error", "unknown error"))
                _log.warning("job_run_failed", job_id=job_id, error=error)
                _finalize_job_failure_safely(
                    job_id,
                    attempt_id=attempt_id,
                    error=error,
                    failure_keyword=_job_failure_keyword(
                        error,
                        stage="background_job",
                    ),
                    source="worker_error",
                )
        except JobTerminalFinalizeStaleError:
            _log.warning(
                "job_result_finalize_stale",
                job_id=job_id,
                attempt_id=attempt_id,
            )
            return
        except Exception as exc:
            with BACKGROUND_JOB_LOCK:
                current_status = str(BACKGROUND_JOBS.get(job_id, {}).get("status", ""))
            if current_status == "cancelled":
                return
            _log.error("job_run_persist_failed", job_id=job_id, error=str(exc))
            _finalize_job_failure_safely(
                job_id,
                attempt_id=attempt_id,
                error=str(exc),
                failure_keyword=_job_failure_keyword(
                    exc,
                    stage="background_job",
                ),
                source="result_finalize_error",
            )

        parent_id = job.get("parentJobId")
        if parent_id:
            _kick_queued_children(str(parent_id))
            _try_rollup_parent_result(str(parent_id))
    finally:
        clear_trace_context("trace_id", "job_id", "stage")


def _start_job(
    job_id: str,
    *,
    command_id: str | None = None,
    expected_status: str | None = None,
    expected_updated_at: str | None = None,
) -> dict:
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        job = BACKGROUND_JOBS.get(job_id)
        if job and job.get("parentJobId") and not _can_start_child_job_locked():
            return {"ok": True, "job": dict(job), "claimed": False, "reason": "child_limit"}
        claim = claim_legacy_job_start(
            BACKGROUND_JOBS,
            job_id,
            claimed_at=datetime.now().isoformat(),
            command_id=command_id,
            expected_status=expected_status,
            expected_updated_at=expected_updated_at,
        )
        if claim.claimed:
            _persist_jobs_locked()
    if claim.claimed:
        threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return claim.to_dict()


def _pause_job_for_approval(job_id: str, tool_event: dict) -> None:
    """Pause a running job and set it to waiting_approval with the pending tool context."""
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        job = BACKGROUND_JOBS.get(job_id)
        if not job:
            return
        job["status"] = "waiting_approval"
        pending_tool = {
            "eventId": str(tool_event.get("id", "")),
            "toolName": str(tool_event.get("name", "")),
            "displayName": str(tool_event.get("draft", {}).get("displayName", tool_event.get("name", ""))),
            "risk": str(tool_event.get("risk", "medium")),
            "summary": str(tool_event.get("summary", "")),
            "detail": str(tool_event.get("detail", "")),
            "draft": tool_event.get("draft") or {},
            "createdAt": datetime.now().isoformat(),
        }
        pending_tool["fingerprint"] = job_approval.pending_tool_fingerprint(
            pending_tool
        )
        job["pendingTool"] = pending_tool
        job["updatedAt"] = datetime.now().isoformat()
        _persist_jobs_locked()


def _spawn_child_jobs(job_id: str, payload: dict) -> dict:
    """Spawn child jobs linked to a parent job.

    Accepts a list of child job specs: { children: [{title, kind, prompt, autoStart?, timeoutSeconds?}, ...] }
    Each child is created and linked to the parent via parentJobId.
    """
    children_specs = payload.get("children")
    if not children_specs or not isinstance(children_specs, list):
        return {"ok": False, "error": "children must be a non-empty list", "id": job_id}

    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        parent = BACKGROUND_JOBS.get(job_id)
        if not parent:
            return {"ok": False, "error": "parent job not found", "id": job_id}

        child_jobs = []
        start_ids: list[str] = []
        for spec in children_specs[:20]:
            if not isinstance(spec, dict):
                continue
            title = str(spec.get("title", "")).strip()
            prompt = str(spec.get("prompt", "")).strip()
            if not title or not prompt:
                continue
            kind = str(spec.get("kind", "")).strip() or "analysis"
            timeout_seconds = _clean_job_timeout(spec.get("timeoutSeconds"))
            from uuid import uuid4
            child_id = f"job-{uuid4().hex[:8]}"
            created_at = datetime.now().isoformat()
            child = {
                "id": child_id,
                "title": f"[子] {title}",
                "kind": kind,
                "prompt": prompt,
                "status": "queued",
                "result": "",
                "createdAt": created_at,
                "updatedAt": created_at,
                "timeoutSeconds": timeout_seconds,
                "parentJobId": job_id,
                "isolated": True,
            }
            BACKGROUND_JOBS[child_id] = child
            child_ids: list = parent.setdefault("childJobIds", [])
            child_ids.append(child_id)
            child_jobs.append(dict(child))
            if spec.get("autoStart", True) is not False:
                start_ids.append(child_id)

        parent["updatedAt"] = datetime.now().isoformat()
        _persist_jobs_locked()

    for child_id in start_ids:
        _start_job(child_id)

    return {"ok": True, "id": job_id, "spawned": len(child_jobs), "children": child_jobs}


# ---------------------------------------------------------------------------
