"""
task_manager — 结构化任务管理

封装 memory/work.py 的 Work Item CRUD，
让 AI 能够自助创建、追踪、更新「工作项」。

API 完整覆盖 memory/work.py：
- create / get / list_active / list_all
- update_status / add_checklist_item / check_item
- add_artifact / delete
"""
from pathlib import Path

SKILL = {
    "name": "task_manager",
    "description": "结构化任务管理：创建、追踪、更新 Work Item，支持检查清单和附件",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "low",
    "default_timeout": 15,
}

# 懒导入，避免循环
def _work():
    from memory.work import (
        create, get, list_active, list_all,
        update_status, add_checklist_item, check_item,
        add_artifact, delete,
        WORK_STATUSES,
    )
    return {
        "create": create,
        "get": get,
        "list_active": list_active,
        "list_all": list_all,
        "update_status": update_status,
        "add_checklist_item": add_checklist_item,
        "check_item": check_item,
        "add_artifact": add_artifact,
        "delete": delete,
        "WORK_STATUSES": WORK_STATUSES,
    }


# ── Schema ─────────────────────────────────────────────────────────

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "task_manager",
            "description": (
                "管理 Work Item（结构化任务项）。"
                "支持创建任务、追踪进度（检查清单 + 状态）、关联附件。"
                "可配合 /work 命令查看 UI。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "create", "list", "get",
                            "update_status", "add_checklist",
                            "check_item", "delete",
                        ],
                        "description": "操作类型",
                    },
                    "title": {
                        "type": "string",
                        "description": "任务标题（action=create 时必填）",
                    },
                    "description": {
                        "type": "string",
                        "description": "任务详细说明（action=create 时使用）",
                    },
                    "checklist": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "初始检查项列表（action=create 时使用）",
                    },
                    "work_id": {
                        "type": "integer",
                        "description": "Work Item ID（action=get/update_status/add_checklist/check_item/delete 时必填）",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "done", "cancelled"],
                        "description": "更新后的状态（action=update_status 时使用）",
                    },
                    "item_text": {
                        "type": "string",
                        "description": "新增检查项文字（action=add_checklist 时使用）",
                    },
                    "item_index": {
                        "type": "integer",
                        "description": "要勾选/取消的检查项序号（从 1 开始，action=check_item 时使用）",
                    },
                    "checked": {
                        "type": "boolean",
                        "description": "勾选=True / 取消=False，默认 True",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "列表返回数量上限，默认 20（active）/ 50（all）",
                    },
                    "list_type": {
                        "type": "string",
                        "enum": ["active", "all"],
                        "description": "列表类型，默认 active（仅未完成）",
                    },
                },
                "required": ["action"],
            },
        },
    }


# ── Run ────────────────────────────────────────────────────────────

def run(args: dict) -> str:
    action = args.get("action", "").strip()
    w = _work()
    WSTAT = w["WORK_STATUSES"]

    # ── create ──────────────────────────────────────────────────
    if action == "create":
        title = args.get("title", "").strip()
        if not title:
            return "错误：action=create 需要 title 参数"
        desc     = args.get("description", "").strip()
        checklist = args.get("checklist", None) or None
        wid = w["create"](title=title, description=desc, checklist=checklist)
        item = w["get"](wid)
        lines = [f"✅ Work Item #{wid} 已创建"]
        lines += _fmt_item(item)
        return "\n".join(lines)

    # ── list ─────────────────────────────────────────────────────
    if action == "list":
        ltype = args.get("list_type", "active").strip()
        limit = int(args.get("limit", 20 if ltype == "active" else 50))
        rows = w["list_active"](limit=limit) if ltype == "active" else w["list_all"](limit=limit)
        if not rows:
            return f"没有{ltype} 类型的任务"
        lines = [f"📋 {ltype} 任务列表（{len(rows)} 条）：\n"]
        for r in rows:
            status_icon = {"pending": "⏳", "in_progress": "🔄", "done": "✅", "cancelled": "❌"}.get(r["status"], "❔")
            lines.append(f"{status_icon} #{r['id']} [{r['status']}] {r['title']}")
            if r.get("description"):
                lines.append(f"   {r['description'][:80]}")
        return "\n".join(lines)

    # ── get ─────────────────────────────────────────────────────
    if action == "get":
        wid = int(args.get("work_id", 0))
        if wid <= 0:
            return "错误：action=get 需要 work_id 参数（整数）"
        item = w["get"](wid)
        if not item:
            return f"Work Item #{wid} 不存在"
        return "\n".join(_fmt_item(item))

    # ── update_status ────────────────────────────────────────────
    if action == "update_status":
        wid    = int(args.get("work_id", 0))
        status = args.get("status", "").strip()
        if wid <= 0:
            return "错误：action=update_status 需要 work_id 参数"
        if status not in WSTAT:
            return f"错误：status 必须是以下之一：{WSTAT}"
        ok = w["update_status"](wid, status)
        if not ok:
            return f"Work Item #{wid} 不存在，状态更新失败"
        return f"✅ #{wid} 状态已更新为 [{status}]"

    # ── add_checklist ───────────────────────────────────────────
    if action == "add_checklist":
        wid  = int(args.get("work_id", 0))
        text = args.get("item_text", "").strip()
        if wid <= 0:
            return "错误：action=add_checklist 需要 work_id 参数"
        if not text:
            return "错误：action=add_checklist 需要 item_text 参数"
        ok = w["add_checklist_item"](wid, text)
        if not ok:
            return f"Work Item #{wid} 不存在"
        return f"✅ #{wid} 已新增检查项：「{text}」"

    # ── check_item ──────────────────────────────────────────────
    if action == "check_item":
        wid  = int(args.get("work_id", 0))
        idx  = int(args.get("item_index", 0))
        chk  = bool(args.get("checked", True))
        if wid <= 0 or idx <= 0:
            return "错误：action=check_item 需要 work_id 和 item_index（从 1 开始）"
        ok = w["check_item"](wid, idx, chk)
        if not ok:
            return f"#{wid} 不存在或检查项 {idx} 越界"
        verb = "勾选" if chk else "取消勾选"
        return f"✅ #{wid} 检查项 #{idx} 已{verb}"

    # ── delete ──────────────────────────────────────────────────
    if action == "delete":
        wid = int(args.get("work_id", 0))
        if wid <= 0:
            return "错误：action=delete 需要 work_id 参数"
        ok = w["delete"](wid)
        if not ok:
            return f"Work Item #{wid} 不存在"
        return f"🗑️  Work Item #{wid} 已删除"

    return (
        f"错误：未知 action「{action}」\n"
        "可用 action：create / list / get / update_status / "
        "add_checklist / check_item / delete"
    )


# ── Format helpers ──────────────────────────────────────────────

def _fmt_item(item: dict) -> list[str]:
    lines = [
        f"📌 #{item['id']} [{item['status']}] {item['title']}",
        f"   创建时间：{item['created_at']}",
    ]
    if item.get("description"):
        lines.append(f"   描述：{item['description']}")
    checklist = item.get("checklist", [])
    if checklist:
        done_count = sum(1 for c in checklist if c.get("done"))
        lines.append(f"   检查清单（{done_count}/{len(checklist)} 完成）：")
        for i, c in enumerate(checklist, 1):
            icon = "✅" if c.get("done") else "⬜"
            lines.append(f"   {icon} {i}. {c['item']}")
    artifacts = item.get("artifacts", [])
    if artifacts:
        lines.append(f"   附件（{len(artifacts)} 个）：")
        for a in artifacts:
            lines.append(f"   - {a}")
    return lines
