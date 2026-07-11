"""Tool event system and chat streaming for the Archer Desktop API."""

from __future__ import annotations

import json
import logging
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

from terminal.api._config import (
    PENDING_TOOL_DRAFTS,
    set_tool_draft,
    get_tool_draft,
    pop_tool_draft,
    TEXT_FILE_EXTENSIONS,
    _clean_chat_messages,
    _load_config,
)
from terminal.api.turn_context import (
    clean_file_refs as _clean_file_refs,
    clean_memory_mode as _clean_memory_mode,
    clean_obsidian_mode as _clean_obsidian_mode,
)
from terminal.api.context_assembly import (
    assemble_memory_context,
    assemble_obsidian_context,
    assemble_vault_focus,
    assemble_web_context,
    file_reference_context,
)
from terminal.api.turn_pipeline import (
    assemble_model_messages,
    classify_turn,
    orchestrate_turn,
    select_turn_tools,
    plain_chat_message as _plain_chat_message,
    trim_model_messages as _trim_model_messages_for_context,
)
from terminal.api.tool_stage import summarize_api_tool_events

logger = logging.getLogger("archer_api")
MODEL_STREAM_HEARTBEAT_SECONDS = 8.0
MODEL_STREAM_TOTAL_TIMEOUT_SECONDS = 180.0
HUGO_WORKFLOW_HEARTBEAT_SECONDS = 8.0
HUGO_WORKFLOW_TOTAL_TIMEOUT_SECONDS = 300.0

# DeepSeek 伪 XML / DSML 残留检测（移植自 terminal/archer.py:228-235）
_DSML_MARKER = "｜｜DSML｜｜"
_FAKE_XML_RE = re.compile(
    r"<(读取文件|写入文件|搜索文件|文件查找|参数|tool_call|invoke|function_call|execute)[^>]{0,60}>",
    re.IGNORECASE,
)


def _has_fake_xml(text: str) -> bool:
    """检测 DeepSeek 输出的伪 XML 假标签或 DSML 残留。"""
    return bool(_FAKE_XML_RE.search(text)) or _DSML_MARKER in text


def _split_safe_model_chunk(buffer: str, chunk: str) -> tuple[str, str, bool]:
    """Return stream-safe text before fake tool markup and whether markup appeared."""
    combined = buffer + chunk
    if _has_fake_xml(combined):
        earliest = len(combined)
        marker_index = combined.find(_DSML_MARKER)
        if marker_index >= 0:
            earliest = min(earliest, marker_index)
        match = _FAKE_XML_RE.search(combined)
        if match:
            earliest = min(earliest, match.start())
        safe_combined = combined[:earliest]
        safe_text = safe_combined[len(buffer):] if len(safe_combined) > len(buffer) else ""
        return safe_combined, safe_text, True
    return combined, chunk, False


from terminal.api.part8_runtime import (
    _initiative_event_from_log,
    _record_part8_shadow_material,
    _yield_shadow_initiative_events,
)


def _runtime_context_event(
    *,
    query: str,
    intent_info: dict,
    orchestration,
    file_refs: list[dict] | None = None,
    trace_id: str = "",
) -> dict:
    matched_skills = list(getattr(orchestration, "matched_skills", []) or [])
    wants_blog = _wants_hugo_publish(query, file_refs or [])
    task = "blog_publish" if wants_blog else str(getattr(orchestration, "sub_intent", "") or intent_info.get("intent", "chat"))
    return {
        "id": f"runtime-context-{uuid4().hex[:8]}",
        "traceId": trace_id,
        "task": task,
        "phase": "route",
        "userIntent": str(getattr(orchestration, "sub_intent", "") or intent_info.get("intent", "chat")),
        "lastResult": "",
        "expectedNext": "select_workflow_or_model",
        "matchedSkills": matched_skills,
    }


def _failure_hint_event(exc: Exception, *, stage: str, trace_id: str = "") -> dict:
    detail = str(exc)[:300] or type(exc).__name__
    lowered = detail.lower()
    # B6.1: provider 连接/鉴权/限流失败 → provider_connection_failed keyword
    # _connection_hint 抛 "无法连接 LLM API"，_status_hint 抛 "模型 API 鉴权失败/额度受限"
    is_llm_stage = stage in ("model_stream", "llm", "call_with_tools")
    is_provider_error = (
        "无法连接" in str(exc)
        or "llm api" in lowered
        or "模型 api" in lowered
        or "连接" in str(exc)
        or "timeout" in lowered
        or "connect" in lowered
    )
    if is_llm_stage and is_provider_error:
        keyword = "provider_connection_failed"
        recoverable = True
    elif "timeout" in lowered or "connect" in lowered:
        keyword = "command_timeout"
        recoverable = True
    elif "permission" in lowered or "denied" in lowered:
        keyword = "write_permission"
        recoverable = False
    elif "not found" in lowered or "no such file" in lowered or "missing" in lowered:
        keyword = "dependency_missing"
        recoverable = True
    elif "syntax" in lowered or "parse" in lowered or "json" in lowered:
        keyword = "syntax_mismatch"
        recoverable = True
    else:
        keyword = "runtime_failure"
        recoverable = True
    return {
        "id": f"failure-hint-{uuid4().hex[:8]}",
        "traceId": trace_id,
        "keyword": keyword,
        "stage": stage,
        "recoverable": recoverable,
        "detail": detail,
    }


def _with_trace_id(event: dict, trace_id: str) -> dict:
    if not trace_id or not isinstance(event, dict):
        return event
    event_type = event.get("type")
    payload_keys = {
        "tool_event": "toolEvent",
        "orchestrationEvent": "orchestrationEvent",
        "planEvent": "planEvent",
        "runtimeContextEvent": "runtimeContextEvent",
        "statusEvent": "statusEvent",
        "initiativeEvent": "initiativeEvent",
        "failureHintEvent": "failureHintEvent",
    }
    payload_key = payload_keys.get(str(event_type))
    payload = event.get(payload_key) if payload_key else None
    if isinstance(payload, dict):
        payload.setdefault("traceId", trace_id)
        if payload_key == "toolEvent" and isinstance(payload.get("draft"), dict):
            payload["draft"].setdefault("traceId", trace_id)
    return event


