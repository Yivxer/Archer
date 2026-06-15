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
    from core.session_store import read_session_file
    sessions_dir = Path(SESSIONS_DIR)
    if not sessions_dir.exists():
        return []
    items: list[dict] = []
    for path in sorted(sessions_dir.glob("*.json"), reverse=True)[:limit]:
        messages, _usage = read_session_file(path)
        first_user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        title = str(first_user).strip().replace("\n", " ")[:42] or path.stem
        preview = str(first_user).strip().replace("\n", " ")[:60]
        items.append({
            "id": path.stem, "title": title, "date": path.stem[:8],
            "turns": max(1, len(messages) // 2), "tone": "saved", "preview": preview,
        })
    return items


def _session_detail(session_id: str) -> dict | None:
    from core.session import SESSIONS_DIR
    from core.session_store import read_session_file
    if not _valid_session_id(session_id):
        return None
    path = Path(SESSIONS_DIR) / f"{session_id}.json"
    if not path.exists() or not path.is_file():
        return None
    messages, token_usage = read_session_file(path)
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
    return detail


def _save_session(payload: dict) -> dict:
    from core.session import SESSIONS_DIR
    from core.session_store import dump_session_file
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
    path.write_text(
        dump_session_file(messages, token_usage=session_usage_for_file()),
        encoding="utf-8",
    )
    return {"id": path.stem, "path": str(path), "messages": len(messages)}


def _append_session(session_id: str, payload: dict) -> dict:
    from core.session import SESSIONS_DIR
    from core.session_store import dump_session_file, read_session_file
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
    existing, token_usage = read_session_file(path)
    if not isinstance(existing, list):
        existing = []
    existing.extend(new_messages)
    path.write_text(
        dump_session_file(existing, token_usage=token_usage),
        encoding="utf-8",
    )
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
        jobs = [dict(job) for job in BACKGROUND_JOBS.values()]
    jobs.sort(key=lambda job: str(job.get("createdAt", "")), reverse=True)
    return {"ok": True, "jobs": jobs}


def _job_detail(job_id: str) -> dict | None:
    with BACKGROUND_JOB_LOCK:
        _load_jobs_locked()
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


def _active_child_job_count_locked() -> int:
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
            url_match = re.search(r'https?://[^\s）+）"]+', prompt)
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
        from memory.retrieve import for_context, format_for_prompt
        core, related = for_context(prompt, limit=5, intent=intent_info.get("intent", ""))
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
        url_match = __import__("re").search(r'https?://[^\s）+）"]+', prompt)
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

    def _execute_chat() -> None:
        try:
            prompt = str(job.get("prompt", ""))
            response = _run_job_chat_with_tools(prompt, job_id)
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

        # Approved: execute the tool
        tool_name = str(pending_tool.get("toolName", ""))
        draft = pending_tool.get("draft") or {}
        try:
            if tool_name == "shell.execute":
                from terminal.api._tools import _execute_shell_command
                output = _execute_shell_command(draft)
                job["result"] = f"[shell] {output[:500]}"
            elif tool_name == "obsidian_write":
                from terminal.api._tools import _append_obsidian_draft
                target = _append_obsidian_draft(draft)
                job["result"] = f"[obsidian_write] 已写入: {target}"
            elif tool_name == "github":
                from terminal.api._tools import _execute_github_operation
                output = _execute_github_operation(draft)
                job["result"] = f"[github] {output[:500]}"
            elif tool_name == "hugo_blog":
                # For hugo_blog, execute deploy action
                action = str((draft.get("args") or {}).get("action", ""))
                if action == "deploy":
                    from skills.hugo_blog import run as hugo_blog_run
                    output = hugo_blog_run(draft.get("args") or {})
                    job["result"] = f"[hugo_blog] {str(output)[:500]}"
                else:
                    job["result"] = f"[hugo_blog] action={action} approved, check tool output"
            elif tool_name == "file_ops":
                # file_ops: write or create file
                from skills.file_ops import run as file_ops_run
                output = file_ops_run(draft.get("args") or {})
                job["result"] = f"[file_ops] {str(output)[:500]}"
            else:
                job["result"] = f"[{tool_name}] tool approved (no auto-executor for this tool type)"
            job["status"] = "complete"
        except Exception as exc:
            job["status"] = "failed"
            job["result"] = ""
            job["error"] = f"tool execution failed: {exc}"

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
    match = re.search(r"[模式：:]\s*([^\\]）\]]+)", first_line)
    return match.group(1).strip() if match else fallback


def _available_modes(cfg: dict) -> dict:
    persona = cfg.get("persona", {})
    mode_auto = persona.get("mode_auto", True) is not False
    locked = persona.get("current_mode", persona.get("default_mode", "listener"))
    current = "auto" if mode_auto else locked
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
                "active": (not mode_auto) and mode_id == locked,
            })

    for mode_id, meta in sorted(toml_modes.items()):
        if mode_id in seen:
            continue
        label = meta.get("name", mode_id) if isinstance(meta, dict) else mode_id
        items.append({
            "id": mode_id,
            "label": label,
            "source": "toml",
            "active": (not mode_auto) and mode_id == locked,
        })

    return {"current": current, "default": default, "modes": items, "modeAuto": mode_auto}


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


