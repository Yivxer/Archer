"""Tool event system and chat streaming for the Archer Desktop API."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
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

logger = logging.getLogger("archer_api")

# ---------------------------------------------------------------------------
# Intent detection helpers（委托 core/desktop_tool_router，保留旧函数名兼容测试）
# ---------------------------------------------------------------------------

from core.desktop_tool_router import (
    extract_github_args as _extract_github_args,
    extract_obsidian_target_path as _extract_obsidian_target_path,
    extract_obsidian_write_content as _extract_obsidian_write_content,
    extract_shell_command as _extract_shell_command,
    filter_skills_for_intent as _filter_skills_for_intent,
    plan_desktop_turn as _plan_desktop_turn,
    plan_desktop_tools as _plan_desktop_tools,
    should_draft_obsidian_write as _should_draft_obsidian_write,
    should_preview_obsidian as _should_preview_obsidian,
    should_trigger_github as _should_trigger_github,
    should_trigger_shell as _should_trigger_shell,
    wants_hugo_creation as _wants_hugo_creation,
    wants_hugo_deploy as _wants_hugo_deploy,
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
    return {"type": "tool_event", "toolEvent": tool_event}


def _obsidian_write_draft(query: str) -> dict:
    body = _extract_obsidian_write_content(query)
    content = (
        "\n<!-- Archer Desktop 自动写入 -->\n"
        f"{body}\n"
    )
    return {
        "path": _extract_obsidian_target_path(query),
        "mode": "append",
        "contentPreview": content[:500],
        "content": content,
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


def _select_api_skills(query: str, all_skills: dict | None = None) -> dict:
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
) -> dict:
    policy = result.get("policy", {})
    risk = policy.get("risk", "low")
    status = "complete" if result.get("ok") else "blocked"
    detail = str(result.get("output") or result.get("summary") or "")[:300]
    return _tool_event(
        event_id, name, status, risk,
        summary if result.get("ok") else f"{summary}失败",
        detail, False,
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

        messages.append(msg)

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
                    "content": f"[等待确认] 工具 {fn_name} 已生成确认卡片，由用户决定是否执行。请告知用户此操作正在等待确认。",
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
        },
        event_id=draft_event_id,
        display_name="obsidian_write",
        extra={
            "path": draft_fields["path"],
            "mode": draft_fields["mode"],
            "contentPreview": draft_fields["contentPreview"],
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
    """预检测博客发布/创建意图，告知 LLM 其拥有博客管理能力。

    明确的部署/上线请求会直接生成 hugo_blog(action=deploy) 确认卡；
    写新文章请求则先做能力宣告，让 LLM 生成合格 Markdown 内容，随后
    在 AI 回复完成后创建 hugo_blog(action=new) 确认卡。
    """
    lowered = query.lower()
    wants_deploy = _wants_hugo_deploy(query)
    wants_creation = _wants_hugo_creation(query)
    asks_capability = any(term in lowered for term in _HUGO_CAPABILITY_TERMS)

    if not wants_deploy and not wants_creation:
        return

    if wants_deploy and not wants_creation and not asks_capability:
        draft_event_id = f"hugo-blog-deploy-{uuid4().hex[:8]}"
        request = _make_api_tool_request(
            "hugo_blog",
            {"action": "deploy"},
            event_id=draft_event_id,
            display_name="hugo_blog",
            extra={"action": "deploy", "title": "部署枫弋札记"},
        )
        if not request.get("blocked"):
            set_tool_draft(draft_event_id, request)
        yield _tool_event_from_request(
            request,
            summary="确认部署枫弋札记",
            detail_prefix="action: deploy",
        )
        return

    # 直接用 skill_router 检测（已在 _iter_api_tool_events 中过滤）
    yield _tool_event(
        f"hugo-blog-ready-{uuid4().hex[:8]}",
        "hugo_blog",
        "waiting",
        "low",
        "博客管理能力已就绪",
        f"query: {query[:200]}\n"
        "你的回复将作为撰写博客的基础内容。请自然地在聊天回复中撰写文章正文（Markdown），"
        "客户端会将其提取为工具草稿并在 UI 上生成确认卡片供用户点击「写入」。"
        "点击「写入」后会自动：1) 写入文件 2) 运行 hugo 构建 3) rsync 部署到服务器。"
        "如有分步需求（仅新建/仅部署/新建+部署），请直接在回复中说明。",
        False,
        {"status": "ready", "mode": "blog_ready"},
    )


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
    "hugo_blog": _iter_hugo_blog_events,
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
        if skill_name == "hugo_blog":
            yield from builder(query)
        else:
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


def _clean_file_refs(raw: object) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("fileRefs must be a list")
    refs: list[dict] = []
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if not path:
            continue
        name = str(item.get("name", "")).strip() or Path(path).name
        size = item.get("size")
        try:
            clean_size = int(size) if size is not None else 0
        except (TypeError, ValueError):
            clean_size = 0
        refs.append({"path": path, "name": name[:180], "size": max(0, clean_size)})
    return refs


def _file_reference_context(
    file_refs: list[dict], per_file_limit: int = 6000, total_limit: int = 12000,
) -> tuple[str, list[dict]]:
    events: list[dict] = []
    sections: list[str] = []
    used = 0

    for idx, ref in enumerate(file_refs):
        path_value = str(ref.get("path", ""))
        display_name = str(ref.get("name") or Path(path_value).name or "未命名文件")
        event_id = f"file-reference-{idx + 1}"
        draft = {"path": path_value, "title": display_name, "size": ref.get("size", 0)}
        events.append(_tool_event(
            event_id, "file.reference", "running", "low",
            f"读取本地文件：{display_name}", path_value, draft=draft,
        ))
        try:
            path = Path(path_value).expanduser()
            suffix = path.suffix.lower()
            if suffix and suffix not in TEXT_FILE_EXTENSIONS:
                events.append(_tool_event(
                    event_id, "file.reference", "blocked", "low",
                    f"已跳过非文本文件：{display_name}",
                    f"extension: {suffix}", draft=draft,
                ))
                continue
            if not path.exists() or not path.is_file():
                events.append(_tool_event(
                    event_id, "file.reference", "blocked", "low",
                    f"文件不可读取：{display_name}", "file not found", draft=draft,
                ))
                continue
            if used >= total_limit:
                events.append(_tool_event(
                    event_id, "file.reference", "blocked", "low",
                    f"已跳过文件：{display_name}",
                    "total file reference limit reached", draft=draft,
                ))
                continue
            raw_text = path.read_text(encoding="utf-8", errors="ignore")
            if "\x00" in raw_text[:2048]:
                events.append(_tool_event(
                    event_id, "file.reference", "blocked", "low",
                    f"已跳过疑似二进制文件：{display_name}",
                    "binary-like content", draft=draft,
                ))
                continue
            remaining = max(0, total_limit - used)
            limit = min(per_file_limit, remaining)
            text = raw_text[:limit]
            used += len(text)
            truncated = len(raw_text) > len(text)
            sections.append(
                f"### {display_name}\n"
                f"path: {path}\n"
                f"truncated: {str(truncated).lower()}\n\n"
                f"{text}"
            )
            done_draft = {
                **draft,
                "contentPreview": text[:500],
                "injectedChars": len(text),
                "truncated": truncated,
            }
            events.append(_tool_event(
                event_id, "file.reference", "complete", "low",
                f"已注入本地文件：{display_name}",
                f"injected_chars: {len(text)}, truncated: {truncated}",
                draft=done_draft,
            ))
        except Exception as exc:
            events.append(_tool_event(
                event_id, "file.reference", "blocked", "low",
                f"文件引用失败：{display_name}", str(exc)[:240], draft=draft,
            ))

    if not sections:
        return "", events
    return (
        "以下是用户在桌面端明确选择并引用的本地文本文件内容。"
        "只在回答当前问题明显相关时使用；如果内容被截断，需要说明只能基于片段判断。\n\n"
        + "\n\n---\n\n".join(sections),
        events,
    )


# ---------------------------------------------------------------------------
# Mode cleaners
# ---------------------------------------------------------------------------

def _clean_memory_mode(value: object) -> str:
    if value in ("off", "conservative", "full"):
        return str(value)
    return "conservative"


def _clean_obsidian_mode(value: object) -> str:
    if value in ("off", "summary", "full"):
        return str(value)
    return "summary"


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


def _do_extract_api(history: list[dict]) -> None:
    if len(history) < 2:
        return
    try:
        from memory.extract import extract
        from memory.store import add_pending, is_duplicate_pending, is_low_quality_memory
        mems, _ = extract(history)
        staged = 0
        skipped_dup = 0
        skipped_low = 0
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
            add_pending(
                content=content,
                type=mtype,
                importance=m.get("importance", 3),
                tags=m.get("tags", ""),
                source="desktop",
                confidence=m.get("confidence", 0.7),
                depth=m.get("depth", 3),
            )
            staged += 1
        logger.info(
            "[memory] desktop extract: staged %d, skipped %d dup, %d low-quality",
            staged, skipped_dup, skipped_low
        )
    except Exception as exc:
        logger.warning("[memory] desktop extract failed: %s", exc)


def _bg_extract_api(history: list[dict]) -> None:
    global _api_extract_thread
    if _api_extract_thread and _api_extract_thread.is_alive():
        return
    _api_extract_thread = threading.Thread(
        target=_do_extract_api, args=(list(history),), daemon=True
    )
    _api_extract_thread.start()


# ---------------------------------------------------------------------------
# Streaming chat with tool events
# ---------------------------------------------------------------------------

def _iter_chat_chunks(
    messages: list[dict],
    memory_mode: str = "conservative",
    obsidian_mode: str = "summary",
    file_refs: list[dict] | None = None,
):
    from core.context import classify_query_intent, augment_retrieval_query
    from core.llm import stream_chat

    query = _latest_user_text(messages)
    # 历史（不含当前这条用户消息），用于历史感知意图与检索改写
    prior_history = messages[:-1] if (messages and messages[-1].get("role") == "user") else messages
    intent_info = classify_query_intent(query, history=prior_history, llm_fallback=True)
    intent = intent_info["intent"]
    _turn_plan = _plan_desktop_turn(
        query,
        intent=intent,
        needs_tools=bool(intent_info.get("needs_tools")),
        llm_fallback=True,
    )
    _selected_tools = _turn_plan.filtered_skills
    _tool_plan = _turn_plan.tool_plan
    # 动态对话姿态：桌面端也按当轮内容选 mode（与终端共用选择器）
    active_stance = None
    stance_prompt = ""
    try:
        from core.stance import resolve_active_stance, available_modes
        from core.context import _get_mode_prompt
        _cfg = _load_config()
        active_stance, _ = resolve_active_stance(
            _cfg, query, intent, available=available_modes(_cfg),
        )
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
    if memory_mode == "off":
        yield _tool_event(
            "memory-retrieve", "memory.retrieve", "complete", "low",
            "记忆上下文已关闭", "mode: off, injected: False",
        )
    else:
        limit = 10 if memory_mode == "full" else (7 if intent_info["needs_memory"] else 5)
        yield _tool_event(
            "memory-retrieve", "memory.retrieve", "running", "low",
            "检索与当前输入相关的本地记忆",
            f"mode: {memory_mode}, scope: local memory, limit: {limit}",
        )
        try:
            from memory.retrieve import for_context, format_for_prompt
            core, related = for_context(
                augment_retrieval_query(query, prior_history), limit=limit, intent=intent,
            )
            memory_context = format_for_prompt(core, related)
            if memory_context:
                enriched_messages = [
                    {
                        "role": "system",
                        "content": (
                            "以下是 Archer 本地记忆检索结果。只在明显相关时使用；"
                            "不要主动逐条展示记忆内容，也不要声称已经展示全部记忆。\n\n"
                            f"{memory_context}"
                        ),
                    },
                    *enriched_messages,
                ]
            yield _tool_event(
                "memory-retrieve", "memory.retrieve", "complete", "low",
                "已完成本地记忆检索",
                f"mode: {memory_mode}, core: {len(core)}, related: {len(related)}, injected: {bool(memory_context)}",
            )
        except Exception as exc:
            yield _tool_event(
                "memory-retrieve", "memory.retrieve", "blocked", "low",
                "本地记忆检索失败，已跳过", str(exc)[:240],
            )

    if obsidian_mode == "off":
        yield _tool_event(
            "obsidian-search", "obsidian_search", "complete", "low",
            "Obsidian 搜索上下文已关闭", "mode: off",
        )
    elif obsidian_mode in ("summary", "full") and _tool_plan.obsidian_preview:
        yield _tool_event(
            "obsidian-search", "obsidian_search", "running", "low",
            "检索 Obsidian 笔记",
            f"mode: {obsidian_mode}, max_results: 5",
        )
        try:
            from skills.obsidian_search import run as obsidian_search
            result = obsidian_search({"keyword": query[:80], "max_results": 5})
            yield _tool_event(
                "obsidian-search", "obsidian_search", "complete", "low",
                "Obsidian 搜索完成", f"mode: {obsidian_mode}, {result[:300]}",
            )

            # 检测用户是否给出了明确的笔记路径，若是则直接读取并注入
            targeted_path = _extract_obsidian_target_path(query)
            has_targeted = bool(targeted_path and targeted_path != "Archer/客户端写入草稿.md")
            injected_read = False
            if has_targeted:
                try:
                    from skills.obsidian_read import run as obsidian_read
                    content = obsidian_read({"path": targeted_path, "max_chars": 6000})
                    if not content.startswith("路径被拒绝") and not content.startswith("笔记不存在"):
                        enriched_messages = [
                            {"role": "system", "content": f"用户指定读取以下 Obsidian 笔记，请基于此内容回答：\n\n### {targeted_path}\n{content}"},
                            *enriched_messages,
                        ]
                        injected_read = True
                        yield _tool_event(
                            f"obsidian-read-{uuid4().hex[:8]}",
                            "obsidian_read", "complete", "low",
                            f"已读取并注入：{targeted_path}",
                            f"path: {targeted_path}, chars: {len(content)}",
                        )
                except Exception:
                    pass

            if obsidian_mode == "full" and not injected_read:
                note_paths = re.findall(r"  - (.+\.md)", result)
                context_parts: list[str] = []
                if note_paths:
                    from skills.obsidian_read import run as obsidian_read
                    for note_path in note_paths[:3]:
                        try:
                            content = obsidian_read({"path": note_path, "max_chars": 3000})
                            context_parts.append(f"### {note_path}\n{content}")
                        except Exception:
                            continue
                if context_parts:
                    obsidian_context = (
                        "以下是 Obsidian vault 中与当前对话相关的笔记内容。"
                        "请在回答时参考这些笔记，但不要逐条陈列搜索结果。\n\n"
                        + "\n\n---\n\n".join(context_parts)
                    )
                    enriched_messages = [
                        {"role": "system", "content": obsidian_context},
                        *enriched_messages,
                    ]
                elif "未找到" not in result:
                    enriched_messages = [
                        {"role": "system", "content": f"Obsidian vault 搜索结果：\n{result}"},
                        *enriched_messages,
                    ]
        except Exception as exc:
            yield _tool_event(
                "obsidian-search", "obsidian_search", "blocked", "low",
                f"Obsidian 搜索{'失败' if obsidian_mode == 'full' else '预览失败'}", str(exc)[:240],
            )
    elif obsidian_mode == "full":
        # full 模式下即使没命中关键词也做一次轻量搜索
        yield _tool_event(
            "obsidian-search", "obsidian_search", "running", "low",
            "检索 Obsidian 笔记（full 模式）",
            f"mode: full, keyword: {query[:80]}",
        )
        try:
            from skills.obsidian_search import run as obsidian_search
            result = obsidian_search({"keyword": query[:80], "max_results": 5})
            yield _tool_event(
                "obsidian-search", "obsidian_search", "complete", "low",
                "Obsidian 搜索完成", f"mode: full, {result[:300]}",
            )
            if "未找到" not in result:
                enriched_messages = [
                    {"role": "system", "content": f"Obsidian vault 搜索结果：\n{result}"},
                    *enriched_messages,
                ]
        except Exception as exc:
            yield _tool_event(
                "obsidian-search", "obsidian_search", "blocked", "low",
                "Obsidian 搜索失败", str(exc)[:240],
            )

    # ── Web Search 自动预检：当 skill_router 命中 web_search 时执行搜索并注入上下文 ──
    _pre_selected = _selected_tools
    if "web_search" in _pre_selected:
        yield _tool_event(
            "web-search", "web_search", "running", "low",
            "搜索互联网", f"query: {query[:80]}",
        )
        try:
            from skills.web_search import run as web_search_run
            search_result = web_search_run({"query": query[:200], "max_results": 5})
            search_text = str(search_result)[:800]
            yield _tool_event(
                "web-search", "web_search", "complete", "low",
                "搜索完成", search_text,
            )
            if search_result and not str(search_result).startswith("未找到"):
                enriched_messages = [
                    {"role": "system", "content": f"互联网搜索结果（{query[:80]}）：\n{search_result}"},
                    *enriched_messages,
                ]
        except Exception as exc:
            yield _tool_event(
                "web-search", "web_search", "blocked", "low",
                "搜索失败", str(exc)[:240],
            )
    if "web_fetch" in _pre_selected:
        url_match = re.search(r'https?://[^\s）+）"]+', query)
        if url_match:
            target_url = url_match.group(0).rstrip('.。，,;；')
            yield _tool_event(
                "web-fetch", "web_fetch", "running", "low",
                "抓取网页", target_url[:100],
            )
            try:
                from skills.web_fetch import run as web_fetch_run
                fetch_result = web_fetch_run({"url": target_url, "max_chars": 4000})
                fetch_text = str(fetch_result)[:800]
                yield _tool_event(
                    "web-fetch", "web_fetch", "complete", "low",
                    "网页抓取完成", fetch_text,
                )
                if fetch_result:
                    enriched_messages = [
                        {"role": "system", "content": f"网页内容（{target_url}）：\n{fetch_result}"},
                        *enriched_messages,
                    ]
            except Exception as exc:
                yield _tool_event(
                    "web-fetch", "web_fetch", "blocked", "low",
                    "抓取失败", str(exc)[:240],
                )

    # ── 预检工具事件。显式 Hugo 部署请求必须先于模型工具循环处理，
    # 避免用户只想确认部署时仍卡在“思考中”。
    api_tool_events = list(_iter_api_tool_events(query, turn_plan=_turn_plan))
    direct_hugo_deploy_approval = any(
        isinstance(event, dict)
        and event.get("toolEvent", {}).get("name") == "hugo_blog"
        and event.get("toolEvent", {}).get("requiresApproval")
        and event.get("toolEvent", {}).get("draft", {}).get("args", {}).get("action") == "deploy"
        for event in api_tool_events
    )
    if direct_hugo_deploy_approval:
        for event in api_tool_events:
            yield event
        yield {"type": "ready", "ready": True}
        yield {
            "type": "token",
            "text": "已准备部署枫弋札记，请在工具卡片中确认。确认后会执行 Hugo 构建、部署，并验证单页可访问。",
        }
        yield {"type": "done", "done": True}
        return

    # ── Desktop Tool Loop：让 LLM 通过 function calling 自主调用未被专用 builder 覆盖的技能 ──
    _all_selected = _selected_tools
    enriched_messages, tool_loop_events = _run_desktop_tool_loop(
        enriched_messages, _all_selected, query,
    )
    for event in tool_loop_events:
        yield event

    # ── 预检工具事件（Shell / GitHub / Obsidian 搜索） ──
    for event in api_tool_events:
        yield event

    direct_obsidian_writes: list[str] = []
    tool_notes: list[str] = []
    for event in api_tool_events:
        tool_event = event.get("toolEvent", {}) if isinstance(event, dict) else {}
        name = str(tool_event.get("name", ""))
        draft = tool_event.get("draft", {}) if isinstance(tool_event.get("draft"), dict) else {}
        if name == "obsidian_write" and tool_event.get("status") == "complete":
            raw_path = draft.get('path') or '未指定'
            try:
                from skills.obsidian_write import _resolve_note_path
                target_path = str(_resolve_note_path(raw_path))
            except Exception:
                target_path = str(raw_path)
            direct_obsidian_writes.append(target_path)
            tool_notes.append(f"已直接写入 Obsidian；目标路径：{target_path}。")
        elif name == "hugo_blog" and tool_event.get("status") in ("waiting", "ready"):
            tool_notes.append(
                "hugo_blog 工具可用——可以在回复中自然撰写 Markdown 格式的博客文章。"
                "客户端会在你回复完成后自动创建文章文件并提供部署确认卡片。"
                "如需新建文章请给出标题（## 开头）、分类和正文；如需部署已有文章请说明文件名。"
            )
        elif tool_event.get("requiresApproval") and "obsidian" in name:
            tool_notes.append(
                "已生成 Obsidian 写入草稿，正在等待用户在工具卡片点击「写入」确认；"
                f"目标路径：{draft.get('path') or draft.get('args', {}).get('path') or '未指定'}。"
            )
        elif tool_event.get("requiresApproval") and name:
            tool_notes.append(f"已生成 {name} 工具草稿，正在等待用户确认。")

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
    obsidian_target_path = _extract_obsidian_target_path(query) if obsidian_write_intent else None

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
            _load_config(),
            db_memories="",
            heavy=intent_info["needs_memory"],
            intent=intent,
            user_input=query,
            confrontation_hints=hints or None,
            mode_override=active_stance,
            emotion_hint=emotion_hint,
            thread_hint=thread_hint,
        )
    except Exception:
        try:
            from core.context import build_desktop_core_prompt
            core_persona = build_desktop_core_prompt()
            if stance_prompt:
                core_persona = f"{core_persona}\n\n{stance_prompt}"
        except Exception:
            core_persona = "Archer 的核心身份是长期陪伴型 AI 灵魂伴生体。"

    tool_context = ""
    if tool_notes:
        tool_context = "\n\n本轮本地客户端已经处理以下工具事件：\n- " + "\n- ".join(tool_notes)
    obsidian_hint = ""
    if obsidian_write_intent:
        obsidian_hint = (
            "\n\n用户希望写入 Obsidian，你需要在回复中整理要点，"
            "并告知用户回复完成后客户端会自动生成写入草稿卡片，用户点击「写入」后才会真正执行。"
            f"当前识别到的目标路径：{obsidian_target_path or '（待确认）'}。"
        )
    model_messages = [
        {
            "role": "system",
            "content": (
                "你正在 Archer Desktop 中回复用户。\n\n"
                + core_persona
                + ("\n\n工具事件由本地客户端处理；请直接自然回答，不要输出 XML、function_call、tool_call。"
                   if not tool_notes else
                   "本轮已触发的工具能力：" + tool_context
                   + "\n\n你可以自然地使用这些能力完成用户的要求——"
                   + "在你的回复中用自然语言描述你想做什么，客户端会自动处理执行细节。"
                   + "不要输出 XML 伪标签或 function call 语法。")
                + (obsidian_hint if obsidian_hint else "")
            ),
        },
        *enriched_messages,
    ]

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
    try:
        for chunk in stream_chat(model_messages, model=active_model):
            if chunk:
                ai_reply_parts.append(chunk)
                yield {"type": "token", "text": chunk}
    except Exception as stream_exc:
        err_msg = str(stream_exc)[:300] or type(stream_exc).__name__
        if "rate" in err_msg.lower() or "limit" in err_msg.lower():
            yield {"type": "token", "text": f"\n\n（请求太频繁，稍等几秒再试。）"}
        elif "timeout" in err_msg.lower() or "connect" in err_msg.lower():
            yield {"type": "token", "text": f"\n\n（连接超时，请检查本地 API 是否正常运行。）"}
        else:
            yield {"type": "token", "text": f"\n\n（回复生成中断：{err_msg}）"}
        yield {"type": "error", "detail": err_msg}
        yield {"type": "done", "done": True}
        return
    ai_reply = "".join(ai_reply_parts)

    # ── AI 回复完成后：生成 Obsidian 写入草稿 ──
    if obsidian_write_intent:
        try:
            ai_content = _generate_obsidian_draft_with_ai(query, enriched_messages, ai_reply)
            if ai_content:
                draft_event_id = f"obsidian-write-{uuid4().hex[:8]}"
                content_with_tag = (
                    "\n<!-- Archer Desktop AI 生成 -->\n"
                    f"{ai_content}\n"
                )
                request = _make_api_tool_request(
                    "obsidian_write",
                    {
                        "path": obsidian_target_path,
                        "content": content_with_tag,
                        "mode": "append",
                    },
                    event_id=draft_event_id,
                    display_name="obsidian_write",
                    extra={
                        "path": obsidian_target_path,
                        "mode": "append",
                        "contentPreview": ai_content[:500],
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
                            "mode": "append",
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

    # ── AI 回复完成后：生成 Hugo 博客写入草稿 ──
    hugo_blog_triggered = any(
        isinstance(e, dict) and e.get("toolEvent", {}).get("name") == "hugo_blog"
        for e in api_tool_events
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

    yield {"type": "done", "done": True}
