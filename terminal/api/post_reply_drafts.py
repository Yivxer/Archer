"""Post-model draft effects for Obsidian and non-direct Hugo requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from uuid import uuid4


@dataclass(frozen=True)
class PostReplyDraftDependencies:
    parse_obsidian: Callable
    generate_obsidian: Callable
    compute_preview: Callable
    generate_hugo: Callable
    make_request: Callable
    event_from_request: Callable
    set_draft: Callable
    execute_request: Callable
    tool_event: Callable
    obsidian_work_intent: Callable


def iter_post_reply_draft_events(
    *, query: str, messages: list[dict], ai_reply: str, obsidian_write_intent: bool,
    obsidian_target_path: str | None, hugo_blog_triggered: bool,
    dependencies: PostReplyDraftDependencies,
):
    if obsidian_write_intent:
        try:
            parsed = dependencies.parse_obsidian(query)
            write_mode = parsed.mode
            content = dependencies.generate_obsidian(query, messages, ai_reply)
            if not content:
                yield dependencies.tool_event(
                    f"obsidian-write-{uuid4().hex[:8]}", "obsidian_write", "blocked", "low",
                    "Obsidian 写入草稿内容为空，请重试或手动指定内容",
                    f"path: {obsidian_target_path}, reason: AI content generation returned empty", False,
                )
            else:
                event_id = f"obsidian-write-{uuid4().hex[:8]}"
                tagged_content = content if write_mode == "overwrite" else (
                    "\n<!-- Archer Desktop AI 生成 -->\n" + content + "\n"
                )
                try:
                    preview = dependencies.compute_preview({
                        "path": obsidian_target_path,
                        "content": tagged_content,
                        "mode": write_mode,
                    })
                except Exception:
                    preview = None
                request = dependencies.make_request(
                    "obsidian_write",
                    {
                        "path": obsidian_target_path,
                        "content": tagged_content,
                        "mode": write_mode,
                        "expected_mtime": preview["mtime"] if preview else None,
                        "expected_size": preview["size"] if preview else None,
                        "expected_fingerprint": preview["fingerprint"] if preview else None,
                    },
                    event_id=event_id,
                    display_name="obsidian_write",
                    extra={
                        "path": obsidian_target_path,
                        "mode": write_mode,
                        "contentPreview": content[:500],
                        "beforeText": preview["before"] if preview else "",
                        "afterText": preview["after"] if preview else tagged_content[:2000],
                        "previewMode": write_mode,
                        "previewExists": preview["exists"] if preview else False,
                        "workIntent": dependencies.obsidian_work_intent(
                            obsidian_target_path or "", write_mode,
                            before_text=preview["before"] if preview else "",
                        ),
                    },
                    force_approval=False,
                )
                if request.get("blocked"):
                    yield dependencies.event_from_request(
                        request, summary="Obsidian 写入被策略阻止",
                        detail_prefix=f"path: {obsidian_target_path}",
                    )
                elif request.get("requiresApproval"):
                    dependencies.set_draft(event_id, request)
                    yield dependencies.event_from_request(
                        request, summary=f"确认 Obsidian 写入：{content[:80].strip()}",
                        detail_prefix=f"path: {obsidian_target_path}",
                    )
                else:
                    result = dependencies.execute_request(request)
                    output = str(result.get("output") or result.get("summary") or "")
                    executed = bool(result.get("executed")) and not output.startswith(("路径被拒绝", "写入失败"))
                    yield dependencies.tool_event(
                        event_id, "obsidian_write", "complete" if executed else "blocked",
                        str(result.get("policy", {}).get("risk", "low")),
                        "已直接写入 Obsidian" if executed else "Obsidian 写入失败",
                        output[:300], False,
                        {"path": obsidian_target_path, "mode": write_mode, "contentPreview": content[:500]},
                    )
        except Exception as exc:
            yield dependencies.tool_event(
                f"obsidian-write-{uuid4().hex[:8]}", "obsidian_write", "blocked", "low",
                "Obsidian 写入草稿生成失败", str(exc)[:240], False,
            )

    if hugo_blog_triggered and ai_reply:
        try:
            draft = dependencies.generate_hugo(ai_reply)
            if not draft or not draft.get("body"):
                return
            event_id = f"hugo-blog-{uuid4().hex[:8]}"
            title = draft.get("title", "无标题")[:40]
            request = dependencies.make_request(
                "hugo_blog",
                {
                    "action": "new",
                    "title": draft.get("title", ""),
                    "category": draft.get("category", "系统"),
                    "description": draft.get("description", ""),
                    "body": draft.get("body", ""),
                },
                event_id=event_id,
                display_name="hugo_blog",
                extra={
                    "title": draft.get("title", ""),
                    "category": draft.get("category", "系统"),
                    "contentPreview": draft.get("body", "")[:500],
                },
            )
            if request.get("blocked"):
                yield dependencies.event_from_request(
                    request, summary="博客发布被策略阻止", detail_prefix=f"title: {title}",
                )
            elif request.get("requiresApproval"):
                dependencies.set_draft(event_id, request)
                yield dependencies.event_from_request(
                    request, summary=f"确认发布博客文章：{title}",
                    detail_prefix=(
                        f"action: new, title: {title}, category: {draft.get('category', '系统')}"
                    ),
                )
            else:
                result = dependencies.execute_request(request)
                output = str(result.get("output") or "")
                executed = bool(result.get("executed"))
                yield dependencies.tool_event(
                    event_id, "hugo_blog", "complete" if executed else "blocked",
                    str(result.get("policy", {}).get("risk", "low")),
                    "已创建博客文章" if executed else "博客创建失败", output[:300], False,
                    {"title": draft.get("title", "")},
                )
        except Exception as exc:
            yield dependencies.tool_event(
                f"hugo-blog-{uuid4().hex[:8]}", "hugo_blog", "blocked", "low",
                "博客草稿生成失败", str(exc)[:240], False,
            )