def _persist_mode_auto(flag: bool) -> None:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    new_line = f'mode_auto = {"true" if flag else "false"}'
    if re.search(r'^mode_auto\s*=', text, re.MULTILINE):
        text = re.sub(r'^mode_auto\s*=.*$', new_line, text, flags=re.MULTILINE)
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
    persona = cfg.get("persona", {})
    mode_auto = persona.get("mode_auto", True) is not False
    mode = "auto" if mode_auto else persona.get("current_mode", persona.get("default_mode", "listener"))
    from core.model_select import status_model_label
    from core.token_usage import status_payload
    token_limit = int(cfg.get("context", {}).get("token_limit", 1_000_000))
    return {
        "adapter": "local",
        "model": status_model_label(cfg),
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
    if not draft and event_id.startswith("hugo-blog-deploy-"):
        from core.api_tool_service import make_tool_request
        from skills.loader import load_skills
        draft = make_tool_request(
            "hugo_blog",
            {"action": "deploy"},
            load_skills(),
            cfg=_load_config(),
            event_id=event_id,
            display_name="hugo_blog",
            extra={"action": "deploy", "title": "部署枫弋札记"},
            force_approval=False,
        )
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
                            deploy_args = {"action": "deploy"}
                            created_file = re.search(r"文章已创建：(.+?\.md)", result_output)
                            if created_file:
                                deploy_args["filename"] = Path(created_file.group(1)).name
                            elif args.get("slug"):
                                deploy_args["slug"] = args.get("slug")
                            deploy_result = hugo_run(deploy_args)
                            result_output += "\n\n" + str(deploy_result)
                            if "单页验证成功" in str(deploy_result):
                                message += " | hugo deploy 已自动执行并验证单页可访问"
                            elif "部署成功" in str(deploy_result):
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
                            deploy_result = hugo_run({"action": "deploy", "filename": Path(target_path).name})
                            result_output += "\n\n" + str(deploy_result)
                            if "单页验证成功" in str(deploy_result):
                                message += " | hugo deploy 已自动执行并验证单页可访问"
                            else:
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
        "message": (
            "未找到待执行草稿（可能 API 已重启或确认卡已过期）。"
            "请重新说「部署枫弋札记」，或直接点当前确认卡上的发布按钮。"
        ),
    }


# ---------------------------------------------------------------------------
# Scheduled tasks
# ---------------------------------------------------------------------------

def _list_schedules() -> dict:
    from core.scheduler import SCHEDULES_JSON_PATH, format_task, list_tasks, sync_schedules_json
    from memory.store import init_db

    init_db()
    sync_schedules_json()
    return {
        "ok": True,
        "jsonPath": str(SCHEDULES_JSON_PATH),
        "tasks": [format_task(t) for t in list_tasks()],
    }


def _add_schedule(payload: dict) -> tuple[int, dict]:
    from core.scheduler import add_task, format_task, get_task, parse_interval
    from memory.store import init_db
    from skills.loader import register_all_skills

    init_db()
    skill_name = str(payload.get("skillName") or payload.get("skill_name") or "").strip()
    interval = str(payload.get("interval") or payload.get("intervalSpec") or "").strip()
    label = str(payload.get("label") or "").strip()
    catchup = str(payload.get("catchup") or "latest").strip()
    args = payload.get("args") if isinstance(payload.get("args"), dict) else None

    if not skill_name or not interval:
        return 400, {"ok": False, "error": "skillName and interval are required"}

    registry = register_all_skills()
    if skill_name not in registry:
        return 400, {"ok": False, "error": f"unknown skill: {skill_name}"}

    try:
        parse_interval(interval)
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}

    task_id = add_task(skill_name, interval, label, args=args, catchup=catchup)
    task = get_task(task_id)
    return 200, {"ok": True, "task": format_task(task)}


def _schedule_action(task_id: str, action: str, payload: dict | None = None) -> tuple[int, dict]:
    from core.scheduler import (
        format_task,
        get_task,
        remove_task,
        run_task_by_id,
        set_enabled,
    )
    from memory.store import init_db
    from skills.loader import register_all_skills

    if not re.fullmatch(r"[0-9]+", task_id):
        return 400, {"ok": False, "error": "task id must be numeric"}

    init_db()
    tid = int(task_id)
    task = get_task(tid)
    if task is None and action != "remove":
        return 404, {"ok": False, "error": "task_not_found", "id": tid}

    if action == "remove":
        ok = remove_task(tid)
        return (200 if ok else 404), {"ok": ok, "id": tid}

    if action == "enable":
        ok = set_enabled(tid, True)
        task = get_task(tid)
        return 200, {"ok": ok, "task": format_task(task) if task else None}

    if action == "disable":
        ok = set_enabled(tid, False)
        task = get_task(tid)
        return 200, {"ok": ok, "task": format_task(task) if task else None}

    if action == "run":
        skills = register_all_skills()
        tr = run_task_by_id(tid, skills)
        task = get_task(tid)
        if tr is None and task is None:
            return 404, {"ok": False, "error": "task_not_found", "id": tid}
        if tr is None:
            return 400, {
                "ok": False,
                "error": "skill_not_loaded",
                "id": tid,
                "skillName": task["skill_name"],
            }
        return 200, {
            "ok": tr.ok,
            "task": format_task(task) if task else None,
            "summary": tr.summary,
            "preview": (tr.content_preview or "")[:600],
        }

    return 400, {"ok": False, "error": f"unknown action: {action}"}


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
    if path == "/health":
        return 200, {"ok": True}
    if path == "/jobs":
        return 200, _list_jobs()
    if path == "/schedules":
        return 200, _list_schedules()
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
    if path == "/schedules":
        status, body = _add_schedule(payload)
        return status, body
    schedule_action = re.fullmatch(r"/schedules/([0-9]+)/(remove|enable|disable|run)", path)
    if schedule_action:
        status, body = _schedule_action(schedule_action.group(1), schedule_action.group(2), payload)
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
