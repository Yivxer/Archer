"""Tool event system and chat streaming for the Archer Desktop API."""

from __future__ import annotations

import json
import logging
import re
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
from terminal.api.chat_turn_context import FullTurnDependencies, prepare_full_turn
from terminal.api.hugo_turn import HugoTurnDependencies, iter_hugo_turn_events
from terminal.api.chat_reply import ChatReplyDependencies, iter_chat_reply_events
from terminal.api.post_reply_drafts import PostReplyDraftDependencies, iter_post_reply_draft_events
from terminal.api.turn_pipeline import (
    assemble_model_messages,
    classify_turn,
    orchestrate_turn,
    select_turn_tools,
    plain_chat_message as _plain_chat_message,
    trim_model_messages as _trim_model_messages_for_context,
)
from terminal.api.tool_stage import summarize_api_tool_events
from terminal.api.model_stream import has_fake_tool_markup as _has_fake_xml, iter_model_stream, iter_rescue_stream, select_model_for_turn, split_safe_model_chunk as _split_safe_model_chunk, stream_failure_events
from terminal.api.memory_extraction import _bg_extract_api, _do_extract_api
from terminal.api.turn_receipt import empty_reply_events, memory_compaction_events

logger = logging.getLogger("archer_api")
MODEL_STREAM_HEARTBEAT_SECONDS = 8.0
MODEL_STREAM_TOTAL_TIMEOUT_SECONDS = 180.0
HUGO_WORKFLOW_HEARTBEAT_SECONDS = 8.0
HUGO_WORKFLOW_TOTAL_TIMEOUT_SECONDS = 300.0

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
# Shared API tool helper compatibility facade
# ---------------------------------------------------------------------------

from terminal.api.api_tool_helpers import (
    _execute_api_tool_preview,
    _execute_shell_command,
    _expert_scoped_skills,
    _filter_api_skills_for_intent,
    _is_dangerous_shell,
    _make_api_tool_request,
    _obsidian_work_intent,
    _obsidian_write_draft,
    _select_api_skills,
    _tool_event,
    _tool_event_from_request,
    _tool_event_from_result,
)


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


# ---------------------------------------------------------------------------
# Hugo workflow compatibility facade
# ---------------------------------------------------------------------------

from terminal.api.hugo_workflow import (
    _collect_hugo_markdown_sources,
    _extract_frontmatter_hints,
    _extract_md_path_from_query,
    _extract_md_paths_from_text,
    _format_hugo_chat_summary,
    _hugo_confirmation_result,
    _hugo_workflow_event,
    _parse_markdown_for_hugo,
    _read_md_source,
    _run_hugo_agent_turn,
    _run_hugo_publish_workflow,
    _try_direct_hugo_delete,
    _try_direct_hugo_deploy_existing,
    _try_direct_hugo_publish,
    _try_direct_hugo_redeploy_with_attachment,
    _wants_hugo_delete,
)


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

def _yield_memory_compaction_events():
    from core.orchestrator import maybe_run_memory_compaction_after_turn
    yield from memory_compaction_events(
        compact=maybe_run_memory_compaction_after_turn,
        event_factory=_tool_event,
        warn=lambda detail: logger.warning("[memory] compaction failed: %s", detail),
    )


def _soul_insight_for_orchestration() -> dict:
    try:
        from core.orchestrator import collect_soul_insight_context

        return collect_soul_insight_context(limit=3)
    except Exception:
        return {}


def _full_turn_dependencies() -> FullTurnDependencies:
    from core.context import resolve_context_limits
    from core.experts import active_expert, active_expert_id, expert_skill_allowlist, format_expert_block

    return FullTurnDependencies(
        classify=classify_turn,
        orchestrate=orchestrate_turn,
        soul_insight=_soul_insight_for_orchestration,
        resolve_limits=resolve_context_limits,
        load_config=_load_config,
        active_expert=active_expert,
        active_expert_id=active_expert_id,
        expert_allowlist=expert_skill_allowlist,
        format_expert=format_expert_block,
        scoped_skills=_expert_scoped_skills,
        select_tools=lambda query, scoped_skills, **kwargs: select_turn_tools(
            query, scoped_skills, planner=_plan_desktop_turn, **kwargs,
        ),
        shadow_events=_yield_shadow_initiative_events,
        file_context=_file_reference_context,
        vault=assemble_vault_focus,
        memory=assemble_memory_context,
        obsidian=assemble_obsidian_context,
        web=assemble_web_context,
        event_factory=_tool_event,
        trace_event=_with_trace_id,
        runtime_event=_runtime_context_event,
        extract_obsidian_path=_extract_obsidian_target_path,
    )


def _hugo_turn_dependencies() -> HugoTurnDependencies:
    return HugoTurnDependencies(
        delete=_try_direct_hugo_delete,
        redeploy=lambda query, refs, messages: _try_direct_hugo_redeploy_with_attachment(
            query, refs, messages=messages,
        ),
        deploy_existing=_try_direct_hugo_deploy_existing,
        publish=lambda query, refs, messages: _try_direct_hugo_publish(
            query, refs, messages=messages,
        ),
        agent=lambda messages, query, refs: _run_hugo_agent_turn(
            messages, query, file_refs=refs,
        ),
        trace_event=_with_trace_id,
        failure_hint=_failure_hint_event,
    )


def _chat_reply_dependencies() -> ChatReplyDependencies:
    return ChatReplyDependencies(
        select_model=select_model_for_turn,
        load_config=_load_config,
        iter_stream=iter_model_stream,
        iter_rescue=iter_rescue_stream,
        has_fake_markup=_has_fake_xml,
        split_safe_chunk=_split_safe_model_chunk,
        failure_events=lambda exc, *, trace_id: stream_failure_events(
            exc,
            trace_id=trace_id,
            hint_factory=_failure_hint_event,
        ),
        empty_events=empty_reply_events,
    )