def _iter_model_stream_with_heartbeat(messages: list[dict], **kwargs):
    """Run blocking model streaming in a worker so SSE can emit keepalive events."""
    output: queue.Queue[tuple[str, object]] = queue.Queue()

    def worker() -> None:
        try:
            from core.llm import stream_chat as model_stream_chat
            for chunk in model_stream_chat(messages, **kwargs):
                output.put(("chunk", chunk))
            output.put(("done", None))
        except Exception as exc:
            output.put(("error", exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    started = time.monotonic()
    while True:
        if time.monotonic() - started > MODEL_STREAM_TOTAL_TIMEOUT_SECONDS:
            raise TimeoutError("model stream total timeout")
        try:
            kind, value = output.get(timeout=MODEL_STREAM_HEARTBEAT_SECONDS)
        except queue.Empty:
            yield {"type": "heartbeat"}
            continue
        if kind == "chunk":
            yield {"type": "chunk", "text": value}
        elif kind == "error":
            raise value
        elif kind == "done":
            break

# ---------------------------------------------------------------------------
# Intent detection helpers（委托 core/desktop_tool_router，保留旧函数名兼容测试）
# ---------------------------------------------------------------------------

from core.desktop_tool_router import (
    extract_github_args as _extract_github_args,
    extract_obsidian_target_path as _extract_obsidian_target_path,
    extract_shell_command as _extract_shell_command,
    filter_skills_for_intent as _filter_skills_for_intent,
    parse_obsidian_write_request as _parse_obsidian_write_request,
    plan_desktop_turn as _plan_desktop_turn,
    plan_desktop_tools as _plan_desktop_tools,
    should_draft_obsidian_write as _should_draft_obsidian_write,
    should_preview_obsidian as _should_preview_obsidian,
    should_trigger_github as _should_trigger_github,
    should_trigger_shell as _should_trigger_shell,
    wants_hugo_creation as _wants_hugo_creation,
    wants_hugo_deploy as _wants_hugo_deploy,
    wants_hugo_publish as _wants_hugo_publish,
)


# ---------------------------------------------------------------------------
# Shell execution
# ---------------------------------------------------------------------------

def _is_dangerous_shell(command: str) -> bool:
    from core.policy import score_shell_risk
    risk, _ = score_shell_risk(command)
    return risk in ("critical", "high")


def _execute_shell_command(command: str, timeout: int = 30) -> dict:
    if _is_dangerous_shell(command):
        return {
            "ok": False,
            "output": f"[拒绝] 检测到高风险命令，已阻止：{command}\n如需执行请直接在终端运行。",
        }
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return {"ok": True, "output": output or "(无输出)", "exitCode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "错误：命令超时（30s）"}
    except Exception as exc:
        return {"ok": False, "output": f"错误：{exc}"}


# ---------------------------------------------------------------------------
# Tool event construction
# ---------------------------------------------------------------------------

def _tool_event(
    event_id: str, name: str, status: str, risk: str,
    summary: str, detail: str, requires_approval: bool = False,
    draft: dict | None = None,
) -> dict:
    tool_event = {
        "id": event_id, "name": name, "status": status, "risk": risk,
        "summary": summary, "detail": detail,
        "requiresApproval": requires_approval,
    }
    if draft:
        tool_event["draft"] = draft
        if draft.get("permissionLevel"):
            tool_event["permissionLevel"] = draft.get("permissionLevel")
    return {"type": "tool_event", "toolEvent": tool_event}


def _obsidian_write_draft(query: str) -> dict:
    parsed = _parse_obsidian_write_request(query)
    content = parsed.body if parsed.mode == "overwrite" else (
        "\n<!-- Archer Desktop 自动写入 -->\n"
        f"{parsed.body}\n"
    )
    path = parsed.path
    # 计算 before/after 预览，供确认卡展示 diff
    try:
        from skills.obsidian_write import compute_preview
        preview = compute_preview({"path": path, "content": content, "mode": parsed.mode})
    except Exception:
        preview = None
    return {
        "path": path,
        "mode": parsed.mode,
        "contentPreview": content[:500],
        "content": content,
        "beforeText": preview["before"] if preview else "",
        "afterText": preview["after"] if preview else content[:2000],
        "previewMode": parsed.mode,
        "previewExists": preview["exists"] if preview else False,
        "expectedMtime": preview["mtime"] if preview else None,
        "expectedSize": preview["size"] if preview else None,
        "expectedFingerprint": preview["fingerprint"] if preview else None,
    }


def _make_api_tool_request(
    skill_name: str, args: dict, *, event_id: str, display_name: str,
    extra: dict | None = None, force_approval: bool = True,
) -> dict:
    from core.api_tool_service import make_tool_request
    from skills.loader import load_skills
    return make_tool_request(
        skill_name, args, load_skills(), cfg=_load_config(),
        event_id=event_id, display_name=display_name,
        extra=extra, force_approval=force_approval,
    )


def _obsidian_work_intent(path: str, mode: str, *, before_text: str = "") -> dict:
    original_lines = len(before_text.splitlines()) if before_text else 0
    return {
        "workflowName": "Obsidian 写入",
        "action": mode,
        "targets": [{"label": "目标笔记", "path": path}],
        "steps": ["读取当前文件状态", "校验文件指纹", "写入内容", "返回写入回执"],
        "verifyPlan": f"确认目标文件存在，原文件约 {original_lines} 行",
        "rollbackPlan": "写入前校验 expected_fingerprint；如文件已变化则拒绝写入",
    }


def _expert_scoped_skills(cfg: dict | None = None) -> dict:
    from core.experts import active_expert, filter_skills_for_expert
    from skills.loader import load_skills

    resolved = cfg or _load_config()
    return filter_skills_for_expert(load_skills(), active_expert(resolved))


def _select_api_skills(query: str, all_skills: dict | None = None) -> dict:
    if all_skills is None:
        all_skills = _expert_scoped_skills()
    return _plan_desktop_turn(
        query, all_skills, llm_fallback=False,
    ).raw_selected


def _filter_api_skills_for_intent(query: str, selected: dict, *, intent: str = "chat") -> dict:
    return _filter_skills_for_intent(query, selected, intent=intent)


def _tool_event_from_request(
    request: dict, *, summary: str, detail_prefix: str = "",
) -> dict:
    policy = request.get("policy", {})
    decision = policy.get("decision", "confirm")
    risk = policy.get("risk", "medium")
    reason = policy.get("reason", "")
    status = "blocked" if request.get("blocked") else "waiting"
    detail_parts = [
        f"id: {request['eventId']}",
        f"skill: {request.get('skillName', '')}",
        f"decision: {decision}",
    ]
    if detail_prefix:
        detail_parts.append(detail_prefix)
    if reason:
        detail_parts.append(str(reason)[:240])
    return _tool_event(
        request["eventId"],
        request.get("displayName") or request.get("skillName", "tool"),
        status, risk,
        summary if not request.get("blocked") else f"工具请求被策略阻止：{summary}",
        ", ".join(detail_parts),
        bool(request.get("requiresApproval")) and not request.get("blocked"),
        request,
    )


def _tool_event_from_result(
    event_id: str, name: str, result: dict, *, summary: str,
    draft: dict | None = None,
) -> dict:
    policy = result.get("policy", {})
    risk = policy.get("risk", "low")
    status = "complete" if result.get("ok") else "blocked"
    detail = str(result.get("output") or result.get("summary") or "")[:300]
    return _tool_event(
        event_id, name, status, risk,
        summary if result.get("ok") else f"{summary}失败",
        detail, False, draft,
    )


def _execute_api_tool_preview(
    skill_name: str, args: dict, *, event_id: str,
    display_name: str, summary: str,
) -> dict:
    from core.api_tool_service import execute_tool_request
    from skills.loader import load_skills
    skills = load_skills()
    request = _make_api_tool_request(
        skill_name, args, event_id=event_id,
        display_name=display_name, force_approval=False,
    )
    if request.get("blocked"):
        return _tool_event_from_request(request, summary=summary)
    result = execute_tool_request(request, skills, cfg=_load_config())
    return _tool_event_from_result(event_id, display_name, result, summary=summary)


# ---------------------------------------------------------------------------
# Desktop tool loop — LLM 自主链式调用工具（低风险自动执行，高风险生成草稿卡）
# ---------------------------------------------------------------------------

# 可在 tool_loop 中自动执行的技能（risk=low 且无需用户确认）
_AUTO_EXEC_SKILLS = {
    "code_review", "code_search", "file_search",
    "frontend_dev", "image_generator", "market_research",
    "task_manager", "video_script", "workflow_automation",
    "summarize", "humanizer", "weather", "site_check",
    "clipboard", "screenshot", "page_screenshot",
    "image_analysis", "image_ocr", "whisper_transcribe",
    "weekly_review", "rss_reader", "apple_reminders",
}


def _extract_md_path_from_query(query: str) -> str:
    match = re.search(r"(/Users/[^\n\r`'\"]+?\.md)", query)
    return match.group(1) if match else ""


def _extract_md_paths_from_text(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"(/Users/[^\n\r`'\"]+?\.md)", text)))


def _read_md_source(path_value: str) -> tuple[str, str] | None:
    path = Path(path_value).expanduser()
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".md":
        return None
    try:
        return str(path), path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _collect_hugo_markdown_sources(
    messages: list[dict],
    query: str,
    file_refs: list[dict] | None,
) -> list[tuple[str, str]]:
    """从附件、消息路径、对话历史回收 Markdown 原文（多轮会话）。"""
    sources: list[tuple[str, str]] = []
    seen_labels: set[str] = set()

    def add(label: str, text: str) -> None:
        clean = text.strip()
        if not clean or label in seen_labels:
            return
        seen_labels.add(label)
        sources.append((label, clean))

    for ref in file_refs or []:
        loaded = _read_md_source(str(ref.get("path", "")).strip())
        if loaded:
            add(loaded[0], loaded[1])

    for path_value in _extract_md_paths_from_text(query):
        loaded = _read_md_source(path_value)
        if loaded:
            add(loaded[0], loaded[1])

    for msg in messages:
        role = str(msg.get("role", ""))
        content = str(msg.get("content", ""))
        if not content.strip():
            continue

        if role == "system" and "以下是用户在桌面端明确选择并引用的本地文本文件内容" in content:
            for block in re.split(r"\n---\n", content):
                path_match = re.search(r"^path:\s*(/Users/.+)$", block, re.MULTILINE)
                if not path_match:
                    continue
                body = re.sub(r"^###\s*.+\npath:.*\ntruncated:.*\n\n", "", block, flags=re.MULTILINE).strip()
                if body:
                    add(path_match.group(1).strip(), body)

        for path_value in _extract_md_paths_from_text(content):
            loaded = _read_md_source(path_value)
            if loaded:
                add(loaded[0], loaded[1])

        if role in ("user", "assistant") and re.search(r"(?m)^title:\s*.+", content):
            add(f"conversation:{hash(content) & 0xfffffff}", content)

    return sources


def _extract_frontmatter_hints(text: str) -> dict[str, str]:
    hints: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^(title|slug|category|description):\s*(.+)$", line.strip(), re.IGNORECASE)
        if match:
            hints[match.group(1).lower()] = match.group(2).strip().strip('"').strip("'")
    return hints


def _format_hugo_chat_summary(
    title: str,
    deploy_result: str,
    *,
    deploy_ok: bool,
    prefix: str | None = None,
) -> str:
    """给用户看的枫弋札记结果，不贴 Hugo/SSH 原始终端输出。"""
    lines = [prefix or f"已部署《{title}》到枫弋札记。"]
    deploy_text = str(deploy_result)
    url_match = re.search(r"https://iver\.yivxer\.com/posts/[^\s/]+/", deploy_text)
    for line in deploy_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("线上地址："):
            lines.append(stripped)
            url_match = None
        elif stripped.startswith("验证：") or stripped.startswith("单页验证成功"):
            lines.append(stripped)
    if url_match and not any(line.startswith("线上地址：") for line in lines):
        lines.append(f"线上地址：{url_match.group(0)}")
    if deploy_ok:
        if not any(line.startswith("验证：") or line.startswith("单页验证成功") for line in lines):
            verify_match = re.search(r"验证：.+", deploy_text)
            if verify_match:
                lines.append(verify_match.group(0))
        lines.append("部署已完成。")
    elif deploy_text and not deploy_ok:
        lines.append(deploy_text)
    return "\n".join(lines)


def _hugo_workflow_event(
    *,
    workflow_id: str,
    step: str,
    event_id: str,
    args: dict,
    result: str,
    summary: str,
) -> dict:
    ok = "错误" not in str(result) and ("失败" not in str(result) or "部署成功" in str(result))
    summary = summary or {
        "create": "创建博客文章",
        "delete": "删除博客文章",
        "deploy": "部署枫弋札记",
    }.get(step, f"hugo_blog · {step}")
    return _tool_event_from_result(
        event_id,
        "hugo_blog",
        {
            "ok": ok,
            "executed": ok,
            "output": result,
            "summary": summary,
            "policy": {"risk": "low"},
        },
        summary=summary,
        draft={
            "workflow": "hugo_publish",
            "workflowId": workflow_id,
            "workflowStep": step,
            "workflowArgs": args,
        },
    )


def _run_hugo_publish_workflow(
    *,
    title: str,
    actions: list[tuple[str, dict]],
    summary_prefix: str | None = None,
) -> tuple[list[dict], str]:
    """Run the authoritative Hugo publish workflow and emit traceable events."""
    from core.tool_runtime import invoke as runtime_invoke
    from skills import hugo_blog as hugo_blog_module

    workflow_id = f"hugo-publish-{uuid4().hex[:8]}"
    tool_events: list[dict] = []
    deploy_result = ""
    deploy_ok = False
    last_result = ""
    skills = {"hugo_blog": hugo_blog_module}

    for step, args in actions:
        event_id = f"{workflow_id}-{step}"
        step_summary = {
            "create": "创建博客文章",
            "delete": "删除博客文章",
            "deploy": "部署枫弋札记",
        }.get(step, f"hugo_blog · {step}")
        tr = runtime_invoke("hugo_blog", args, skills)
        if tr.ok:
            result = tr.content_preview or tr.summary
        else:
            err = tr.error or {}
            result = (
                f"枫弋札记工作流失败（{step}）："
                f"{err.get('type', 'Error')}: {err.get('message') or tr.summary}"
            )
            tool_events.append(_hugo_workflow_event(
                workflow_id=workflow_id,
                step=step,
                event_id=event_id,
                args=args,
                result=result,
                summary=step_summary,
            ))
            return tool_events, result
        last_result = result
        if step == "deploy":
            deploy_result = result
            deploy_ok = "部署成功" in result
        tool_events.append(_hugo_workflow_event(
            workflow_id=workflow_id,
            step=step,
            event_id=event_id,
            args=args,
            result=result,
            summary=step_summary,
        ))
        if step != "deploy" and result.startswith("错误"):
            return tool_events, result

    if not deploy_result:
        return tool_events, last_result
    return tool_events, _format_hugo_chat_summary(
        title,
        deploy_result,
        deploy_ok=deploy_ok,
        prefix=summary_prefix,
    )


def _try_direct_hugo_deploy_existing(
    messages: list[dict],
    query: str,
) -> tuple[list[dict], str] | None:
    """对话里已有 slug/title 且博客目录有对应文件 → 直接 deploy。"""
    slug = ""
    title = ""
    for msg in reversed(messages):
        hints = _extract_frontmatter_hints(str(msg.get("content", "")))
        slug = slug or hints.get("slug", "")
        title = title or hints.get("title", "")
        if slug and title:
            break

    if not slug and not title:
        return None

    from skills.hugo_blog import POSTS_DIR, _safe_slug, _slug_from_post

    target: Path | None = None
    if slug:
        safe = _safe_slug(slug)
        direct = POSTS_DIR / f"{safe}.md"
        if direct.exists():
            target = direct
        else:
            for path in POSTS_DIR.glob("*.md"):
                if _slug_from_post(path) == safe or path.stem == safe:
                    target = path
                    break

    if target is None and title:
        for path in POSTS_DIR.glob("*.md"):
            # 用 frontmatter 解析替代字符串拼接匹配，避免引号格式差异导致漏匹配
            hints = _extract_frontmatter_hints(path.read_text(encoding="utf-8", errors="ignore")[:2000])
            if hints.get("title", "") == title:
                target = path
                break

    if target is None:
        return None

    deploy_title = title or target.stem
    args = {"action": "deploy", "filename": target.name}
    return _hugo_confirmation_result(
        action="deploy",
        title=deploy_title,
        args=args,
        source=str(target),
        target_url=f"https://iver.yivxer.com/posts/{_safe_slug(target.stem)}/",
        steps=["构建 Hugo 站点", "同步到远端", "验证线上 URL"],
        verify_plan="部署后验证文章 URL 返回 HTTP 200",
        rollback_plan="不修改源文件；如部署失败保留当前 content/posts 文件",
    )


def _wants_hugo_delete(query: str) -> bool:
    lowered = query.lower()
    delete_terms = ("删除", "删掉", "移除", "下架", "撤下", "隐藏", "remove", "delete")
    return any(term in lowered for term in delete_terms) and (
        "枫弋札记" in query
        or "博客" in query
        or "网站" in query
        or "站点" in query
        or "content/posts" in lowered
        or "iver.yivxer.com" in lowered
    )


def _try_direct_hugo_delete(query: str) -> tuple[list[dict], str] | None:
    """明确删除文章 → 移出 content/posts 并全站部署，避免模型假删除。"""
    if not _wants_hugo_delete(query):
        return None

    from skills.hugo_blog import POSTS_DIR, _post_frontmatter, _safe_slug

    matches: list[Path] = []
    lowered = query.lower()
    for path in POSTS_DIR.glob("*.md"):
        fm = _post_frontmatter(path)
        title = str(fm.get("title") or "")
        slug = _safe_slug(str(fm.get("slug") or path.stem))
        if path.name in query or path.stem in lowered or slug in lowered:
            matches.append(path)
            continue
        if title and title in query:
            matches.append(path)
            continue
        title_parts = [part for part in re.split(r"[，,：:｜|《》\s]+", title) if len(part) >= 4]
        if any(part in query for part in title_parts):
            matches.append(path)

    if not matches:
        return None
    if len(matches) > 1:
        candidates = "\n".join(f"- {p.name} · {str(_post_frontmatter(p).get('title') or p.stem)}" for p in matches[:8])
        return [], f"找到多篇可能要删除的文章，请先指定其中一篇：\n{candidates}"

    target = matches[0]
    title = str(_post_frontmatter(target).get("title") or target.stem)
    return _hugo_confirmation_result(
        action="delete_and_deploy",
        title=title,
        args={"action": "delete_and_deploy", "filename": target.name},
        source=str(target),
        target_url=f"https://iver.yivxer.com/posts/{_safe_slug(str(_post_frontmatter(target).get('slug') or target.stem))}/",
        steps=["移出 content/posts 文件到 .archer-trash/posts", "重新部署站点", "验证原 URL 返回 HTTP 404"],
        verify_plan="删除并部署后验证原文章 URL 返回 HTTP 404",
        rollback_plan="从 .archer-trash/posts 恢复源文件后重新 deploy",
    )


def _parse_markdown_for_hugo(text: str, *, source_path: str = "") -> dict | None:
    """从 Obsidian/本地 Markdown 提取 hugo_blog new 所需字段。"""
    raw = text.strip()
    if not raw:
        return None

    fm: dict[str, str] = {}
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                fm[key.strip()] = value.strip().strip('"').strip("'")
            body = parts[2].strip()

    title = fm.get("title", "").strip()
    title_source = "frontmatter title" if title else ""
    if not title:
        h1 = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if h1:
            title = h1.group(1).strip()
            title_source = "H1"
    if not title and source_path:
        title = Path(source_path).stem
        title_source = "filename"
    if not title:
        h2 = re.search(r"^##\s+(.+)$", body, re.MULTILINE)
        if h2:
            title = h2.group(1).strip()

    category = "阅读" if "读书笔记" in source_path else "系统"
    cats_raw = fm.get("categories", fm.get("category", "")).strip().strip("[]")
    if cats_raw:
        for valid in ("系统", "健身", "复盘", "阅读", "产品", "写作", "技术"):
            if valid in cats_raw:
                category = valid
                break

    description = fm.get("description", fm.get("summary", "")).strip().strip('"')
    if not description:
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "```", "- ", "* ", ">")):
                continue
            description = stripped[:200]
            break
    if not description:
        description = title[:120] if title else "无摘要"

    clean_body = body
    if title:
        clean_body = re.sub(rf"^#{{1,2}}\s+{re.escape(title)}\s*\n+", "", clean_body, count=1, flags=re.MULTILINE)

    if not title or len(title) < 2:
        return None

    return {
        "title": title[:120],
        "titleSource": title_source or "filename",
        "category": category,
        "description": description[:200],
        "body": clean_body.strip(),
    }


