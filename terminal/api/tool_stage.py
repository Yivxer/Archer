"""Tool selection, approval messaging, and execution receipt helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class ToolEventSummary:
    direct_obsidian_writes: list[str]
    tool_notes: list[str]


def parse_approval_decision(payload: dict) -> tuple[str, str]:
    event_id = str(payload.get("eventId", "")).strip()
    decision = str(payload.get("decision", "")).strip()
    if not event_id:
        raise ValueError("eventId is required")
    if decision not in ("approved", "denied"):
        raise ValueError("decision must be approved or denied")
    return event_id, decision


def reuse_cached_approval(event_id: str, get_result: Callable[[str], dict | None]) -> dict | None:
    cached_result = get_result(event_id)
    if not cached_result:
        return None
    cached_result["reused"] = True
    return cached_result


def reuse_fingerprint_approval(event_id: str, fingerprint: str, cached: dict | None, *, permission_level: str) -> dict | None:
    if not cached:
        return None
    response = dict(cached)
    response.update({"eventId": event_id, "reused": True, "fingerprint": fingerprint, "idempotencyReason": "same_fingerprint", "permissionLevel": permission_level})
    return response


def build_denied_response(event_id: str) -> dict:
    return {"ok": True, "eventId": event_id, "decision": "denied", "executed": False, "output": "", "message": "已取消，未执行。"}


def summarize_api_tool_events(
    events: list[dict],
    *,
    resolve_obsidian_path: Callable[[str], str] | None = None,
) -> ToolEventSummary:
    direct_obsidian_writes: list[str] = []
    tool_notes: list[str] = []
    for event in events:
        tool_event = event.get("toolEvent", {}) if isinstance(event, dict) else {}
        name = str(tool_event.get("name", ""))
        raw_draft = tool_event.get("draft")
        draft = raw_draft if isinstance(raw_draft, dict) else {}
        if name == "obsidian_write" and tool_event.get("status") == "complete":
            raw_path = str(draft.get("path") or "未指定")
            target_path = raw_path
            if resolve_obsidian_path is not None:
                try:
                    target_path = str(resolve_obsidian_path(raw_path))
                except Exception:
                    target_path = raw_path
            direct_obsidian_writes.append(target_path)
            tool_notes.append(f"已直接写入 Obsidian；目标路径：{target_path}。")
        elif name == "hugo_blog" and tool_event.get("status") in ("waiting", "ready"):
            tool_notes.append(
                "hugo_blog 工具可用——可以在回复中自然撰写 Markdown 格式的博客文章。"
                "客户端会在你回复完成后自动创建文章并直接部署到枫弋札记（无需确认卡片）。"
                "如需新建文章请给出标题（## 开头）、分类和正文；如需部署已有文章请说明文件名。"
            )
        elif tool_event.get("requiresApproval") and "obsidian" in name:
            nested_args = draft.get("args") if isinstance(draft.get("args"), dict) else {}
            target_path = draft.get("path") or nested_args.get("path") or "未指定"
            tool_notes.append(
                "已生成 Obsidian 写入草稿，正在等待用户在工具卡片点击「写入」确认；"
                f"目标路径：{target_path}。"
            )
        elif tool_event.get("requiresApproval") and name:
            tool_notes.append(f"已生成 {name} 工具草稿，正在等待用户确认。")
    return ToolEventSummary(direct_obsidian_writes, tool_notes)
