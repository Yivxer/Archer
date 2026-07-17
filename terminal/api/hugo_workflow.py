"""Deterministic Hugo publish, delete, redeploy, and agent fallback workflow."""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from core.desktop_tool_router import wants_hugo_publish as _wants_hugo_publish
from terminal.api._config import _load_config, set_tool_draft
from terminal.api.api_tool_helpers import (
    _make_api_tool_request,
    _tool_event_from_request,
    _tool_event_from_result,
)
from terminal.api.turn_pipeline import plain_chat_message as _plain_chat_message

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
    # “发布 / 重新部署”已经由用户的明确指令授权，直接执行一次即可。
    # 删除仍保留确认卡，避免不可逆操作被误触发。
    if action in {"publish", "deploy"}:
        return _run_hugo_publish_workflow(
            title=title,
            actions=[("deploy", args)],
        )

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