def _hugo_confirmation_result(
    *,
    action: str,
    title: str,
    args: dict,
    source: str,
    target_url: str,
    steps: list[str],
    verify_plan: str,
    rollback_plan: str,
) -> tuple[list[dict], str]:
    event_id = f"hugo-blog-{action}-{uuid4().hex[:8]}"
    work_intent = {
        "workflowName": "枫弋札记",
        "action": action,
        "targets": [
            {"label": "源文件", "path": source},
            {"label": "线上地址", "url": target_url},
        ],
        "steps": steps,
        "verifyPlan": verify_plan,
        "rollbackPlan": rollback_plan,
    }
    request = _make_api_tool_request(
        "hugo_blog",
        args,
        event_id=event_id,
        display_name="hugo_blog",
        extra={
            "title": title,
            "sourcePath": source,
            "targetUrl": target_url,
            "workIntent": work_intent,
        },
        force_approval=True,
    )
    if not request.get("blocked"):
        set_tool_draft(event_id, request)
    event = _tool_event_from_request(
        request,
        summary=f"确认枫弋札记操作：{title}",
        detail_prefix=f"action: {action}, target: {target_url}",
    )
    return [event], "已生成枫弋札记确认卡，请确认后再执行。"


def _try_direct_hugo_publish(
    query: str,
    file_refs: list[dict] | None,
    *,
    messages: list[dict] | None = None,
) -> tuple[list[dict], str] | None:
    """附件、路径或对话历史 → hugo new + deploy，无需用户再操作。"""
    sources = _collect_hugo_markdown_sources(messages or [], query, file_refs)
    if not sources:
        return None

    label, text = sources[0]
    parsed = _parse_markdown_for_hugo(text, source_path=label)
    if not parsed:
        return None

    hints = _extract_frontmatter_hints(text)
    if hints.get("slug"):
        parsed["slug"] = hints["slug"]
    if hints.get("title") and not parsed.get("title"):
        parsed["title"] = hints["title"][:120]
    if hints.get("category"):
        for valid in ("系统", "健身", "复盘", "阅读", "产品", "写作", "技术"):
            if valid in hints["category"]:
                parsed["category"] = valid
                break
    if hints.get("description"):
        parsed["description"] = hints["description"][:200]

    if len(parsed.get("body", "")) < 40:
        merged_body = ""
        for _, alt_text in sources:
            alt_parsed = _parse_markdown_for_hugo(alt_text, source_path=label)
            if alt_parsed and len(alt_parsed.get("body", "")) > len(merged_body):
                merged_body = alt_parsed["body"]
        if len(merged_body) >= 40:
            parsed["body"] = merged_body
        elif not parsed.get("body"):
            return None

    new_args = {
        "action": "publish",
        "title": parsed["title"],
        "category": parsed["category"],
        "description": parsed["description"],
        "body": parsed["body"],
        "sourcePath": label,
        "titleSource": parsed.get("titleSource") or "filename",
    }
    if parsed.get("slug"):
        new_args["slug"] = parsed["slug"]

    from skills.hugo_blog import _safe_slug
    slug = _safe_slug(str(new_args.get("slug") or parsed["title"]))
    return _hugo_confirmation_result(
        action="publish",
        title=parsed["title"],
        args=new_args,
        source=label,
        target_url=f"https://iver.yivxer.com/posts/{slug}/",
        steps=[
            f"读取源稿标题（来源：{new_args['titleSource']}）",
            "写入或复用 content/posts 文章",
            "构建并同步站点",
            "验证线上 URL 返回 HTTP 200",
        ],
        verify_plan="发布后验证文章 URL 返回 HTTP 200",
        rollback_plan=f"如需撤回，将 content/posts/{slug}.md 移入 .archer-trash/posts 后重新 deploy",
    )


def _try_direct_hugo_redeploy_with_attachment(
    query: str,
    file_refs: list[dict] | None,
    *,
    messages: list[dict] | None = None,
) -> tuple[list[dict], str] | None:
    """用户带附件说「重新部署/再部署/更新」已有文章 → 直接读附件正文写入 posts 文件 + deploy，不弹确认卡。

    这是确定性路径，绕过 LLM agent 循环，避免幻觉。触发条件：
    1. 用户带附件（file_refs 非空）
    2. query 含「重新部署/再部署/更新部署/重新发布」等关键词
    3. 附件能解析出 title/slug，且 posts 目录有对应文件
    """
    if not file_refs:
        return None

    lowered = query.lower()
    redeploy_terms = (
        "重新部署", "再部署", "重新发布", "再发布",
        "更新部署", "更新发布", "重新上线", "再上线",
        "redeploy", "republish",
    )
    if not any(term in lowered for term in redeploy_terms):
        return None

    # 从附件 + 对话历史收集 markdown 源
    sources = _collect_hugo_markdown_sources(messages or [], query, file_refs)
    if not sources:
        return None

    label, text = sources[0]
    parsed = _parse_markdown_for_hugo(text, source_path=label)
    if not parsed:
        return None

    # 提取 frontmatter hints（slug/title 用于匹配已有文件）
    hints = _extract_frontmatter_hints(text)
    slug = hints.get("slug", "") or parsed.get("slug", "")
    title = hints.get("title", "") or parsed.get("title", "")
    if not slug and not title:
        return None

    # 找 posts 目录里已有的文件
    from skills.hugo_blog import POSTS_DIR, _safe_slug, _slug_from_post
    target: Path | None = None
    if slug:
        safe = _safe_slug(slug)
        direct = POSTS_DIR / f"{safe}.md"
        if direct.exists():
            target = direct
        else:
            for path in POSTS_DIR.glob("*.md"):
                if _slug_from_post(path) == safe or path.stem == safe:
                    target = path
                    break

    if target is None and title:
        for path in POSTS_DIR.glob("*.md"):
            file_hints = _extract_frontmatter_hints(path.read_text(encoding="utf-8", errors="ignore")[:2000])
            if file_hints.get("title", "") == title:
                target = path
                break

    if target is None:
        return None  # 没找到已有文件，不触发此捷径（交给 _try_direct_hugo_publish 创建新文章）

    # 读已有文件的 frontmatter，保留原 metadata
    existing_content = target.read_text(encoding="utf-8")
    existing_hints = _extract_frontmatter_hints(existing_content[:2000])
    final_title = existing_hints.get("title", title)
    final_slug = existing_hints.get("slug", _slug_from_post(target))

    # 用附件正文更新已有文件（保留原 frontmatter，替换正文）
    body = parsed.get("body", "")
    if len(body) < 40:
        # 正文太短，尝试合并其他源
        for _, alt_text in sources:
            alt_parsed = _parse_markdown_for_hugo(alt_text, source_path=label)
            if alt_parsed and len(alt_parsed.get("body", "")) > len(body):
                body = alt_parsed["body"]

    if len(body) < 40:
        return None  # 正文仍然太短，不触发此捷径

    # 重建文件：保留原 frontmatter + 新正文
    if existing_content.strip().endswith("---"):
        new_content = existing_content.strip() + "\n\n" + body + "\n"
    else:
        # 已有正文，替换：找第二个 --- 后面的内容
        parts = existing_content.split("---\n", 2)
        if len(parts) >= 3:
            new_content = parts[0] + "---\n" + parts[1] + "---\n\n" + body + "\n"
        else:
            new_content = existing_content  # 格式异常，不动文件

    target.write_text(new_content, encoding="utf-8")

    # 直接调用 deploy（不弹确认卡，直接执行）
    from core.tool_runtime import invoke as runtime_invoke
    from skills import hugo_blog as hugo_blog_module

    workflow_id = f"hugo-redeploy-{uuid4().hex[:8]}"
    event_id = f"{workflow_id}-deploy"
    target_url = f"https://iver.yivxer.com/posts/{final_slug}/"

    tr = runtime_invoke(
        "hugo_blog",
        {"action": "deploy", "filename": target.name},
        {"hugo_blog": hugo_blog_module},
    )

    if tr.ok:
        result_text = tr.content_preview or tr.summary
    else:
        err = tr.error or {}
        result_text = (
            f"枫弋札记重新部署失败："
            f"{err.get('type', 'Error')}: {err.get('message') or tr.summary}"
        )

    # 生成 tool_event（complete 或 blocked）
    status = "complete" if tr.ok else "blocked"
    tool_event = {
        "type": "tool_event",
        "toolEvent": {
            "id": event_id,
            "name": "hugo_blog",
            "status": status,
            "risk": "low",
            "summary": f"重新部署《{final_title}》",
            "detail": result_text,
            "requiresApproval": False,
            "draft": {
                "path": str(target),
                "title": final_title,
                "url": target_url,
                "action": "redeploy",
            },
        },
    }

    summary = _format_hugo_chat_summary(
        final_title,
        result_text,
        deploy_ok=tr.ok,
        prefix=f"已重新部署《{final_title}》到枫弋札记。" if tr.ok else f"重新部署《{final_title}》失败。",
    )

    return [tool_event], summary