def _post_reply_draft_dependencies() -> PostReplyDraftDependencies:
    def compute_preview(payload: dict) -> dict:
        from skills.obsidian_write import compute_preview as preview

        return preview(payload)

    def execute_request(request: dict) -> dict:
        from core.api_tool_service import execute_tool_request
        from skills.loader import load_skills

        return execute_tool_request(request, load_skills(), cfg=_load_config())

    return PostReplyDraftDependencies(
        parse_obsidian=_parse_obsidian_write_request,
        generate_obsidian=_generate_obsidian_draft_with_ai,
        compute_preview=compute_preview,
        generate_hugo=_generate_hugo_draft_from_reply,
        make_request=_make_api_tool_request,
        event_from_request=_tool_event_from_request,
        set_draft=set_tool_draft,
        execute_request=execute_request,
        tool_event=_tool_event,
        obsidian_work_intent=_obsidian_work_intent,
    )


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
    active_model = select_model_for_turn(
        _load_config(), query=query, intent="chat", needs_tools=False,
        file_refs=file_refs, resolver=resolve_active_model,
    )
    ai_reply_parts: list[str] = []
    streamed_safe_text = ""
    fake_markup_detected = False
    try:
        for item in iter_model_stream(
            model_messages,
            heartbeat_seconds=MODEL_STREAM_HEARTBEAT_SECONDS,
            total_timeout_seconds=MODEL_STREAM_TOTAL_TIMEOUT_SECONDS,
            model=active_model,
        ):
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
        yield from stream_failure_events(stream_exc, trace_id=trace_id, hint_factory=_failure_hint_event)
        return
    ai_reply = "".join(ai_reply_parts)

    # DSML / 伪 XML 救援
    if _has_fake_xml(ai_reply):
        for item in iter_rescue_stream(
            model_messages, ai_reply, model=active_model,
            heartbeat_seconds=MODEL_STREAM_HEARTBEAT_SECONDS,
            total_timeout_seconds=MODEL_STREAM_TOTAL_TIMEOUT_SECONDS,
        ):
            if item.get("type") == "chunk":
                yield {"type": "token", "text": item["text"]}
            elif item.get("type") == "done" and item.get("text"):
                ai_reply = str(item["text"])

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
    prepared_turn = prepare_full_turn(
        messages,
        memory_mode=memory_mode,
        obsidian_mode=obsidian_mode,
        file_refs=file_refs,
        runtime_context=runtime_context,
        trace_id=trace_id,
        dependencies=_full_turn_dependencies(),
        classified_turn=classified_turn,
    )
    query = prepared_turn.query
    prior_history = prepared_turn.prior_history
    intent_info = prepared_turn.intent_info
    orchestration = prepared_turn.orchestration
    memory_scope = prepared_turn.memory_scope
    context_limits = prepared_turn.context_limits
    _cfg = prepared_turn.config
    _expert = prepared_turn.expert
    _expert_block = prepared_turn.expert_block
    task_plan_block = prepared_turn.task_plan_block
    mode_constraint_block = prepared_turn.mode_constraint_block
    matched_skills_block = prepared_turn.matched_skills_block
    _turn_plan = prepared_turn.turn_plan
    _selected_tools = prepared_turn.selected_tools
    _tool_plan = prepared_turn.tool_plan
    intent = intent_info["intent"]
    enriched_messages = prepared_turn.enriched_messages
    for event in prepared_turn.events:
        yield event
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
    # ── 枫弋札记：附件/路径直发 或 LLM 工具链，自动执行，不弹确认卡
    if _wants_hugo_publish(query, file_refs) and "hugo_blog" in _selected_tools:
        yield from iter_hugo_turn_events(
            query=query,
            file_refs=file_refs,
            messages=enriched_messages,
            intent=intent,
            selected_tools=_selected_tools,
            memory_scope=memory_scope,
            trace_id=trace_id,
            dependencies=_hugo_turn_dependencies(),
            heartbeat_seconds=HUGO_WORKFLOW_HEARTBEAT_SECONDS,
            total_timeout_seconds=HUGO_WORKFLOW_TOTAL_TIMEOUT_SECONDS,
        )
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

    ai_reply = yield from iter_chat_reply_events(
        model_messages,
        query=query,
        intent=intent,
        file_refs=file_refs,
        selected_tools=_selected_tools,
        memory_scope=memory_scope,
        trace_id=trace_id,
        had_tool_activity=bool(tool_loop_events or api_tool_events),
        runtime_context=runtime_context,
        dependencies=_chat_reply_dependencies(),
        heartbeat_seconds=MODEL_STREAM_HEARTBEAT_SECONDS,
        total_timeout_seconds=MODEL_STREAM_TOTAL_TIMEOUT_SECONDS,
    )
    if ai_reply is None:
        return

    hugo_blog_triggered = (
        not _wants_hugo_publish(query, file_refs)
        and any(
            isinstance(e, dict) and e.get("toolEvent", {}).get("name") == "hugo_blog"
            for e in api_tool_events
        )
    )
    yield from iter_post_reply_draft_events(
        query=query,
        messages=enriched_messages,
        ai_reply=ai_reply,
        obsidian_write_intent=obsidian_write_intent,
        obsidian_target_path=obsidian_target_path,
        hugo_blog_triggered=hugo_blog_triggered,
        dependencies=_post_reply_draft_dependencies(),
    )

    for event in _yield_memory_compaction_events():
        yield event

    yield {"type": "done", "done": True}
