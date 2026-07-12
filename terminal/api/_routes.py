"""Route handler functions and domain logic for the Archer Desktop API."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
import tomllib
import tomli_w

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

BACKGROUND_JOBS: dict[str, dict] = {}
BACKGROUND_JOB_LOCK = threading.Lock()
BACKGROUND_JOBS_LOADED = False
BACKGROUND_JOBS_PATH = ROOT / "memory" / "background_jobs.json"
DEFAULT_BACKGROUND_JOB_TIMEOUT_SECONDS = 300
BACKGROUND_JOB_STALE_SECONDS = 15 * 60
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

    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()

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
        _start_job(job_id)
    return {"ok": True, "job": response_job}


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


def _try_rollup_parent_result(parent_id: str) -> bool:
    """Auto-aggregate child results into parent job when all children are done."""
    with BACKGROUND_JOB_LOCK:
        parent = BACKGROUND_JOBS.get(parent_id)
        if not parent:
            return False
        child_ids: list = parent.get("childJobIds") or []
        if not child_ids:
            return False
        for cid in child_ids:
            child = BACKGROUND_JOBS.get(cid)
            if child and child.get("status") in ("queued", "running", "waiting_approval"):
                return False
        lines: list[str] = []
        for cid in child_ids:
            child = BACKGROUND_JOBS.get(cid)
            if not child:
                continue
            title = str(child.get("title", "")).replace("[子] ", "").strip()
            status = str(child.get("status", "?"))
            result = str(child.get("result", "") or "").strip()
            error = str(child.get("error", "") or "").strip()
            lines.append(f"## {title} [{status}]")
            if result:
                lines.append(result)
            elif error:
                lines.append(f"错误：{error}")
            lines.append("")
        parent["result"] = "\n".join(lines).strip()
        parent["status"] = "complete"
        parent["updatedAt"] = datetime.now().isoformat()
        _persist_jobs_locked()
        return True


def _run_isolated_child_job_chat(prompt: str, job: dict) -> dict:
    """Execute a child background job with isolated context (no memory, read-only tools)."""
    from core.llm import stream_chat
    from core.subagent_context import (
        build_subagent_system_prompt,
        select_subagent_enrichment_skills,
    )

    config = _load_config()
    title = str(job.get("title", "")).replace("[子] ", "").strip()
    system = build_subagent_system_prompt(config, title, prompt)

    tool_parts: list[str] = []
    system_parts = [system]

    for skill_name in select_subagent_enrichment_skills(prompt):
        if skill_name == "web_search":
            try:
                from skills.web_search import run as web_search_run

                result = web_search_run({"query": prompt[:200], "max_results": 5})
                if result and not str(result).startswith("未找到"):
                    system_parts.append(f"互联网搜索结果（{prompt[:80]}）：\n{result}")
                    tool_parts.append("[web_search] 搜索完成")
            except Exception as exc:
                tool_parts.append(f"[web_search] 失败: {exc}")
        elif skill_name == "web_fetch":
            url_match = re.search(r'https?://[^\s）)>"\'<\]]+', prompt)
            if url_match:
                target_url = url_match.group(0).rstrip(".。，,;；")
                try:
                    from skills.web_fetch import run as web_fetch_run

                    fetch = web_fetch_run({"url": target_url, "max_chars": 4000})
                    if fetch:
                        system_parts.append(f"网页内容（{target_url}）：\n{fetch}")
                        tool_parts.append(f"[web_fetch] {target_url}")
                except Exception as exc:
                    tool_parts.append(f"[web_fetch] 失败: {exc}")

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

    with BACKGROUND_JOB_LOCK:
        job = dict(BACKGROUND_JOBS.get(job_id) or {})
    if is_isolated_job(job):
        return _run_isolated_child_job_chat(prompt, job)

    from core.context import classify_query_intent
    from core.llm import stream_chat
    from terminal.api._tools import _select_api_skills, _filter_api_skills_for_intent

    config = _load_config()
    intent_info = classify_query_intent(prompt)

    tool_parts: list[str] = []
    enriched_messages: list[dict] = [{"role": "user", "content": prompt}]
    system_context: list[str] = []

    # ── 1. Memory retrieval (conservative mode, limit 5) ──
    try:
        from core.experts import active_expert, expert_memory_tags, format_expert_block
        from memory.retrieve import for_context, format_for_prompt

        expert = active_expert(config)
        expert_block = format_expert_block(expert)
        if expert_block:
            system_context.append(expert_block)

        retrieval_kwargs = {
            "limit": 5,
            "intent": intent_info.get("intent", ""),
            "tag_hints": expert_memory_tags(expert) or None,
        }
        try:
            core, related = for_context(prompt, **retrieval_kwargs)
        except TypeError as exc:
            if "tag_hints" not in str(exc):
                raise
            retrieval_kwargs.pop("tag_hints", None)
            core, related = for_context(prompt, **retrieval_kwargs)
        mem_ctx = format_for_prompt(core, related)
        if mem_ctx:
            system_context.append(
                "以下是 Archer 本地记忆检索结果。只在明显相关时使用。\n\n" + mem_ctx
            )
            tool_parts.append(f"[memory] 检索到 {len(core)}+{len(related)} 条相关记忆")
    except Exception as exc:
        tool_parts.append(f"[memory] 检索失败: {exc}")

    # ── 2. Web search (if skill router detects search intent) ──
    selected_skills = _filter_api_skills_for_intent(prompt, _select_api_skills(prompt))
    if "web_search" in selected_skills:
        try:
            from skills.web_search import run as web_search_run
            result = web_search_run({"query": prompt[:200], "max_results": 5})
            if result and not str(result).startswith("未找到"):
                system_context.append(f"互联网搜索结果（{prompt[:80]}）：\n{result}")
                tool_parts.append("[web_search] 搜索完成")
        except Exception as exc:
            tool_parts.append(f"[web_search] 失败: {exc}")

    if "web_fetch" in selected_skills:
        url_match = __import__("re").search(r'https?://[^\s）)>"\'<\]]+', prompt)
        if url_match:
            target_url = url_match.group(0).rstrip('.。，,;；')
            try:
                from skills.web_fetch import run as web_fetch_run
                fetch = web_fetch_run({"url": target_url, "max_chars": 4000})
                if fetch:
                    system_context.append(f"网页内容（{target_url}）：\n{fetch}")
                    tool_parts.append(f"[web_fetch] {target_url}")
            except Exception as exc:
                tool_parts.append(f"[web_fetch] 失败: {exc}")

    # ── 3. Assemble enriched messages ──
    if system_context:
        enriched_messages = [
            {"role": "system", "content": "\n\n".join(system_context)},
            *enriched_messages,
        ]

    # ── 4. LLM call ──
    chunks: list[str] = []
    for chunk in stream_chat(enriched_messages):
        chunks.append(chunk)
    text = "".join(chunks)

    # ── 5. Append tool summary to response ──
    if tool_parts:
        text += "\n\n---\n*后台任务自动执行了以下工具：*\n" + "\n".join(f"- {p}" for p in tool_parts)

    return {"role": "assistant", "text": text}


def _run_job(job_id: str) -> None:
    with BACKGROUND_JOB_LOCK:
        job = dict(BACKGROUND_JOBS.get(job_id) or {})
    if not job:
        return
    _update_job(job_id, status="running")
    result_holder: dict[str, object] = {}
    cancel_flag = {"cancelled": False}  # 共享标志，超时后置 True，_execute_chat 内部检查

    def _execute_chat() -> None:
        try:
            if cancel_flag["cancelled"]:
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

    def _execute_vault_reflection() -> None:
        """后台执行 vault_reflection，不走 LLM 对话链路。"""
        try:
            if cancel_flag["cancelled"]:
                return
            from workflows.vault_reflection import reflect_on_recent, reflect_on_note
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
        except Exception as exc:
            if not cancel_flag["cancelled"]:
                result_holder["ok"] = False
                result_holder["error"] = str(exc)

    # 按 kind 分派
    job_kind = str(job.get("kind", ""))
    if job_kind == "vault_reflection":
        execute_fn = _execute_vault_reflection
    else:
        execute_fn = _execute_chat

    timeout_seconds = _clean_job_timeout(job.get("timeoutSeconds"))
    chat_thread = threading.Thread(target=execute_fn, daemon=True)
    chat_thread.start()
    chat_thread.join(timeout=timeout_seconds)

    if chat_thread.is_alive():
        # 超时：设置取消标志，通知 _execute_chat 不再写入结果
        cancel_flag["cancelled"] = True
        with BACKGROUND_JOB_LOCK:
            current_status = str(BACKGROUND_JOBS.get(job_id, {}).get("status", ""))
        if current_status == "cancelled":
            return
        _update_job(
            job_id,
            status="failed",
            result="",
            error=f"job timed out after {timeout_seconds}s",
            failureKeyword="command_timeout",
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
            error = str(result_holder.get("error", "unknown error"))
            _update_job(
                job_id,
                status="failed",
                result="",
                error=error,
                failureKeyword=_job_failure_keyword(error, stage="background_job"),
            )
    except Exception as exc:
        with BACKGROUND_JOB_LOCK:
            current_status = str(BACKGROUND_JOBS.get(job_id, {}).get("status", ""))
        if current_status == "cancelled":
            return
        _update_job(
            job_id,
            status="failed",
            result="",
            error=str(exc),
            failureKeyword=_job_failure_keyword(exc, stage="background_job"),
        )

    parent_id = job.get("parentJobId")
    if parent_id:
        _kick_queued_children(str(parent_id))
        _try_rollup_parent_result(str(parent_id))


def _start_job(job_id: str) -> None:
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        job = BACKGROUND_JOBS.get(job_id)
        if job and job.get("parentJobId") and not _can_start_child_job_locked():
            return
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


def _approve_job_tool(job_id: str, payload: dict) -> dict:
    """Approve or deny a pending tool request for a waiting_approval job.

    When approved: execute the tool, update job result with tool output,
    and set status back to running so the job thread can continue.
    When denied: set job status to failed with an appropriate error.
    """
    event_id = str(payload.get("eventId", "")).strip()
    decision = str(payload.get("decision", "")).strip()
    if not event_id:
        return {"ok": False, "error": "eventId is required", "id": job_id}
    if decision not in ("approved", "denied"):
        return {"ok": False, "error": "decision must be approved or denied", "id": job_id}

    # 锁内：读取 pending_tool 并标记为 running，避免长时间持锁阻塞其他任务操作
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        job = BACKGROUND_JOBS.get(job_id)
        if not job:
            return {"ok": False, "error": "job_not_found", "id": job_id}
        if job.get("status") != "waiting_approval":
            return {"ok": True, "job": dict(job), "message": f"job status is {job.get('status')}, not waiting_approval"}

        pending_tool = job.get("pendingTool")
        if not pending_tool or pending_tool.get("eventId") != event_id:
            return {"ok": False, "error": "pending tool not found or eventId mismatch", "id": job_id}

        if decision == "denied":
            job["status"] = "failed"
            job["result"] = ""
            job["error"] = f"tool {pending_tool.get('displayName', 'unknown')} denied by user"
            job.pop("pendingTool", None)
            job["updatedAt"] = datetime.now().isoformat()
            _persist_jobs_locked()
            return {"ok": True, "job": dict(job), "message": "tool denied, job marked failed"}

        # Approved: 标记为 running，锁外执行工具
        tool_name = str(pending_tool.get("toolName", ""))
        draft = pending_tool.get("draft") or {}
        job["status"] = "running"
        job["updatedAt"] = datetime.now().isoformat()
        _persist_jobs_locked()

    # 锁外执行工具：避免 shell/GitHub/Hugo/文件操作长时间阻塞 BACKGROUND_JOB_LOCK
    result_text = ""
    error_text = ""
    try:
        if tool_name == "shell.execute":
            from terminal.api._tools import _execute_shell_command
            output = _execute_shell_command(draft)
            result_text = f"[shell] {output[:500]}"
        elif tool_name == "obsidian_write":
            from terminal.api._tools import _append_obsidian_draft
            target = _append_obsidian_draft(draft)
            result_text = f"[obsidian_write] 已写入: {target}"
        elif tool_name == "github":
            from terminal.api._tools import _execute_github_operation
            output = _execute_github_operation(draft)
            result_text = f"[github] {output[:500]}"
        elif tool_name == "hugo_blog":
            # For hugo_blog, execute deploy action
            action = str((draft.get("args") or {}).get("action", ""))
            if action == "deploy":
                from skills.hugo_blog import run as hugo_blog_run
                output = hugo_blog_run(draft.get("args") or {})
                result_text = f"[hugo_blog] {str(output)[:500]}"
            else:
                result_text = f"[hugo_blog] action={action} approved, check tool output"
        elif tool_name == "file_ops":
            # file_ops: write or create file
            from skills.file_ops import run as file_ops_run
            output = file_ops_run(draft.get("args") or {})
            result_text = f"[file_ops] {str(output)[:500]}"
        else:
            result_text = f"[{tool_name}] tool approved (no auto-executor for this tool type)"
    except Exception as exc:
        error_text = f"tool execution failed: {exc}"

    # 锁内：更新最终结果
    with BACKGROUND_JOB_LOCK:
        job = BACKGROUND_JOBS.get(job_id)
        if job is None:
            # 任务在执行期间被取消/删除
            return {"ok": False, "error": "job_not_found", "id": job_id}
        if error_text:
            job["status"] = "failed"
            job["result"] = ""
            job["error"] = error_text
        else:
            job["status"] = "complete"
            job["result"] = result_text
        job.pop("pendingTool", None)
        job["updatedAt"] = datetime.now().isoformat()
        _persist_jobs_locked()
        return {"ok": True, "job": dict(job), "message": "tool executed" if decision == "approved" else "tool denied"}


def _pause_job_for_approval(job_id: str, tool_event: dict) -> None:
    """Pause a running job and set it to waiting_approval with the pending tool context."""
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
        job = BACKGROUND_JOBS.get(job_id)
        if not job:
            return
        job["status"] = "waiting_approval"
        job["pendingTool"] = {
            "eventId": str(tool_event.get("id", "")),
            "toolName": str(tool_event.get("name", "")),
            "displayName": str(tool_event.get("draft", {}).get("displayName", tool_event.get("name", ""))),
            "risk": str(tool_event.get("risk", "medium")),
            "summary": str(tool_event.get("summary", "")),
            "detail": str(tool_event.get("detail", "")),
            "draft": tool_event.get("draft") or {},
            "createdAt": datetime.now().isoformat(),
        }
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
# Memory routes
# ---------------------------------------------------------------------------

def _memory(limit: int = 50, include_rejected: bool = False) -> list[dict]:
    from memory.store import init_db, list_all, list_pending
    init_db()

    def _item_fields(item: dict, status: str) -> dict:
        return {
            "id": int(item["id"]),
            "status": status,
            "type": item.get("type", "insight"),
            "content": item.get("content", ""),
            "confidence": f"{float(item.get('confidence') or 0):.2f}",
            "source": item.get("source", ""),
            "sessionId": item.get("session_id", "") or "",
            "depth": int(item.get("depth") or item.get("importance") or 3),
            "blockType": item.get("block_type", "insight"),
            "label": item.get("label", ""),
        }

    confirmed = [_item_fields(item, "confirmed") for item in list_all(limit=limit)]
    pending = [
        {
            **_item_fields(item, item.get("status", "pending")),
            "suggestReason": item.get("suggest_reason", ""),
            "sessionSummary": item.get("session_summary", ""),
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


def _hypotheses(limit: int = 50, status: str = "active") -> dict:
    from memory.hypothesis_tracker import list_hypotheses
    from memory.store import init_db

    init_db()
    return {"ok": True, "hypotheses": list_hypotheses(status=status, limit=limit)}


def _create_hypothesis(payload: dict) -> dict:
    from memory.hypothesis_tracker import create_hypothesis, get_hypothesis
    from memory.store import init_db

    init_db()
    title = str(payload.get("title", "") or "").strip()
    statement = str(payload.get("statement", "") or "").strip()
    if not title:
        raise ValueError("title is required")
    if not statement:
        raise ValueError("statement is required")

    hypothesis_id = create_hypothesis(
        title,
        statement,
        source="manual",
        trigger_type=str(payload.get("triggerType", "") or "").strip(),
        confidence=payload.get("confidence", 0.7),
        validate_after_days=payload.get("validateAfterDays", 14),
        session_id=str(payload.get("sessionId", "") or "").strip() or None,
    )
    return {"ok": True, "id": hypothesis_id, "hypothesis": get_hypothesis(hypothesis_id)}


def _import_obsidian_hypotheses(payload: dict, cfg: dict) -> dict:
    from memory.hypothesis_tracker import import_hypotheses_from_obsidian
    from memory.store import init_db

    init_db()
    vault_path = cfg.get("obsidian", {}).get("vault_path", "")
    return import_hypotheses_from_obsidian(
        vault_path,
        days=payload.get("days", 30),
        validate_after_days=payload.get("validateAfterDays", 14),
        limit=payload.get("limit", 20),
    )


def _vault_reflection(payload: dict) -> dict:
    """触发 Vault Bridge 笔记结晶（Phase 2）。

    支持两种模式：
    - path: 对单篇笔记做结晶
    - days: 扫描最近 N 天修改的笔记批量结晶

    当 background=true 时，创建 kind=vault_reflection 的后台 job，立即返回 jobId。
    """
    note_path = (payload.get("path") or "").strip()
    days = payload.get("days")
    force = bool(payload.get("force", False))
    background = bool(payload.get("background", False))

    if background:
        # 后台 job 化：把参数打包进 vaultArgs，由 _run_job 分派到 _execute_vault_reflection
        vault_args: dict = {"force": force}
        if note_path:
            vault_args["note_path"] = note_path
            title = f"Vault 结晶：{Path(note_path).name}"
        elif days is not None:
            try:
                days_int = int(days)
            except (TypeError, ValueError):
                days_int = 7
            try:
                max_notes = int(payload.get("maxNotes", 5))
            except (TypeError, ValueError):
                max_notes = 5
            vault_args["days"] = days_int
            vault_args["maxNotes"] = max_notes
            title = f"Vault 结晶：最近 {days_int} 天"
        else:
            return {"ok": False, "error": "需要 path（单篇笔记）或 days（扫描最近 N 天）参数"}

        create_payload = {
            "title": title,
            "kind": "vault_reflection",
            "prompt": title,  # prompt 必填，vault_reflection 不使用但需通过校验
            "vaultArgs": vault_args,
            "timeoutSeconds": int(payload.get("timeoutSeconds", 600)),
        }
        created = _create_job(create_payload)
        return {"ok": True, "background": True, "job": created.get("job", {})}

    # 同步执行
    from workflows.vault_reflection import reflect_on_note, reflect_on_recent

    if note_path:
        result = reflect_on_note(note_path, force=force)
    elif days is not None:
        try:
            days_int = int(days)
        except (TypeError, ValueError):
            days_int = 7
        try:
            max_notes = int(payload.get("maxNotes", 5))
        except (TypeError, ValueError):
            max_notes = 5
        # 进度回调：记录到日志，便于排查长时间阻塞
        progress_log: list[dict] = []
        def _on_progress(p: dict) -> None:
            progress_log.append(p)
            print(f"[vault_reflection] {p['done']}/{p['total']} {p['note_path']} ok={p['ok']}")
        result = reflect_on_recent(
            days=days_int, max_notes=max_notes, force=force,
            progress_callback=_on_progress,
        )
        result["progress"] = progress_log
    else:
        return {"ok": False, "error": "需要 path（单篇笔记）或 days（扫描最近 N 天）参数"}

    return result


def _list_recent_reflections(limit: int = 20) -> dict:
    """返回最近的 vault_reflection 结晶记录。"""
    from workflows.vault_reflection import list_recent_reflections

    return {"ok": True, "reflections": list_recent_reflections(limit)}


def _vault_refresh_index(force: bool = False) -> dict:
    """刷新 vault 笔记索引。"""
    from knowledge.vault_sensor import refresh_index

    return refresh_index(force=force)


def _vault_current_focus(detect: bool = False) -> dict:
    """获取/检测当前 focus 的笔记。

    detect=True 时主动调用 detect_current_focus()；
    否则返回上次缓存的 focus 状态。
    """
    from knowledge.vault_sensor import get_current_focus, detect_current_focus

    if detect:
        return detect_current_focus()
    return get_current_focus()


def _sensor_obsidian_focus(payload: dict) -> dict:
    """Receive an explicit focus event from an Obsidian sensor/plugin."""
    from knowledge.vault_sensor import ingest_focus_event

    return ingest_focus_event(payload)


def _sensors_status() -> dict:
    from knowledge.vault_sensor import get_current_focus

    return {"ok": True, "obsidian": get_current_focus()}


def _vault_search_index(keyword: str = "", limit: int = 20) -> dict:
    """从索引搜索笔记（不读文件）。"""
    from knowledge.vault_sensor import search_indexed_notes

    return {"ok": True, "notes": search_indexed_notes(keyword=keyword, limit=limit)}


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
    from skills.loader import register_all_skills
    disabled = _load_disabled_skills()
    registry = register_all_skills()
    result = []
    for name, meta in sorted(registry.metas().items()):
        result.append({
            "name": name,
            "description": meta.description,
            "risk": meta.risk,
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
    match = re.search(r"[模式：:]\s*([^）\]]+)", first_line)
    return match.group(1).strip() if match else fallback


def _available_modes(cfg: dict) -> dict:
    persona = cfg.get("persona", {})
    mode_auto = persona.get("mode_auto", True) is not False
    locked = persona.get("current_mode", persona.get("default_mode", "listener"))
    current = "auto" if mode_auto else locked
    default = persona.get("default_mode", "listener")
    raw_modes = persona.get("modes", {})
    toml_modes = raw_modes if isinstance(raw_modes, dict) else {}
    modes_dir_raw = str(persona.get("modes_dir", "") or "").strip()
    modes_dir = Path(modes_dir_raw).expanduser() if modes_dir_raw else None
    try:
        from core.orchestrator import _MODE_LABELS, _VALID_MODES
    except Exception:
        _VALID_MODES = {
            "coach", "mirror", "listener", "questioner", "philosopher", "writer",
            "therapist", "witness", "ritualist", "critic", "builder", "operator",
        }
        _MODE_LABELS = {mode: mode for mode in _VALID_MODES}

    items: list[dict] = []
    seen: set[str] = set()
    if modes_dir and modes_dir.is_dir():
        for path in sorted(modes_dir.glob("*.md")):
            mode_id = path.stem
            if mode_id not in _VALID_MODES and mode_id not in toml_modes:
                continue
            seen.add(mode_id)
            items.append({
                "id": mode_id,
                "label": _mode_label_from_file(path, mode_id),
                "source": "file",
                "active": (not mode_auto) and mode_id == locked,
            })

    for mode_id, meta in sorted(toml_modes.items()):
        if mode_id in seen:
            continue
        seen.add(mode_id)
        label = meta.get("name", mode_id) if isinstance(meta, dict) else mode_id
        items.append({
            "id": mode_id,
            "label": label,
            "source": "toml",
            "active": (not mode_auto) and mode_id == locked,
        })

    for mode_id in sorted(_VALID_MODES):
        if mode_id in seen:
            continue
        items.append({
            "id": mode_id,
            "label": _MODE_LABELS.get(mode_id, mode_id),
            "source": "builtin",
            "active": (not mode_auto) and mode_id == locked,
        })

    return {"current": current, "default": default, "modes": items, "modeAuto": mode_auto}


def _persist_current_mode(mode: str) -> None:
    def _mutate(text: str) -> str:
        new_line = f'current_mode = "{mode}"'
        if re.search(r'^current_mode\s*=', text, re.MULTILINE):
            return re.sub(r'^current_mode\s*=.*$', new_line, text, flags=re.MULTILINE)
        if re.search(r'^default_mode\s*=', text, re.MULTILINE):
            return re.sub(r'^(default_mode\s*=.*)$', rf'\1\n{new_line}', text, flags=re.MULTILINE)
        if "[persona]" in text:
            return re.sub(r'^\[persona\]\s*$', f"[persona]\n{new_line}", text, count=1, flags=re.MULTILINE)
        return text.rstrip() + f'\n\n[persona]\n{new_line}\n'

    mutate_config_text(_mutate)


def _persist_mode_auto(flag: bool) -> None:
    def _mutate(text: str) -> str:
        new_line = f'mode_auto = {"true" if flag else "false"}'
        if re.search(r'^mode_auto\s*=', text, re.MULTILINE):
            return re.sub(r'^mode_auto\s*=.*$', new_line, text, flags=re.MULTILINE)
        if re.search(r'^default_mode\s*=', text, re.MULTILINE):
            return re.sub(r'^(default_mode\s*=.*)$', rf'\1\n{new_line}', text, flags=re.MULTILINE)
        if "[persona]" in text:
            return re.sub(r'^\[persona\]\s*$', f"[persona]\n{new_line}", text, count=1, flags=re.MULTILINE)
        return text.rstrip() + f'\n\n[persona]\n{new_line}\n'

    mutate_config_text(_mutate)


def _persist_current_expert(expert_id: str) -> None:
    def _mutate(text: str) -> str:
        new_line = f'current_expert = "{expert_id}"'
        if re.search(r"^current_expert\s*=", text, re.MULTILINE):
            return re.sub(r"^current_expert\s*=.*$", new_line, text, flags=re.MULTILINE)
        if re.search(r"^default_mode\s*=", text, re.MULTILINE):
            return re.sub(r"^(default_mode\s*=.*)$", rf"\1\n{new_line}", text, flags=re.MULTILINE)
        if "[persona]" in text:
            return re.sub(r"^\[persona\]\s*$", f"[persona]\n{new_line}", text, count=1, flags=re.MULTILINE)
        return text.rstrip() + f"\n\n[persona]\n{new_line}\n"

    mutate_config_text(_mutate)


def _persist_active_profile(profile_id: str) -> None:
    def _mutate(text: str) -> str:
        new_line = f'active_profile = "{profile_id}"'
        if re.search(r"^active_profile\s*=", text, re.MULTILINE):
            return re.sub(r"^active_profile\s*=.*$", new_line, text, flags=re.MULTILINE)
        if re.search(r"^model\s*=", text, re.MULTILINE):
            return re.sub(r"^(model\s*=.*)$", rf"\1\n{new_line}", text, flags=re.MULTILINE, count=1)
        if "[api]" in text:
            return re.sub(r"^\[api\]\s*$", f"[api]\n{new_line}", text, count=1, flags=re.MULTILINE)
        return text.rstrip() + f"\n\n[api]\n{new_line}\n"

    mutate_config_text(_mutate)


def _expert_catalog_items(cfg: dict) -> list[dict]:
    from core.experts import (
        BUILTIN_EXPERT_IDS,
        expert_ids,
        expert_model_configured,
        expert_model_profile_id,
        expert_skill_allowlist,
        expert_starters,
        experts,
    )

    catalog = experts(cfg)
    items = []
    for expert_id in expert_ids(cfg):
        expert = catalog[expert_id]
        allowlist = expert_skill_allowlist(expert)
        source = str(expert.get("source", "builtin") or "builtin")
        items.append({
            "id": expert_id,
            "label": str(expert.get("label", expert_id)),
            "note": str(expert.get("note", "")),
            "modelProfile": expert_model_profile_id(expert),
            "skillCount": len(allowlist) if allowlist else 0,
            "configured": True,
            "modelConfigured": expert_model_configured(cfg, expert),
            "starters": expert_starters(expert),
            "source": source,
            "custom": expert_id not in BUILTIN_EXPERT_IDS,
        })
    return items


def _available_experts(cfg: dict) -> dict:
    from core.experts import active_expert_id

    return {"current": active_expert_id(cfg), "experts": _expert_catalog_items(cfg)}


def _switch_current_expert(payload: dict, cfg: dict) -> dict:
    from core.experts import (
        active_expert_id,
        expert_ids,
        expert_model_profile_id,
        experts,
    )

    expert_id = str(payload.get("expert", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", expert_id):
        raise ValueError("expert must be a short identifier")
    if expert_id not in expert_ids(cfg):
        raise ValueError(f"unknown expert: {expert_id}")

    catalog = experts(cfg)
    expert = catalog[expert_id]
    model_profile = expert_model_profile_id(expert)

    _persist_current_expert(expert_id)
    label = str(expert.get("label", expert_id))
    return {
        "ok": True,
        "current": expert_id,
        "label": label,
        "modelProfile": model_profile,
        "recommendedModelProfile": model_profile,
        "previous": active_expert_id(cfg),
    }


def _switch_current_mode(payload: dict, cfg: dict) -> dict:
    mode = str(payload.get("mode", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", mode):
        raise ValueError("mode must be a short identifier")
    available = _available_modes(cfg)
    # 特殊值 "auto"：恢复每轮自动选择姿态
    if mode == "auto":
        _persist_mode_auto(True)
        return {
            "ok": True,
            "current": "auto",
            "label": "自动",
            "modes": [{**item, "active": False} for item in available["modes"]],
        }
    modes = {item["id"]: item for item in available["modes"]}
    if mode not in modes:
        raise ValueError(f"unknown mode: {mode}")
    _persist_current_mode(mode)
    _persist_mode_auto(False)
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
        "rhythm",
        "narrative",
        "tensions",
        "patterns",
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
    from core.experts import active_expert_id
    from core.model_profiles import active_api_config, active_model_profile_id, model_profiles
    api = active_api_config(cfg)
    profiles = model_profiles(cfg)
    memory = cfg.get("memory", {})
    paths = cfg.get("paths", {})
    return {
        "activeProfile": active_model_profile_id(cfg),
        "activeExpert": active_expert_id(cfg),
        "experts": _expert_catalog_items(cfg),
        "modelProfiles": [
            {
                "id": profile_id,
                "label": str(profile.get("label", profile_id)),
                "provider": str(profile.get("provider", "")),
                "baseUrl": str(profile.get("base_url", "")),
                "model": str(profile.get("model", "")),
                "apiKeyPreview": _mask_key(str(profile.get("api_key", ""))),
                "configured": bool(profile.get("base_url") and profile.get("model") and profile.get("api_key")),
            }
            for profile_id, profile in profiles.items()
        ],
        "provider": api.get("provider", "OpenAI-compatible"),
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
    active_profile = allowed.get("activeProfile", "")
    if active_profile and active_profile not in ("lite", "pro", "max"):
        errors.append("activeProfile must be lite, pro, or max")
    model = allowed.get("model", "")
    if model and not re.fullmatch(r"[A-Za-z0-9._:/@+-]{1,160}", model):
        errors.append("model contains unsupported characters")
    api_key = allowed.get("apiKey", "")
    if api_key and ("\n" in api_key or "\r" in api_key):
        errors.append("apiKey must be a single line")
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
        if not isinstance(cfg.get("model_profiles"), dict):
            cfg["model_profiles"] = {}
        if "memory" not in cfg:
            cfg["memory"] = {}
        if "paths" not in cfg:
            cfg["paths"] = {}
        active_profile = draft.get("activeProfile", cfg["api"].get("active_profile", "lite")) or "lite"
        cfg["api"]["active_profile"] = active_profile
        profile_cfg = cfg["model_profiles"].setdefault(active_profile, {})
        profile_cfg["provider"] = draft.get("provider", profile_cfg.get("provider", ""))
        profile_cfg["base_url"] = draft.get("baseUrl", profile_cfg.get("base_url", ""))
        profile_cfg["model"] = draft.get("model", profile_cfg.get("model", ""))
        api_key = str(draft.get("apiKey", "") or "").strip()
        if api_key:
            profile_cfg["api_key"] = api_key
        cfg["api"]["base_url"] = draft.get("baseUrl", cfg["api"].get("base_url", ""))
        cfg["api"]["model"] = draft.get("model", cfg["api"].get("model", ""))
        if api_key:
            cfg["api"]["api_key"] = api_key
        cfg["memory"]["db_path"] = draft.get("memoryDbPath", cfg["memory"].get("db_path", ""))
        cfg["paths"]["sessions_dir"] = draft.get("sessionsPath", cfg["paths"].get("sessions_dir", ""))
        write_config_text(tomli_w.dumps(cfg))
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


def _save_profile_settings(payload: dict) -> dict:
    """独立保存单个 model profile 的配置，不影响其他 profile。

    payload 结构：
    {
        "profileId": "lite" | "pro" | "max",
        "provider": "...",
        "baseUrl": "...",
        "model": "...",
        "apiKey": "..."  # 空字符串表示不更新 key
    }
    """
    from core.model_profiles import MODEL_PROFILE_IDS

    profile_id = str(payload.get("profileId", "") or "").strip().lower()
    if profile_id not in MODEL_PROFILE_IDS:
        return {"ok": False, "error": f"无效的 profileId: {profile_id}"}

    backup_path = CONFIG_PATH.with_suffix(".toml.bak")
    if CONFIG_PATH.exists():
        backup_path.write_bytes(CONFIG_PATH.read_bytes())
    try:
        cfg = _load_config()
        if not isinstance(cfg.get("model_profiles"), dict):
            cfg["model_profiles"] = {}
        profile_cfg = cfg["model_profiles"].setdefault(profile_id, {})

        # 只更新非空字段，空字段保留原值（避免清空已有配置）
        provider = str(payload.get("provider", "") or "").strip()
        base_url = str(payload.get("baseUrl", "") or "").strip()
        model = str(payload.get("model", "") or "").strip()
        api_key = str(payload.get("apiKey", "") or "").strip()

        if provider:
            profile_cfg["provider"] = provider
        if base_url:
            profile_cfg["base_url"] = base_url
        if model:
            profile_cfg["model"] = model
        if api_key:
            profile_cfg["api_key"] = api_key

        # 如果保存的是当前 active profile，同步更新 [api] 段
        active_profile = str(cfg.get("api", {}).get("active_profile", "lite"))
        if active_profile == profile_id:
            if base_url:
                cfg["api"]["base_url"] = base_url
            if model:
                cfg["api"]["model"] = model
            if api_key:
                cfg["api"]["api_key"] = api_key

        write_config_text(tomli_w.dumps(cfg))
        try:
            _load_config()
        except Exception as parse_exc:
            if backup_path.exists():
                CONFIG_PATH.write_bytes(backup_path.read_bytes())
            return {
                "ok": False,
                "error": f"写入后配置文件损坏：{parse_exc}，已回滚",
            }
        return {
            "ok": True,
            "profileId": profile_id,
            "message": f"已保存 {profile_id} 配置",
        }
    except Exception as exc:
        if backup_path.exists():
            CONFIG_PATH.write_bytes(backup_path.read_bytes())
        return {"ok": False, "error": f"保存失败：{exc}，已回滚"}
    finally:
        if backup_path.exists() and CONFIG_PATH.exists():
            try:
                if backup_path.read_bytes() == CONFIG_PATH.read_bytes():
                    backup_path.unlink()
            except Exception:
                pass


def _switch_active_profile(payload: dict) -> dict:
    """只切换 active_profile，不修改任何 profile 的配置。

    会从目标 profile 同步 base_url/model/api_key 到 [api] 段（仅当 profile 中存在该字段时），
    确保 legacy 代码读取 [api] 段时拿到的是新 profile 的配置。
    不会删除或覆盖任何 [model_profiles.*] 段的内容。
    """
    from core.model_profiles import MODEL_PROFILE_IDS, model_profiles

    profile_id = str(payload.get("profileId", "") or "").strip().lower()
    if profile_id not in MODEL_PROFILE_IDS:
        return {"ok": False, "error": f"无效的 profileId: {profile_id}"}

    backup_path = CONFIG_PATH.with_suffix(".toml.bak")
    if CONFIG_PATH.exists():
        backup_path.write_bytes(CONFIG_PATH.read_bytes())
    try:
        cfg = _load_config()
        if "api" not in cfg or not isinstance(cfg.get("api"), dict):
            cfg["api"] = {}
        cfg["api"]["active_profile"] = profile_id

        # 从已解析的 profile 同步字段到 [api] 段（仅当 profile 有该字段且非空时）
        profiles = model_profiles(cfg)
        target = profiles.get(profile_id, {})
        for key in ("provider", "base_url", "model", "api_key", "vision_model"):
            val = target.get(key)
            if val not in ("", None):
                cfg["api"][key] = val

        write_config_text(tomli_w.dumps(cfg))
        try:
            _load_config()
        except Exception as parse_exc:
            if backup_path.exists():
                CONFIG_PATH.write_bytes(backup_path.read_bytes())
            return {"ok": False, "error": f"写入后配置文件损坏：{parse_exc}，已回滚"}
        return {
            "ok": True,
            "profileId": profile_id,
            "activeProfile": profile_id,
            "message": f"已切换到 {profile_id}",
        }
    except Exception as exc:
        if backup_path.exists():
            CONFIG_PATH.write_bytes(backup_path.read_bytes())
        return {"ok": False, "error": f"切换失败：{exc}，已回滚"}
    finally:
        if backup_path.exists() and CONFIG_PATH.exists():
            try:
                if backup_path.read_bytes() == CONFIG_PATH.read_bytes():
                    backup_path.unlink()
            except Exception:
                pass


def _model_test_config_from_draft(payload: dict, cfg: dict) -> dict:
    from core.model_profiles import active_api_config, active_model_profile_id, cfg_with_active_api

    draft = payload.get("settings")
    if not isinstance(draft, dict):
        raise ValueError("settings must be an object")
    validation = _validate_settings_draft(payload)
    if not validation["ok"]:
        return {"ok": False, "errors": validation["errors"]}

    test_cfg = dict(cfg)
    api = dict(test_cfg.get("api", {}) if isinstance(test_cfg.get("api"), dict) else {})
    active_profile = str(draft.get("activeProfile") or api.get("active_profile") or "lite")
    api["active_profile"] = active_profile
    test_cfg["api"] = api

    current_profile = active_model_profile_id(cfg)
    current_api = active_api_config(cfg)
    profiles = dict(test_cfg.get("model_profiles", {}) if isinstance(test_cfg.get("model_profiles"), dict) else {})
    profile = dict(profiles.get(active_profile, {}) if isinstance(profiles.get(active_profile), dict) else {})
    draft_profiles = draft.get("modelProfiles")
    if isinstance(draft_profiles, list):
        for item in draft_profiles:
            if not isinstance(item, dict) or str(item.get("id", "")).strip().lower() != active_profile:
                continue
            for draft_key, profile_key in (("provider", "provider"), ("baseUrl", "base_url"), ("model", "model")):
                value = str(item.get(draft_key, "") or "").strip()
                if value:
                    profile[profile_key] = value
            break
    for draft_key, profile_key in (("provider", "provider"), ("baseUrl", "base_url"), ("model", "model"), ("apiKey", "api_key")):
        value = str(draft.get(draft_key, "") or "").strip()
        if value:
            if (
                profile_key != "api_key"
                and active_profile != current_profile
                and value == str(current_api.get(profile_key, "") or "").strip()
            ):
                continue
            profile[profile_key] = value
    profiles[active_profile] = profile
    test_cfg["model_profiles"] = profiles
    return cfg_with_active_api(test_cfg)


def _test_model_profile(payload: dict, cfg: dict) -> dict:
    test_cfg = _model_test_config_from_draft(payload, cfg)
    if test_cfg.get("ok") is False:
        return {
            "ok": False,
            "profile": "",
            "provider": "",
            "model": "",
            "baseUrl": "",
            "latencyMs": 0,
            "message": "模型配置校验失败",
            "errors": test_cfg.get("errors", []),
        }

    api = test_cfg["api"]
    profile = str(api.get("active_profile", "lite"))
    provider = str(api.get("provider", ""))
    base_url = str(api.get("base_url", ""))
    model = str(api.get("model", ""))
    api_key = str(api.get("api_key", ""))
    missing = [
        name
        for name, value in (("baseUrl", base_url), ("model", model), ("apiKey", api_key))
        if not value
    ]
    if missing:
        return {
            "ok": False,
            "profile": profile,
            "provider": provider,
            "model": model,
            "baseUrl": base_url,
            "latencyMs": 0,
            "message": f"缺少字段：{', '.join(missing)}",
            "errors": [f"missing {name}" for name in missing],
        }

    try:
        from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
    except Exception as exc:
        return {
            "ok": False,
            "profile": profile,
            "provider": provider,
            "model": model,
            "baseUrl": base_url,
            "latencyMs": 0,
            "message": f"OpenAI SDK 不可用：{exc}",
            "errors": [str(exc)],
        }

    started = time.perf_counter()
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=20, max_retries=0)
        temperature = 1 if "moonshot." in base_url.lower() else 0
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
            temperature=temperature,
            stream=False,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        content = response.choices[0].message.content if response.choices else ""
        return {
            "ok": True,
            "profile": profile,
            "provider": provider,
            "model": model,
            "baseUrl": base_url,
            "latencyMs": latency_ms,
            "message": "模型连接测试通过",
            "sample": (content or "").strip()[:40],
            "errors": [],
        }
    except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "profile": profile,
            "provider": provider,
            "model": model,
            "baseUrl": base_url,
            "latencyMs": latency_ms,
            "message": f"模型连接测试失败：{exc.__class__.__name__}",
            "errors": [str(exc)[:500]],
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "profile": profile,
            "provider": provider,
            "model": model,
            "baseUrl": base_url,
            "latencyMs": latency_ms,
            "message": "模型连接测试失败",
            "errors": [str(exc)[:500]],
        }


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