_HUGO_AGENT_SYSTEM_PROMPT = """你是 Archer 的枫弋札记（博客）工作流执行器。

枫弋札记是用户的 Hugo 静态博客：
- 本地目录：/Users/Yivxer/yivxer-blog
- 文章目录：content/posts/
- 线上站点：https://iver.yivxer.com
- 合法分类：系统、健身、复盘、阅读、产品、写作、技术

## 硬性规则（不可违反）

1. **必须调用 hugo_blog 工具**：你不能直接生成「已部署」「部署成功」等回复。
   任何关于部署/发布/上线的回复，都必须基于 hugo_blog 工具的真实返回值。
   如果没调用工具就回复「部署好了」，那是幻觉，会被系统拦截并替换为兜底失败文案。

2. **action=deploy 必须传 filename 参数**：deploy 不传 filename 会被视为全站部署，
   且无法验证具体文章是否上线。正确流程是：
   - 先 action=list 或 action=read 拿到 filename
   - 再 action=deploy 传 filename 参数
   - 部署后工具会验证该文章 URL，返回 HTTP 状态

3. **必须根据工具返回的真实输出决定下一步**，不要编造结果。
   工具返回「构建失败」「部署失败」时，必须如实告诉用户失败原因，不能说「部署好了」。

## 禁止事项

- 禁止让用户手动复制正文
- 禁止让用户自己去终端执行命令
- 禁止说「我手里没有文章内容」（附件已注入系统消息，应主动查找）
- 禁止在未调用 hugo_blog 工具的情况下回复「部署成功/已部署/部署好了」

## 工作流

若系统消息或对话历史中已有附件 Markdown、title/slug frontmatter 或正文片段，必须优先使用；
用户说「部署一下」时，先 action=list，再按 slug/title 匹配已有文章；匹配到则直接 action=deploy。

若对话里只有 frontmatter 而本地 posts 目录已有同 slug 文件，直接 action=deploy，不要要求用户重贴正文。

当用户要部署时：
1. 先用 action=list 查看最近文章，判断要部署哪篇（未指定则部署全站）
2. 若对话里已有正文或用户指定了文章，用 action=read 检查 frontmatter 与 Markdown 结构
3. 结构不合规时用 action=edit 修正 title、description、category、body
4. 最后用 action=deploy 构建并同步上线（必须传 filename 参数）

当用户要删除、下架、移除某篇文章时：
1. 先用 action=list 或对话中的 title/slug/filename 找到目标文章
2. 用 action=delete 移出 content/posts
3. 再用 action=deploy 同步线上站点

当用户要写新文章并发布时：
1. 从对话整理 title、category、description、body（Markdown 正文）
2. 用 action=new 创建，再 action=deploy

完成后用简短中文告诉用户：做了什么、文章标题、是否部署成功、可访问地址。
如果工具返回失败，必须如实告知失败原因，不要说「部署好了」。"""


def _run_hugo_agent_turn(
    messages: list[dict],
    query: str,
    *,
    file_refs: list[dict] | None = None,
) -> tuple[list[dict], list[dict], str]:
    """LLM 驱动枫弋札记工作流；ALLOW 操作自动执行，不弹确认卡。"""
    if not _wants_hugo_publish(query, file_refs):
        return messages, [], ""

    from core.llm import call_with_tools
    from core.policy import check as policy_check, Decision
    from core.tool_runtime import invoke as runtime_invoke
    from skills.loader import load_skills, get_tools

    all_skills = load_skills()
    if "hugo_blog" not in all_skills:
        return messages, [], ""

    hugo_only = {"hugo_blog": all_skills["hugo_blog"]}
    tools = get_tools(hugo_only)
    if not tools:
        return messages, [], ""

    agent_messages: list[dict] = [
        {"role": "system", "content": _HUGO_AGENT_SYSTEM_PROMPT},
        *messages,
    ]
    tool_events: list[dict] = []
    final_text = ""

    # 根因 A 修复：跟踪 hugo_blog 是否被实际调用 + 是否有成功执行
    hugo_tool_invoked = False
    hugo_tool_succeeded = False

    for _ in range(8):
        try:
            msg = call_with_tools(agent_messages, tools)
        except Exception as exc:
            final_text = f"枫弋札记工作流中断：{exc}"
            break

        if not msg.tool_calls:
            # 根因 A 修复：LLM 没调用工具直接生成文本时，必须校验是否已成功执行 hugo_blog
            # 如果从未成功调用过 hugo_blog，LLM 的「部署好了」是幻觉，用兜底文案替换
            if not hugo_tool_succeeded:
                llm_text = (msg.content or "").strip()
                if hugo_tool_invoked:
                    # 调用过但都失败了 → 告知用户失败
                    final_text = "枫弋札记部署未能完成：hugo_blog 工具执行失败，请稍后重试或检查日志。"
                else:
                    # 压根没调用工具 → LLM 幻觉，明确告知用户未部署
                    final_text = "枫弋札记部署未执行：我未能正确调用 hugo_blog 工具完成部署，请重新告诉我文章内容或附件路径。"
                # 保留 LLM 原始回复到 tool_events 供 trace 追溯
                if llm_text and llm_text != final_text:
                    tool_events.append({
                        "type": "tool_event",
                        "toolEvent": {
                            "id": f"hugo-agent-hallucination-{uuid4().hex[:8]}",
                            "name": "hugo_blog",
                            "status": "blocked",
                            "risk": "high",
                            "summary": "LLM 未调用工具直接生成回复（已拦截幻觉）",
                            "detail": f"LLM 原始回复：{llm_text[:200]}",
                            "requiresApproval": False,
                        },
                    })
            else:
                final_text = (msg.content or "").strip()
            break

        agent_messages.append(_plain_chat_message(msg))

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            if fn_name != "hugo_blog":
                agent_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": "[不可用] 本轮仅允许 hugo_blog",
                })
                continue

            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            pr = policy_check(fn_name, fn_args, all_skills, cfg=_load_config())
            event_id = f"hugo-agent-{uuid4().hex[:8]}"
            action = str(fn_args.get("action", "") or "…")

            if pr.decision == Decision.DENY:
                tool_events.append({
                    "type": "tool_event",
                    "toolEvent": {
                        "id": event_id,
                        "name": "hugo_blog",
                        "status": "blocked",
                        "risk": pr.risk,
                        "summary": f"hugo_blog {action} 被策略拒绝",
                        "detail": pr.reason,
                        "requiresApproval": False,
                    },
                })
                agent_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"[策略拒绝] {pr.reason}",
                })
                continue

            hugo_tool_invoked = True
            tr = runtime_invoke(fn_name, fn_args, all_skills)
            if tr.ok:
                hugo_tool_succeeded = True
            tool_events.append(_tool_event_from_result(
                event_id,
                "hugo_blog",
                {
                    "ok": tr.ok,
                    "executed": tr.ok,
                    "output": tr.content_preview or tr.summary,
                    "summary": tr.summary,
                    "policy": {"risk": pr.risk},
                },
                summary=f"hugo_blog · {action}",
            ))
            agent_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tr.to_message_content() if tr.ok else f"[执行失败] {tr.summary}\n{tr.content_preview or ''}",
            })

    # 根因 A 修复：循环结束但从未成功调用 hugo_blog 时，兜底告知用户
    if not final_text and not hugo_tool_succeeded:
        if hugo_tool_invoked:
            final_text = "枫弋札记部署未能完成：hugo_blog 工具执行失败，请稍后重试或检查日志。"
        else:
            final_text = "枫弋札记部署未执行：未能正确调用 hugo_blog 工具，请重新告诉我文章内容或附件路径。"
    elif not final_text:
        for event in reversed(tool_events):
            tool_event = event.get("toolEvent", {})
            if tool_event.get("status") in ("complete", "blocked"):
                final_text = str(tool_event.get("detail") or tool_event.get("summary") or "").strip()
                if final_text:
                    break

    return messages, tool_events, final_text


def _run_desktop_tool_loop(
    messages: list[dict],
    selected_skills: set[str],
    query: str,
    max_rounds: int = 5,
) -> tuple[list[dict], list[dict]]:
    """在 Desktop API 中运行工具调用循环。

    针对 skill_router 选中但无专用 event builder 的技能，
    让 LLM 通过 function calling 自主决定调用哪些工具。

    - 低风险技能自动执行，结果注入 messages
    - 需确认的技能生成 tool_event 草稿卡

    Returns:
        (更新后的 messages, tool_events 列表)
    """
    from core.llm import call_with_tools
    from core.tool_runtime import invoke as runtime_invoke
    from skills.loader import load_skills, get_tools

    all_skills = load_skills()
    # 筛选：排除已有专用 builder 的、已自动执行的
    _HANDLED = {"obsidian_read", "obsidian_search", "obsidian_write",
                 "shell", "github_ops", "hugo_blog",
                 "web_search", "web_fetch"}
    loop_skills = {
        name: all_skills[name]
        for name in selected_skills
        if name in all_skills and name not in _HANDLED
    }
    if not loop_skills:
        return messages, []

    tools = get_tools(loop_skills)
    if not tools:
        return messages, []

    messages = list(messages)
    tool_events: list[dict] = []

    for _round in range(max_rounds):
        try:
            msg = call_with_tools(messages, tools)
        except Exception:
            break

        if not msg.tool_calls:
            break

        messages.append(_plain_chat_message(msg))

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            if fn_name not in loop_skills:
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": f"[不可用] 技能 {fn_name} 未在本次请求中触发",
                })
                continue

            skill_mod = loop_skills[fn_name]
            skill_meta = getattr(skill_mod, "SKILL", {})

            # 使用 policy 系统判断：ALLOW → 自动执行，CONFIRM → 草稿卡，DENY → 跳过
            from core.policy import check as policy_check, Decision

            pr = policy_check(fn_name, fn_args, loop_skills, cfg=_load_config())

            if pr.decision == Decision.DENY:
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": f"[策略拒绝] {pr.reason}",
                })
                continue

            if pr.decision == Decision.ALLOW:
                tr = runtime_invoke(fn_name, fn_args, loop_skills)
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": tr.to_message_content() if tr.ok else f"[执行失败] {tr.summary}",
                })
                continue

            # 需确认 → 生成草稿卡
            draft_id = f"tool-loop-{fn_name}-{uuid4().hex[:8]}"
            try:
                from core.api_tool_service import make_tool_request
                request = make_tool_request(
                    fn_name, fn_args, skills=loop_skills,
                    cfg=_load_config(),
                )
                blocked = request.get("blocked", False)
                policy = request.get("policy", {})
                risk = policy.get("risk", "medium")
                reason = policy.get("reason", "")

                draft = {
                    "eventId": draft_id,
                    "skillName": fn_name,
                    "args": fn_args,
                    "policy": policy,
                    "summary": f"{fn_name} — {reason or '等待确认'}",
                }
                set_tool_draft(draft_id, request)

                event = _tool_event(
                    draft_id, fn_name, "waiting", risk,
                    f"{fn_name} 等待确认",
                    f"参数: {json.dumps(fn_args, ensure_ascii=False)[:200]}\n{reason}",
                    requires_approval=True,
                    draft={"eventId": draft_id, "skillName": fn_name, "args": fn_args, "policy": policy},
                )
                tool_events.append(event)
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": f"[等待确认] 工具 {fn_name} 已生成确认卡片，由用户决定是否执行。请用一句话告诉用户你打算做什么，并提示在上方卡片确认。",
                })
            except Exception:
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": f"[系统错误] 无法为 {fn_name} 创建草稿",
                })

    # 注入最终回答提示
    messages.append({
        "role": "user",
        "content": "请用自然语言直接回答，总结你已完成的操作和结果。不要输出 XML 或 function call 语法。",
    })
    return messages, tool_events


# ---------------------------------------------------------------------------
# Tool event iterators (per skill)
# ---------------------------------------------------------------------------

def _iter_obsidian_search_events(query: str, plan):
    if not plan.should_run("obsidian_search"):
        return
    entry = plan.get("obsidian_search")
    args = entry.args if entry else {"keyword": query[:80], "max_results": 5}
    yield _execute_api_tool_preview(
        "obsidian_search",
        args,
        event_id="obsidian-search",
        display_name="obsidian_search",
        summary="Obsidian 搜索摘要完成",
    )


def _iter_obsidian_read_events(query: str, plan):
    if not plan.should_run("obsidian_read"):
        return
    entry = plan.get("obsidian_read")
    target_path = (entry.args.get("path") if entry else "") or _extract_obsidian_target_path(query)
    # 跳过无意义回退路径（说明用户没给出具体笔记名）
    if not target_path or target_path == "Archer/客户端写入草稿.md":
        return
    yield _execute_api_tool_preview(
        "obsidian_read",
        {"path": target_path, "max_chars": 4000},
        event_id=f"obsidian-read-{uuid4().hex[:8]}",
        display_name="obsidian_read",
        summary=f"读取 Obsidian 笔记：{target_path}",
    )


