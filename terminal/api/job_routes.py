"""Background job domain for the Archer Desktop API."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime

from terminal.api._config import ROOT, _load_config
from terminal.api._tools import _failure_hint_event

BACKGROUND_JOBS: dict[str, dict] = {}
BACKGROUND_JOB_LOCK = threading.Lock()
BACKGROUND_JOBS_LOADED = False
BACKGROUND_JOBS_PATH = ROOT / "memory" / "background_jobs.json"
DEFAULT_BACKGROUND_JOB_TIMEOUT_SECONDS = 300
BACKGROUND_JOB_STALE_SECONDS = 15 * 60


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