def _iter_obsidian_write_events(query: str, plan):
    if not plan.should_run("obsidian_write"):
        return
    draft_event_id = f"obsidian-write-{uuid4().hex[:8]}"
    draft_fields = _obsidian_write_draft(query)
    request = _make_api_tool_request(
        "obsidian_write",
        {
            "path": draft_fields["path"],
            "content": draft_fields["content"],
            "mode": draft_fields["mode"],
            "expected_mtime": draft_fields.get("expectedMtime"),
            "expected_size": draft_fields.get("expectedSize"),
            "expected_fingerprint": draft_fields.get("expectedFingerprint"),
        },
        event_id=draft_event_id,
        display_name="obsidian_write",
        extra={
            "path": draft_fields["path"],
            "mode": draft_fields["mode"],
            "contentPreview": draft_fields["contentPreview"],
            "beforeText": draft_fields.get("beforeText", ""),
            "afterText": draft_fields.get("afterText", ""),
            "previewMode": draft_fields.get("previewMode", draft_fields["mode"]),
            "previewExists": draft_fields.get("previewExists", False),
            "workIntent": _obsidian_work_intent(
                draft_fields["path"],
                draft_fields["mode"],
                before_text=draft_fields.get("beforeText", ""),
            ),
        },
        force_approval=False,
    )
    if request.get("blocked"):
        yield _tool_event_from_request(
            request,
            summary="Obsidian 写入被策略阻止",
            detail_prefix=f"path: {draft_fields['path']}, mode: {draft_fields['mode']}",
        )
        return

    if request.get("requiresApproval"):
        # 需要用户确认：存入 PENDING_TOOL_DRAFTS，等待前端 approve
        set_tool_draft(draft_event_id, request)
        yield _tool_event_from_request(
            request,
            summary=f"确认 Obsidian 写入：{draft_fields['contentPreview'][:80]}",
            detail_prefix=f"path: {draft_fields['path']}, mode: {draft_fields['mode']}",
        )
        return

    from core.api_tool_service import execute_tool_request
    from skills.loader import load_skills
    result = execute_tool_request(request, load_skills(), cfg=_load_config())
    output = str(result.get("output") or result.get("summary") or "")
    executed = bool(result.get("executed")) and not output.startswith(("路径被拒绝", "写入失败"))
    yield _tool_event(
        draft_event_id,
        "obsidian_write",
        "complete" if executed else "blocked",
        str(result.get("policy", {}).get("risk", "low")),
        "已直接写入 Obsidian" if executed else "Obsidian 写入失败",
        output[:300],
        False,
        {
            "path": draft_fields["path"],
            "mode": draft_fields["mode"],
            "contentPreview": draft_fields["contentPreview"],
        },
    )


def _iter_shell_events(query: str, plan):
    if not plan.should_run("shell"):
        return
    shell_event_id = f"shell-execute-{uuid4().hex[:8]}"
    entry = plan.get("shell")
    command = (entry.args.get("command") if entry else "") or _extract_shell_command(query)
    if not command or len(command) < 3:
        return  # 没有提取到有效命令，不弹卡片
    request = _make_api_tool_request(
        "shell", {"command": command},
        event_id=shell_event_id, display_name="shell.execute",
        extra={"command": command, "timeout": 30},
    )
    if not request.get("blocked"):
        set_tool_draft(shell_event_id, request)
    yield _tool_event_from_request(
        request,
        summary="已检测到 Shell 命令执行请求，等待确认",
        detail_prefix=f"command: {command[:200]}",
    )


def _iter_github_events(query: str, plan):
    if not plan.should_run("github_ops"):
        return
    github_event_id = f"github-{uuid4().hex[:8]}"
    entry = plan.get("github_ops")
    args = entry.args if entry and entry.args.get("action") else _extract_github_args(query)
    github_args = {
        "action": args["action"],
        "repo": args.get("repo", ""),
        "title": args.get("title", ""),
        "body": args.get("body", ""),
        "command": args.get("command", ""),
    }
    github_args = {k: v for k, v in github_args.items() if v}
    action_desc = {
        "list_repos": "列出 GitHub 仓库",
        "list_issues": "列出 Issue",
        "list_prs": "列出 Pull Request",
        "view_repo": "查看仓库",
        "create_issue": "创建 Issue",
        "run": "执行 gh 命令",
    }.get(args["action"], args["action"])
    summary = f"已检测到 GitHub 操作：{action_desc}，等待确认"
    request = _make_api_tool_request(
        "github_ops", github_args,
        event_id=github_event_id, display_name="github",
        extra=github_args,
    )
    if not request.get("blocked"):
        set_tool_draft(github_event_id, request)
    yield _tool_event_from_request(
        request, summary=summary,
        detail_prefix=f"action: {args['action']}, repo: {args.get('repo', '（当前用户）')}",
    )


_HUGO_CAPABILITY_TERMS = ("能不能", "可以吗", "还能不能", "是否", "吗", "?")


def _iter_hugo_blog_events(query: str):
    """枫弋札记请求改由 _run_hugo_agent_turn 处理，此处不再生成确认卡。"""
    return
    yield


def _generate_hugo_draft_from_reply(ai_reply: str) -> dict | None:
    """从 AI 回复中提取博客文章结构化内容。放宽格式容忍度。"""
    title = ""
    # 尝试多种标题格式：## Title / # Title / Title / **标题：xxx** / 标题：xxx / **标题**：xxx
    for pat in (
        r'^##?\s*(.+?)(?:\n|$)',
        r'\*\*标题[:：]\s*(.+?)\*\*',
        r'\*\*标题\*\*[:：]\s*(.+)',
        r'标题[:：]\s*(.+)',
        r'^(.+?)(?:\n\s*\n)',  # 兜底：第一段作为标题
    ):
        m = re.search(pat, ai_reply, re.MULTILINE)
        if m:
            title = m.group(1).strip().rstrip("*").strip()
            if title and len(title) > 1:
                break
            title = ""
    if not title:
        lines = [l.strip() for l in ai_reply.split("\n") if l.strip() and not l.strip().startswith(("<", "```"))]
        for line in lines[:5]:
            cleaned = line.lstrip("#*- ").strip()
            if len(cleaned) > 5:
                title = cleaned[:60].rstrip("，,.。")
                break
    if not title or len(title) < 2:
        return None

    category = "系统"
    VALID_CATS = ["系统", "健身", "复盘", "阅读", "产品", "写作", "技术"]
    for pat in (
        r'\*\*(?:分类|类别|标签|tag)[:：]\*\*\s*(\S+)',
        r'\*\*(?:分类|类别|标签|tag)[:：]\s*(.+?)\*\*',
        r'\*\*(?:分类|类别|标签|tag)\*\*[:：]\s*(.+)',
        r'(?:分类|类别|标签|tag)[:：]\s*(\S+)',
        r'[-\*]\s*(?:分类|类别|标签|tag)[:：]\s*(\S+)',
    ):
        m = re.search(pat, ai_reply, re.IGNORECASE)
        if m:
            cat = m.group(1).strip().rstrip("*").strip()
            for vc in VALID_CATS:
                if vc in cat:
                    category = vc
                    break
            break

    description = ""
    for pat in (
        r'\*\*摘要[:：]\s*(.+?)\*\*',
        r'\*\*摘要\*\*[:：]\s*(.+)',
        r'摘要[:：]\s*(.+)',
        r'[-\*]\s*摘要[:：]\s*(.+)',
    ):
        m = re.search(pat, ai_reply, re.IGNORECASE)
        if m:
            description = m.group(1).strip().rstrip("*").strip()[:200]
            break
    if not description:
        for line in ai_reply.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "<", "```", "*", "- [")):
                continue
            cleaned = stripped.lstrip("*- ").strip()
            if len(cleaned) > 20 and cleaned[:len(title)] != title:
                description = cleaned[:200]
                break

    body = ai_reply
    meta_pattern = re.compile(r'^.{0,5}(?:标题|分类|摘要|description|category|title)[:：]', re.IGNORECASE)
    lines = body.split("\n")
    content_lines = [l for l in lines if not meta_pattern.match(l.strip())]
    body = "\n".join(content_lines).strip()
    # 去掉标题行（多种格式）
    for title_pat in (
        r'^##?\s*' + re.escape(title) + r'\s*\n',
        r'^' + re.escape(title) + r'\s*\n',
    ):
        title_heading = re.match(title_pat, body)
        if title_heading:
            body = body[title_heading.end():].strip()
            break

    if not body or len(body) < 20:
        return None
    return {"title": title, "category": category, "description": description, "body": body}




def _generate_obsidian_draft_with_ai(query: str, messages: list[dict], ai_reply: str) -> str:
    """用 AI 基于完整对话上下文生成 Obsidian 写入内容。

    在主 AI 回复完成后调用，让 AI 综合对话全文 + 自身回复，
    提炼出结构化 Markdown 笔记，而非粗暴 regex 切用户原文。
    """
    from core.llm import stream_chat

    from core.writing import load_writing_prompt_blocks
    spec_blocks = load_writing_prompt_blocks(_load_config(), "note")
    system_prompt = (
        "你是 Archer 的 Obsidian 写作助手。"
        "请基于完整对话上下文，将需要记录的内容整理成结构化的 Markdown 笔记。\n\n"
        "如果用户要求修改、调整、润色或重写某个已有 Markdown 文件，"
        "请输出修改后的完整 Markdown 正文；保留原文中已有的 frontmatter、标题、链接和用户没有要求改动的主体结构。"
        "不要输出解释、diff 或额外说明。\n\n"
        + ("\n\n".join(spec_blocks) if spec_blocks else "")
        + "\n\n只输出笔记正文，第一行直接开始正文。"
    )

    gen_messages = [
        {"role": "system", "content": system_prompt},
        *messages,
        {"role": "assistant", "content": ai_reply},
        {"role": "user", "content": f"请基于以上对话内容，生成写入 Obsidian 的笔记。用户原始请求：{query}"},
    ]

    parts: list[str] = []
    for chunk in stream_chat(gen_messages, track_usage=False):
        if chunk:
            parts.append(chunk)
    return "".join(parts).strip()


_API_TOOL_EVENT_BUILDERS = {
    "obsidian_read": _iter_obsidian_read_events,
    "obsidian_search": _iter_obsidian_search_events,
    "shell": _iter_shell_events,
    "github_ops": _iter_github_events,
}


def _iter_api_tool_events(
    query: str,
    *,
    intent_info: dict | None = None,
    tool_plan=None,
    turn_plan=None,
):
    if turn_plan is not None:
        selected = turn_plan.filtered_skills
        tool_plan = turn_plan.tool_plan
    else:
        selected = _filter_api_skills_for_intent(query, _select_api_skills(query))
        if tool_plan is None:
            info = intent_info or {}
            tool_plan = _plan_desktop_tools(
                query, selected,
                intent=info.get("intent", "chat"),
                needs_tools=bool(info.get("needs_tools")),
                llm_fallback=True,
            )
    for skill_name, builder in _API_TOOL_EVENT_BUILDERS.items():
        if skill_name not in selected:
            continue
        yield from builder(query, tool_plan)


# ---------------------------------------------------------------------------
# Draft execution helpers (used by tool approval route)
# ---------------------------------------------------------------------------

def _append_obsidian_draft(draft: dict) -> str:
    path = str(draft.get("path", "")).strip()
    mode = str(draft.get("mode", "")).strip()
    content = str(draft.get("contentPreview", ""))
    if mode != "append":
        raise ValueError("only append mode is allowed for desktop write drafts")
    if not path or not content.strip():
        raise ValueError("draft path and contentPreview are required")
    from skills.obsidian_write import _resolve_note_path
    target = _resolve_note_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as f:
        f.write("\n" + content)
    return str(target)


def _execute_github_operation(draft: dict) -> str:
    try:
        from skills.github_ops import run as github_ops_run
        args = {
            "action": draft.get("action", ""),
            "repo": draft.get("repo", ""),
            "title": draft.get("title", ""),
            "body": draft.get("body", ""),
            "command": draft.get("command", ""),
        }
        args = {k: v for k, v in args.items() if v}
        result = github_ops_run(args)
        return result
    except Exception as exc:
        return f"GitHub 操作失败：{exc}"


# ---------------------------------------------------------------------------
# File reference context
# ---------------------------------------------------------------------------

def _latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", "")).strip()
    return ""


def _file_reference_context(
    file_refs: list[dict],
    per_file_limit: int = 6000,
    total_limit: int = 12000,
    max_file_bytes: int = 1_000_000,
) -> tuple[str, list[dict]]:
    return file_reference_context(
        file_refs,
        event_factory=_tool_event,
        allowed_extensions=TEXT_FILE_EXTENSIONS,
        per_file_limit=per_file_limit,
        total_limit=total_limit,
        max_file_bytes=max_file_bytes,
    )


# ---------------------------------------------------------------------------
# Simple chat (non-streaming)
# ---------------------------------------------------------------------------

def _chat(payload: dict) -> dict:
    messages = _clean_chat_messages(payload.get("messages"))
    from core.llm import stream_chat
    chunks: list[str] = []
    for chunk in stream_chat(messages):
        chunks.append(chunk)
    return {"role": "assistant", "text": "".join(chunks)}


# ---------------------------------------------------------------------------
# Background memory extraction
# ---------------------------------------------------------------------------

_api_extract_thread: threading.Thread | None = None
_api_extract_lock = threading.Lock()


def _yield_memory_compaction_events():
    """Run compaction if thresholds met; yield a lightweight tool event for Desktop."""
    try:
        from core.orchestrator import maybe_run_memory_compaction_after_turn

        result = maybe_run_memory_compaction_after_turn()
        if result and result.get("archivedCount", 0) > 0:
            yield _tool_event(
                f"memory-compact-{uuid4().hex[:8]}",
                "memory.compact",
                "complete",
                "low",
                "已整理记忆",
                (
                    f"archived: {result['archivedCount']}, "
                    f"summary_id: {result.get('summaryId')}, "
                    f"reason: {result.get('reason', '')}"
                ),
            )
    except Exception as exc:
        logger.warning("[memory] compaction failed: %s", exc)


def _should_auto_save_memory(memory: dict, sensitive: bool) -> bool:
    if sensitive:
        return False
    mtype = str(memory.get("type", "insight") or "insight")
    review_types = {
        "emotion_pattern",
        "value",
        "value_conflict",
        "life_theme",
        "self_narrative",
        "relationship_pattern",
        "project_mythology",
        "reflection_anchor",
    }
    if mtype in review_types:
        return False
    try:
        confidence = float(memory.get("confidence", 0.7) or 0.7)
    except Exception:
        confidence = 0.0
    try:
        depth = int(memory.get("depth", 3) or 3)
    except Exception:
        depth = 3
    return confidence >= 0.75 and depth <= 3


def _do_extract_api(history: list[dict]) -> None:
    if len(history) < 2:
        return
    try:
        from core.orchestrator import (
            build_memory_candidate_policy,
            format_memory_candidate_reason,
            orchestrate_user_input,
        )
        latest_user = _latest_user_text(history)
        policy = None
        suggest_reason = ""
        if latest_user:
            policy = build_memory_candidate_policy(
                orchestrate_user_input(latest_user, history=history[:-1])
            )
            if not policy.should_extract:
                logger.info("[memory] desktop extract skipped: no candidate policy")
                return
            suggest_reason = format_memory_candidate_reason(policy, latest_user)
        from memory.extract import extract
        from memory.store import add_pending, is_duplicate_pending, is_low_quality_memory, save
        extract_kwargs = {}
        if policy:
            extract_kwargs = {
                "candidate_types": policy.candidate_types,
                "sensitive": policy.sensitive,
            }
        mems, _ = extract(history, **extract_kwargs)
        staged = 0
        saved = 0
        skipped_dup = 0
        skipped_low = 0
        # Build session_summary: first user message, first 80 chars
        session_summary = ""
        for m in history:
            if m.get("role") == "user":
                content = str(m.get("content", "")).strip()
                if content:
                    session_summary = content[:80]
                    break
        for m in mems:
            content = m.get("content", "")
            mtype = m.get("type", "insight")
            # 质量过滤
            if is_low_quality_memory(content, mtype):
                skipped_low += 1
                continue
            # 去重
            if is_duplicate_pending(content):
                skipped_dup += 1
                continue
            if _should_auto_save_memory(m, policy.sensitive if policy else False):
                save(
                    content=content,
                    tags=m.get("tags", ""),
                    type=mtype,
                    importance=m.get("importance", 3),
                    source="desktop",
                    confidence=m.get("confidence", 0.7),
                    depth=m.get("depth", 3),
                    block_type=m.get("block_type"),
                    label=m.get("label"),
                )
                saved += 1
            else:
                add_pending(
                    content=content,
                    type=mtype,
                    importance=m.get("importance", 3),
                    tags=m.get("tags", ""),
                    source="desktop",
                    confidence=m.get("confidence", 0.7),
                    depth=m.get("depth", 3),
                    suggest_reason=suggest_reason,
                    block_type=m.get("block_type"),
                    label=m.get("label"),
                    session_summary=session_summary,
                )
                staged += 1
        logger.info(
            "[memory] desktop extract: saved %d, staged %d, skipped %d dup, %d low-quality",
            saved, staged, skipped_dup, skipped_low
        )
    except Exception as exc:
        logger.warning("[memory] desktop extract failed: %s", exc)


def _bg_extract_api(history: list[dict]) -> None:
    global _api_extract_thread
    # 加锁避免多请求并发时 TOCTOU 竞态导致重复启动提取线程
    with _api_extract_lock:
        if _api_extract_thread and _api_extract_thread.is_alive():
            return
        _api_extract_thread = threading.Thread(
            target=_do_extract_api, args=(list(history),), daemon=True
        )
        _api_extract_thread.start()


def _soul_insight_for_orchestration() -> dict:
    try:
        from core.orchestrator import collect_soul_insight_context

        return collect_soul_insight_context(limit=3)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Streaming chat with tool events
# ---------------------------------------------------------------------------

def _iter_simple_chat_path(
    messages: list[dict],
    *,
    query: str,
    intent_info: dict,
    file_refs: list[dict] | None,
    trace_id: str,
    memory_mode: str,
    obsidian_mode: str,
    runtime_context=None,
):
    """B5.1 simple path：轻量闲聊跳过 orchestration/router/memory/vault/tool_loop。

    只做：
    1. yield ready + 最小化 statusEvent
    2. 构建 enriched_messages（messages + file_context + vault focus）
    3. 构建简化 model_messages（core_persona + stance，无 task_plan/mode_constraint/matched_skills）
    4. 主模型 stream + heartbeat + DSML 救援 + fallback
    5. yield done
    """
    from core.model_select import resolve_active_model

    _cfg = _load_config()
    from core.experts import active_expert, format_expert_block, active_expert_id
    _expert = active_expert(_cfg)
    _expert_block = format_expert_block(_expert)

    # shadow initiative events（被动扫描，开销小，simple path 保留）
    for event in _yield_shadow_initiative_events(runtime_context):
        yield event

    # ready 信号
    yield {"type": "ready", "ready": True}

    # 最小化 statusEvent（让 UI 有锚点，不丢状态契约）
    yield _with_trace_id({
        "type": "statusEvent",
        "statusEvent": {
            "intentType": "chat",
            "intentLabel": intent_info.get("intent_label", "闲聊"),
            "matchedSkills": [],
            "isBackground": False,
            "memoryScope": [],
            "expertId": active_expert_id(_cfg),
            "expertLabel": str(_expert.get("label", "")),
            "traceId": trace_id,
            "simplePath": True,  # 标识 simple path，UI 可选简化渲染
        },
    }, trace_id)

    # enriched_messages = messages + file_context + vault focus
    enriched_messages = list(messages)
    file_context, file_events = _file_reference_context(file_refs or [])
    for event in file_events:
        yield event
    if file_context:
        enriched_messages = [{"role": "system", "content": file_context}, *enriched_messages]
    vault_result = assemble_vault_focus(
        enriched_messages,
        obsidian_mode=obsidian_mode,
        event_factory=_tool_event,
        include_tool_receipt=False,
    )
    enriched_messages = vault_result.messages
    yield from vault_result.events

    # 构建 system prompt（简化版：core_persona + stance + expert_block，无 task_plan）
    try:
        from core.context import build_desktop_core_prompt, _get_mode_prompt
        core_persona = build_desktop_core_prompt()
        stance_prompt = ""
        if _cfg["persona"].get("mode_auto", True):
            # simple path 不跑 orchestration，stance 用默认
            pass
        else:
            current_mode = _cfg["persona"].get("current_mode")
            if current_mode:
                stance_prompt = _get_mode_prompt(_cfg, current_mode)
        if stance_prompt:
            core_persona = f"{core_persona}\n\n{stance_prompt}"
        if _expert_block:
            core_persona = f"{core_persona}\n\n{_expert_block}"
    except Exception:
        core_persona = "Archer 的核心身份是长期陪伴型 AI 灵魂伴生体。"

    model_messages = assemble_model_messages(
        enriched_messages,
        core_persona=core_persona,
        simple=True,
    )

    # 主模型 stream
    has_images = bool(file_refs and any(r.get("type") == "image" for r in file_refs))
    active_model, _ = resolve_active_model(
        _load_config(),
        user_text=query,
        intent="chat",
        needs_tools=False,
        has_images=has_images,
    )
    ai_reply_parts: list[str] = []
    streamed_safe_text = ""
    fake_markup_detected = False
    try:
        for item in _iter_model_stream_with_heartbeat(model_messages, model=active_model):
            if item.get("type") == "heartbeat":
                yield {
                    "type": "statusEvent",
                    "statusEvent": {
                        "id": f"model-wait-{uuid4().hex[:8]}",
                        "intentType": "chat",
                        "intentLabel": "模型响应中",
                        "matchedSkills": [],
                        "isBackground": False,
                        "memoryScope": [],
                        "traceId": trace_id,
                    },
                }
                continue
            chunk = str(item.get("text") or "")
            if chunk:
                ai_reply_parts.append(chunk)
                if fake_markup_detected:
                    continue
                streamed_safe_text, safe_chunk, detected = _split_safe_model_chunk(streamed_safe_text, chunk)
                if safe_chunk:
                    yield {"type": "token", "text": safe_chunk}
                if detected:
                    fake_markup_detected = True
    except Exception as stream_exc:
        err_msg = str(stream_exc)[:300] or type(stream_exc).__name__
        if "rate" in err_msg.lower() or "limit" in err_msg.lower():
            yield {"type": "token", "text": "\n\n（请求太频繁，稍等几秒再试。）"}
        elif "timeout" in err_msg.lower() or "connect" in err_msg.lower():
            yield {"type": "token", "text": "\n\n（连接超时，请检查本地 API 是否正常运行。）"}
        else:
            yield {"type": "token", "text": f"\n\n（回复生成中断：{err_msg}）"}
        yield {
            "type": "failureHintEvent",
            "failureHintEvent": _failure_hint_event(
                stream_exc, stage="model_stream", trace_id=trace_id
            ),
        }
        yield {"type": "error", "detail": err_msg}
        yield {"type": "done", "done": True}
        return
    ai_reply = "".join(ai_reply_parts)

    # DSML / 伪 XML 救援
    if _has_fake_xml(ai_reply):
        rescue_messages = list(model_messages) + [
            {"role": "assistant", "content": ai_reply},
            {"role": "user", "content": (
                "你刚才输出了假标签（如 <读取文件>）或 DSML 标记，这些不会被执行。"
                "请直接用自然语言重新回答刚才的问题，不要输出任何 XML、伪标签或 function call 语法。"
            )},
        ]
        rescue_parts: list[str] = []
        try:
            for item in _iter_model_stream_with_heartbeat(rescue_messages, model=active_model):
                if item.get("type") == "heartbeat":
                    continue
                chunk = str(item.get("text") or "")
                if chunk:
                    rescue_parts.append(chunk)
                    yield {"type": "token", "text": chunk}
        except Exception:
            pass  # 救援失败保留原回复

    # B1.1: 模型无回复兜底
    if not ai_reply.strip():
        yield {"type": "token", "text": "模型没有返回内容，请重试或检查诊断。"}
        yield {
            "type": "failureHintEvent",
            "failureHintEvent": _failure_hint_event(
                RuntimeError("model_empty_response"),
                stage="model_stream",
                trace_id=trace_id,
            ),
        }

    yield {"type": "done", "done": True}


def _iter_chat_chunks(
    messages: list[dict],
    memory_mode: str = "conservative",
    obsidian_mode: str = "summary",
    file_refs: list[dict] | None = None,
    runtime_context=None,
):
    from core.llm import stream_chat

    classified_turn = classify_turn(messages)
    query = classified_turn.query
    trace_id = f"trace-{uuid4().hex[:12]}"
    _record_part8_shadow_material(messages, runtime_context)
    # 历史（不含当前这条用户消息），用于历史感知意图与检索改写
    prior_history = classified_turn.prior_history
    intent_info = classified_turn.intent_info
    # ── B5.1: simple path 分叉（轻量闲聊跳过 orchestration/router/memory/vault/tool_loop） ──
    try:
        from core.desktop_tool_router import is_simple_chat_path
        if is_simple_chat_path(query, intent_info, file_refs=file_refs):
            yield from _iter_simple_chat_path(
                messages, query=query, intent_info=intent_info,
                file_refs=file_refs, trace_id=trace_id,
                memory_mode=memory_mode, obsidian_mode=obsidian_mode,
                runtime_context=runtime_context,
            )
            return
    except Exception:
        pass  # simple path 判定异常 → 回退到 full path
    planned_turn = orchestrate_turn(
        query, prior_history, _soul_insight_for_orchestration()
    )
    orchestration = planned_turn.orchestration
    memory_scope = planned_turn.memory_scope
    task_plan_block = planned_turn.task_plan_block
    mode_constraint_block = planned_turn.mode_constraint_block
    matched_skills_block = planned_turn.matched_skills_block
    plan_event = planned_turn.plan_event
    orchestration_event = planned_turn.orchestration_event
    intent = intent_info["intent"]
    classifier_needs_tools = bool(intent_info.get("needs_tools"))
    needs_tools = bool(orchestration.needs_tools) if orchestration is not None else classifier_needs_tools
    from core.context import resolve_context_limits
    context_limits = resolve_context_limits(
        memory_scope,
        needs_memory=intent_info["needs_memory"],
        memory_mode=memory_mode,
    )
    _cfg = _load_config()
    from core.experts import active_expert, format_expert_block, active_expert_id
    _expert = active_expert(_cfg)
    _expert_block = format_expert_block(_expert)
    _scoped_skills = _expert_scoped_skills(_cfg)
    for event in _yield_shadow_initiative_events(runtime_context):
        yield event
    selected_turn_tools = select_turn_tools(
        query,
        _scoped_skills,
        intent=intent,
        needs_tools=needs_tools,
        planner=_plan_desktop_turn,
    )
    _turn_plan = selected_turn_tools.turn_plan
    _selected_tools = selected_turn_tools.selected_tools
    _tool_plan = selected_turn_tools.tool_plan
    # 动态对话姿态：优先使用 orchestrator 的 mode；手动锁定时让位
    active_stance = orchestration.mode if orchestration else None
    stance_prompt = ""
    try:
        from core.context import _get_mode_prompt
        if not _cfg["persona"].get("mode_auto", True):
            active_stance = _cfg["persona"].get("current_mode") or active_stance
        if active_stance:
            stance_prompt = _get_mode_prompt(_cfg, active_stance)
    except Exception:
        active_stance = None
        stance_prompt = ""
    enriched_messages = list(messages)
    file_context, file_events = _file_reference_context(file_refs or [])
    for event in file_events:
        yield event
    if file_context:
        enriched_messages = [
            {"role": "system", "content": file_context},
            *enriched_messages,
        ]
    vault_result = assemble_vault_focus(
        enriched_messages,
        obsidian_mode=obsidian_mode,
        event_factory=_tool_event,
        include_tool_receipt=True,
    )
    enriched_messages = vault_result.messages
    for event in vault_result.events:
        yield _with_trace_id(event, trace_id) if event.get("toolEvent") else event
    if orchestration_event:
        yield _with_trace_id({"type": "orchestrationEvent", "orchestrationEvent": orchestration_event}, trace_id)
    if plan_event:
        yield _with_trace_id({"type": "planEvent", "planEvent": plan_event}, trace_id)
    if orchestration is not None:
        yield _with_trace_id({
            "type": "runtimeContextEvent",
            "runtimeContextEvent": _runtime_context_event(
                query=query,
                intent_info=intent_info,
                orchestration=orchestration,
                file_refs=file_refs,
                trace_id=trace_id,
            ),
        }, trace_id)
        _matched_for_status = list(orchestration.matched_skills)
        from core.experts import expert_skill_allowlist
        _allowlist = expert_skill_allowlist(_expert)
        if _allowlist:
            _matched_for_status = [name for name in _matched_for_status if name in _allowlist]
        yield _with_trace_id({
            "type": "statusEvent",
            "statusEvent": {
                "intentType": intent_info["intent"],
                "intentLabel": intent_info.get("intent_label", intent_info["intent"]),
                "matchedSkills": _matched_for_status,
                "isBackground": orchestration.needs_job,
                "memoryScope": list(orchestration.memory_scope),
                "expertId": active_expert_id(_cfg),
                "expertLabel": str(_expert.get("label", "")),
            },
        }, trace_id)
    memory_result = assemble_memory_context(
        enriched_messages,
        query=query,
        prior_history=prior_history,
        intent=intent,
        needs_memory=bool(intent_info.get("needs_memory")),
        memory_mode=memory_mode,
        retrieve_limit=context_limits.retrieve_total,
        expert=_expert,
        event_factory=_tool_event,
    )
    enriched_messages = memory_result.messages
    yield from memory_result.events

    obsidian_result = assemble_obsidian_context(
        enriched_messages,
        query=query,
        obsidian_mode=obsidian_mode,
        preview_requested=bool(_tool_plan.obsidian_preview),
        event_factory=_tool_event,
        extract_target_path=_extract_obsidian_target_path,
    )
    enriched_messages = obsidian_result.messages
    yield from obsidian_result.events

    _pre_selected = _selected_tools
    web_result = assemble_web_context(
        enriched_messages,
        query=query,
        selected_tools=_pre_selected,
        event_factory=_tool_event,
        trace_event=lambda event: _with_trace_id(event, trace_id),
    )
    enriched_messages = web_result.messages
    yield from web_result.events

    # ── 枫弋札记：附件/路径直发 或 LLM 工具链，自动执行，不弹确认卡
    if _wants_hugo_publish(query, file_refs) and "hugo_blog" in _selected_tools:
        output: queue.Queue[tuple[str, object]] = queue.Queue()

        def run_hugo_workflow() -> None:
            try:
                direct = _try_direct_hugo_delete(query)
                if not direct:
                    # 优先尝试带附件重新部署（确定性路径，不弹确认卡，不进 LLM agent）
                    direct = _try_direct_hugo_redeploy_with_attachment(query, file_refs, messages=enriched_messages)
                if not direct:
                    direct = _try_direct_hugo_deploy_existing(enriched_messages, query)
                if not direct:
                    direct = _try_direct_hugo_publish(query, file_refs, messages=enriched_messages)
                if direct:
                    output.put(("result", direct))
                    return
                _, agent_events, agent_summary = _run_hugo_agent_turn(
                    enriched_messages, query, file_refs=file_refs,
                )
                output.put(("result", (agent_events, agent_summary)))
            except Exception as exc:
                output.put(("error", exc))

        thread = threading.Thread(target=run_hugo_workflow, daemon=True)
        thread.start()
        started = time.monotonic()
        while True:
            if time.monotonic() - started > HUGO_WORKFLOW_TOTAL_TIMEOUT_SECONDS:
                raise TimeoutError("hugo workflow total timeout")
            try:
                kind, value = output.get(timeout=HUGO_WORKFLOW_HEARTBEAT_SECONDS)
            except queue.Empty:
                yield {
                    "type": "statusEvent",
                    "statusEvent": {
                        "id": f"hugo-wait-{uuid4().hex[:8]}",
                        "intentType": intent,
                        "intentLabel": "枫弋札记部署中",
                        "matchedSkills": list(_selected_tools.keys()),
                        "isBackground": False,
                        "memoryScope": memory_scope,
                        "traceId": trace_id,
                    },
                }
                continue
            if kind == "error":
                raise value
            hugo_events, hugo_summary = value  # type: ignore[misc]
            break

        for event in hugo_events:
            yield _with_trace_id(event, trace_id)
        if any(
            isinstance(event, dict)
            and event.get("toolEvent", {}).get("status") == "blocked"
            for event in hugo_events
        ):
            yield {
                "type": "failureHintEvent",
                "failureHintEvent": _failure_hint_event(
                    RuntimeError(hugo_summary or "hugo workflow failed"),
                    stage="hugo_workflow",
                    trace_id=trace_id,
                ),
            }
        yield {"type": "ready", "ready": True}
        if hugo_summary:
            yield {"type": "token", "text": hugo_summary}
        else:
            yield {
                "type": "token",
                "text": "未能完成枫弋札记操作。请用附件添加 .md 文件，或说明要部署哪篇文章。",
            }
        yield {"type": "done", "done": True}
        return

    api_tool_events = list(_iter_api_tool_events(query, turn_plan=_turn_plan))

    # ── Desktop Tool Loop：让 LLM 通过 function calling 自主调用未被专用 builder 覆盖的技能 ──
    _all_selected = _selected_tools
    if _all_selected:
        enriched_messages, tool_loop_events = _run_desktop_tool_loop(
            enriched_messages, _all_selected, query,
        )
    else:
        tool_loop_events = []
    for event in tool_loop_events:
        yield _with_trace_id(event, trace_id)

    # ── 预检工具事件（Shell / GitHub / Obsidian 搜索） ──
    for event in api_tool_events:
        yield _with_trace_id(event, trace_id)

    def resolve_obsidian_event_path(path: str) -> str:
        from skills.obsidian_write import _resolve_note_path
        return str(_resolve_note_path(path))

    tool_summary = summarize_api_tool_events(
        api_tool_events,
        resolve_obsidian_path=resolve_obsidian_event_path,
    )
    direct_obsidian_writes = tool_summary.direct_obsidian_writes
    tool_notes = tool_summary.tool_notes

    # ── 通用技能宣告：告诉 LLM 所有被 skill_router 选中但无专用 event builder 的技能 ──
    _AUTO_EXECUTED_SKILLS = {"web_search", "web_fetch"}
    selected_skills = _selected_tools
    for skill_name in sorted(selected_skills):
        if skill_name in _API_TOOL_EVENT_BUILDERS or skill_name in _AUTO_EXECUTED_SKILLS:
            continue  # 已有专用 builder 或已自动执行注入上下文
        # 加载技能的简短描述
        try:
            from skills.loader import load_skills
            all_skills = load_skills()
            mod = all_skills.get(skill_name)
            if mod is None:
                continue
            desc = getattr(mod, 'SKILL', {}).get('description', '') or getattr(mod, '__doc__', '') or ''
            desc = desc.split('\n')[0].strip()[:80]
            if desc:
                skill_label = skill_name.replace('_', ' ')
                tool_notes.append(f"{skill_name} 可用——{desc}")
            else:
                tool_notes.append(f"{skill_name} 可用")
        except Exception:
            pass

    yield {"type": "ready", "ready": True}
    if direct_obsidian_writes:
        if len(direct_obsidian_writes) == 1:
            yield {"type": "token", "text": f"已写入 Obsidian：{direct_obsidian_writes[0]}。"}
        else:
            joined = "、".join(direct_obsidian_writes)
            yield {"type": "token", "text": f"已写入 Obsidian：{joined}。"}
        yield {"type": "done", "done": True}
        return

    # ── 检测 Obsidian 写入意图（非预检，不在此阶段弹草稿卡） ──
    obsidian_write_intent = _tool_plan.obsidian_write
    obsidian_target_path = _parse_obsidian_write_request(query).path if obsidian_write_intent else None

    # ── 构建 AI 系统提示词 ──
    # 想法3：桌面端与终端共用完整灵魂分层（COVENANT/PRESENCE/SOUL/MEMORY/mode/对峙提醒），
    # 并按桌面渲染允许 Markdown。记忆检索结果仍由上方 enriched_messages 单独注入，
    # 因此这里 db_memories 留空，避免重复。
    try:
        from core.context import build_system_prompt
        from memory.narrative import confrontation_hook
        from memory.emotion import infer_turn_emotion_hint
        from core.thread import resolve_topic_thread
        try:
            hints = confrontation_hook(query, prior_history)
        except Exception:
            hints = None
        emotion_hint = infer_turn_emotion_hint(query, prior_history)
        thread_hint = resolve_topic_thread(query, prior_history)
        core_persona = build_system_prompt(
            _cfg,
            db_memories="",
            heavy=intent_info["needs_memory"],
            intent=intent,
            user_input=query,
            confrontation_hints=hints or None,
            mode_override=active_stance,
            emotion_hint=emotion_hint,
            thread_hint=thread_hint,
            memory_scope=memory_scope,
            task_plan_block=task_plan_block,
            mode_constraint_block=mode_constraint_block,
            matched_skills_block=matched_skills_block,
            expert_block=_expert_block,
            needs_project_context=(
                orchestration.needs_project_context if orchestration else None
            ),
            context_limits=context_limits,
        )
    except Exception:
        try:
            from core.context import build_desktop_core_prompt
            core_persona = build_desktop_core_prompt()
            if stance_prompt:
                core_persona = f"{core_persona}\n\n{stance_prompt}"
        except Exception:
            core_persona = "Archer 的核心身份是长期陪伴型 AI 灵魂伴生体。"

    obsidian_hint = ""
    if obsidian_write_intent:
        obsidian_hint = (
            "\n\n用户希望写入 Obsidian，你需要在回复中整理要点，"
            "并告知用户回复完成后客户端会自动生成写入草稿卡片，用户点击「写入」后才会真正执行。"
            f"当前识别到的目标路径：{obsidian_target_path or '（待确认）'}。"
        )
    model_messages = assemble_model_messages(
        enriched_messages,
        core_persona=core_persona,
        tool_notes=tool_notes,
        obsidian_hint=obsidian_hint,
    )

    # ── AI 主回复（收集完整回复用于后续草稿生成） ──
    from core.model_select import resolve_active_model
    has_images = bool(file_refs and any(r.get("type") == "image" for r in file_refs))
    active_model, _ = resolve_active_model(
        _load_config(),
        user_text=query,
        intent=intent,
        needs_tools=bool(intent_info.get("needs_tools")),
        has_images=has_images,
    )
    ai_reply_parts: list[str] = []
    streamed_safe_text = ""
    fake_markup_detected = False
    try:
        for item in _iter_model_stream_with_heartbeat(model_messages, model=active_model):
            if item.get("type") == "heartbeat":
                yield {
                    "type": "statusEvent",
                    "statusEvent": {
                        "id": f"model-wait-{uuid4().hex[:8]}",
                        "intentType": intent,
                        "intentLabel": "模型响应中",
                        "matchedSkills": list(_selected_tools.keys()),
                        "isBackground": False,
                        "memoryScope": memory_scope,
                        "traceId": trace_id,
                    },
                }
                continue
            chunk = str(item.get("text") or "")
            if chunk:
                ai_reply_parts.append(chunk)
                if fake_markup_detected:
                    continue
                streamed_safe_text, safe_chunk, detected = _split_safe_model_chunk(streamed_safe_text, chunk)
                if safe_chunk:
                    yield {"type": "token", "text": safe_chunk}
                if detected:
                    fake_markup_detected = True
    except Exception as stream_exc:
        err_msg = str(stream_exc)[:300] or type(stream_exc).__name__
        if "rate" in err_msg.lower() or "limit" in err_msg.lower():
            yield {"type": "token", "text": f"\n\n（请求太频繁，稍等几秒再试。）"}
        elif "timeout" in err_msg.lower() or "connect" in err_msg.lower():
            yield {"type": "token", "text": f"\n\n（连接超时，请检查本地 API 是否正常运行。）"}
        else:
            yield {"type": "token", "text": f"\n\n（回复生成中断：{err_msg}）"}
        yield {"type": "failureHintEvent", "failureHintEvent": _failure_hint_event(stream_exc, stage="model_stream", trace_id=trace_id)}
        yield {"type": "error", "detail": err_msg}
        yield {"type": "done", "done": True}
        return
    ai_reply = "".join(ai_reply_parts)

    # ── DSML / 伪 XML 救援：DeepSeek 在多轮上下文中容易输出伪标签 ──
    # 移植自 terminal/archer.py:582-592，Desktop API 之前缺失此逻辑
    if _has_fake_xml(ai_reply):
        rescue_messages = list(model_messages) + [
            {"role": "assistant", "content": ai_reply},
            {"role": "user", "content": (
                "你刚才输出了假标签（如 <读取文件>）或 DSML 标记，这些不会被执行。"
                "请直接用自然语言重新回答刚才的问题，不要输出任何 XML、伪标签或 function call 语法。"
            )},
        ]
        rescue_parts: list[str] = []
        try:
            for item in _iter_model_stream_with_heartbeat(rescue_messages, model=active_model):
                if item.get("type") == "heartbeat":
                    yield {
                        "type": "statusEvent",
                        "statusEvent": {
                            "id": f"model-rescue-wait-{uuid4().hex[:8]}",
                            "intentType": intent,
                            "intentLabel": "模型修正中",
                            "matchedSkills": list(_selected_tools.keys()),
                            "isBackground": False,
                            "memoryScope": memory_scope,
                            "traceId": trace_id,
                        },
                    }
                    continue
                chunk = str(item.get("text") or "")
                if chunk:
                    rescue_parts.append(chunk)
                    yield {"type": "token", "text": chunk}
        except Exception:
            # 救援失败则保留原始回复
            pass
        else:
            if rescue_parts:
                ai_reply = "".join(rescue_parts)

    if not ai_reply.strip():
        had_tool_activity = bool(tool_loop_events or api_tool_events)
        # B1.1: 兜底 token —— 让终端/web/三方客户端都能拿到文案，不只依赖前端 failureHintFallback
        fallback_text = (
            "已执行操作，详见上方卡片。"
            if had_tool_activity else
            "模型没有返回内容，请打开诊断查看原因。"
        )
        yield {"type": "token", "text": fallback_text}
        yield {
            "type": "failureHintEvent",
            "failureHintEvent": {
                "id": f"failure-hint-{uuid4().hex[:8]}",
                "traceId": trace_id,
                "keyword": "tool_executed_no_summary" if had_tool_activity else "model_empty_response",
                "stage": "model_stream",
                "recoverable": True,
                "detail": (
                    "工具事件已产生，但模型没有返回总结文本。"
                    if had_tool_activity else
                    "模型请求结束但没有返回可显示文本。"
                ),
            },
        }

    # ── AI 回复完成后：生成 Obsidian 写入草稿 ──
    if obsidian_write_intent:
        try:
            parsed_write_request = _parse_obsidian_write_request(query)
            write_mode = parsed_write_request.mode
            ai_content = _generate_obsidian_draft_with_ai(query, enriched_messages, ai_reply)
            if ai_content:
                draft_event_id = f"obsidian-write-{uuid4().hex[:8]}"
                content_with_tag = ai_content if write_mode == "overwrite" else (
                    "\n<!-- Archer Desktop AI 生成 -->\n"
                    f"{ai_content}\n"
                )
                # 计算 before/after 预览
                try:
                    from skills.obsidian_write import compute_preview
                    preview = compute_preview({
                        "path": obsidian_target_path,
                        "content": content_with_tag,
                        "mode": write_mode,
                    })
                except Exception:
                    preview = None
                request = _make_api_tool_request(
                    "obsidian_write",
                    {
                        "path": obsidian_target_path,
                        "content": content_with_tag,
                        "mode": write_mode,
                        "expected_mtime": preview["mtime"] if preview else None,
                        "expected_size": preview["size"] if preview else None,
                        "expected_fingerprint": preview["fingerprint"] if preview else None,
                    },
                    event_id=draft_event_id,
                    display_name="obsidian_write",
                    extra={
                        "path": obsidian_target_path,
                        "mode": write_mode,
                        "contentPreview": ai_content[:500],
                        "beforeText": preview["before"] if preview else "",
                        "afterText": preview["after"] if preview else content_with_tag[:2000],
                        "previewMode": write_mode,
                        "previewExists": preview["exists"] if preview else False,
                        "workIntent": _obsidian_work_intent(
                            obsidian_target_path or "",
                            write_mode,
                            before_text=preview["before"] if preview else "",
                        ),
                    },
                    force_approval=False,
                )
                if request.get("blocked"):
                    yield _tool_event_from_request(
                        request,
                        summary="Obsidian 写入被策略阻止",
                        detail_prefix=f"path: {obsidian_target_path}",
                    )
                elif request.get("requiresApproval"):
                    set_tool_draft(draft_event_id, request)
                    yield _tool_event_from_request(
                        request,
                        summary=f"确认 Obsidian 写入：{ai_content[:80].strip()}",
                        detail_prefix=f"path: {obsidian_target_path}",
                    )
                else:
                    from core.api_tool_service import execute_tool_request
                    from skills.loader import load_skills
                    result = execute_tool_request(request, load_skills(), cfg=_load_config())
                    output = str(result.get("output") or result.get("summary") or "")
                    executed = bool(result.get("executed")) and not output.startswith(("路径被拒绝", "写入失败"))
                    yield _tool_event(
                        draft_event_id,
                        "obsidian_write",
                        "complete" if executed else "blocked",
                        str(result.get("policy", {}).get("risk", "low")),
                        "已直接写入 Obsidian" if executed else "Obsidian 写入失败",
                        output[:300],
                        False,
                        {
                            "path": obsidian_target_path,
                            "mode": write_mode,
                            "contentPreview": ai_content[:500],
                        },
                    )
            else:
                # AI 生成草稿内容为空——告知用户
                yield _tool_event(
                    f"obsidian-write-{uuid4().hex[:8]}",
                    "obsidian_write",
                    "blocked",
                    "low",
                    "Obsidian 写入草稿内容为空，请重试或手动指定内容",
                    f"path: {obsidian_target_path}, reason: AI content generation returned empty",
                    False,
                )
        except Exception as exc:
            yield _tool_event(
                f"obsidian-write-{uuid4().hex[:8]}",
                "obsidian_write",
                "blocked",
                "low",
                "Obsidian 写入草稿生成失败",
                str(exc)[:240],
                False,
            )

    # ── AI 回复完成后：生成 Hugo 博客写入草稿（枫弋札记专向请求已在 agent 阶段处理） ──
    hugo_blog_triggered = (
        not _wants_hugo_publish(query, file_refs)
        and any(
            isinstance(e, dict) and e.get("toolEvent", {}).get("name") == "hugo_blog"
            for e in api_tool_events
        )
    )
    if hugo_blog_triggered and ai_reply:
        try:
            hugo_draft = _generate_hugo_draft_from_reply(ai_reply)
            if hugo_draft and hugo_draft.get("body"):
                draft_event_id = f"hugo-blog-{uuid4().hex[:8]}"
                title_preview = hugo_draft.get("title", "无标题")[:40]
                request = _make_api_tool_request(
                    "hugo_blog",
                    {
                        "action": "new",
                        "title": hugo_draft.get("title", ""),
                        "category": hugo_draft.get("category", "系统"),
                        "description": hugo_draft.get("description", ""),
                        "body": hugo_draft.get("body", ""),
                    },
                    event_id=draft_event_id,
                    display_name="hugo_blog",
                    extra={
                        "title": hugo_draft.get("title", ""),
                        "category": hugo_draft.get("category", "系统"),
                        "contentPreview": hugo_draft.get("body", "")[:500],
                    },
                )
                if request.get("blocked"):
                    yield _tool_event_from_request(
                        request,
                        summary="博客发布被策略阻止",
                        detail_prefix=f"title: {title_preview}",
                    )
                elif request.get("requiresApproval"):
                    set_tool_draft(draft_event_id, request)
                    yield _tool_event_from_request(
                        request,
                        summary=f"确认发布博客文章：{title_preview}",
                        detail_prefix=f"action: new, title: {title_preview}, category: {hugo_draft.get('category', '系统')}",
                    )
                else:
                    from core.api_tool_service import execute_tool_request
                    from skills.loader import load_skills
                    result = execute_tool_request(request, load_skills(), cfg=_load_config())
                    output = str(result.get("output") or "")
                    executed = bool(result.get("executed"))
                    yield _tool_event(
                        draft_event_id,
                        "hugo_blog",
                        "complete" if executed else "blocked",
                        str(result.get("policy", {}).get("risk", "low")),
                        "已创建博客文章" if executed else "博客创建失败",
                        output[:300],
                        False,
                        {"title": hugo_draft.get("title", "")},
                    )
        except Exception as exc:
            yield _tool_event(
                f"hugo-blog-{uuid4().hex[:8]}",
                "hugo_blog",
                "blocked",
                "low",
                "博客草稿生成失败",
                str(exc)[:240],
                False,
            )

    for event in _yield_memory_compaction_events():
        yield event

    yield {"type": "done", "done": True}
