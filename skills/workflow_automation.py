"""
workflow_automation — 自动化工作流设计与配置生成

帮助用户设计自动化工作流（Zapier / Make / n8n 风格），
生成可导入的配置文件或操作清单。

输入：触发条件 + 目标动作
输出：工作流设计文档 + 配置示例（JSON/YAML）
"""
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

SKILL = {
    "name": "workflow_automation",
    "description": "自动化工作流设计：触发条件→动作链路，支持 Zapier/Make/n8n 配置导出",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "low",
    "default_timeout": 45,
}

# ── 懒加载 LLM ───────────────────────────────────────────────

def _llm_stream(prompt: str) -> str:
    from core.llm import stream_chat
    parts = []
    for chunk in stream_chat([{"role": "user", "content": prompt}]):
        if isinstance(chunk, str):
            parts.append(chunk)
    return "".join(parts)


# ── 内置触发器和动作模板 ───────────────────────────────────

_TRIGGER_TEMPLATES: dict[str, list[str]] = {
    "schedule":    ["定时触发（每日/每周/每小时）", "Cron 表达式"],
    "webhook":    ["HTTP Webhook 接收数据", "支持 GET/POST/PUT"],
    "email":      ["新邮件到达", "Gmail / Outlook 集成"],
    "form":       ["表单提交（Typeform / Google Forms）", "新回复触发"],
    "rss":        ["RSS 订阅更新", "监测特定关键词"],
    "file":       ["新文件到达（Google Drive / Dropbox）", "云盘变更"],
    "social":     ["新 Tweet / 新微博 / 新评论", "社交平台触发"],
    "database":   ["数据库新增行 / 记录更新", "Airtable / MySQL / Supabase"],
    "manual":     ["手动按钮触发", "人工审批节点"],
}

_ACTION_TEMPLATES: dict[str, list[str]] = {
    "email":    ["发送邮件（Gmail / Outlook）", "支持模板变量"],
    "sms":      ["发送短信（Twilio）", "支持批量发送"],
    "webhook":  ["调用 Webhook（POST JSON）", "传递数据到下游系统"],
    "sheet":    ["写入 Google Sheets / Excel", "新增行 / 更新单元格"],
    "database": ["写入 Airtable / Supabase / MySQL", "结构化存储"],
    "slack":    ["发送 Slack 消息", "支持频道 / 私信"],
    "notify":   ["系统通知 / 浏览器推送", "Toast 提示"],
    "file":     ["生成 PDF / CSV 文件", "保存结果到云盘"],
    "ai":       ["调用 AI 处理（摘要/分类/生成）", "LLM 节点"],
    "condition": ["条件分支（If/Else）", "多路路由"],
    "delay":    ["延迟等待（分钟/小时/天）", "定时重试"],
    "loop":     ["循环处理（For Each）", "批量操作"],
}


# ── Schema ─────────────────────────────────────────────────────

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "workflow_automation",
            "description": (
                "设计和配置自动化工作流（Zapier/Make/n8n 风格）。"
                "输入触发条件和目标动作，输出工作流文档和配置。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["design", "list_templates"],
                        "description": "design=设计新工作流；list_templates=列出可用触发/动作模板",
                    },
                    "description": {
                        "type": "string",
                        "description": "工作流描述（action=design 时必填）：什么触发→做什么→什么结果",
                    },
                    "trigger_type": {
                        "type": "string",
                        "enum": ["schedule", "webhook", "email", "form", "rss", "file", "social", "database", "manual", "auto"],
                        "description": "触发类型，auto=让 AI 自动判断（action=design 时使用）",
                    },
                    "target_platform": {
                        "type": "string",
                        "enum": ["zapier", "make", "n8n", "ifttt", "custom"],
                        "description": "目标自动化平台，默认 zapier",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "保存路径（.md 设计文档 / .json 配置），填写后自动保存",
                    },
                },
                "required": ["action"],
            },
        },
    }


# ── Run ─────────────────────────────────────────────────────

def run(args: dict) -> str:
    action = args.get("action", "").strip()

    if action == "list_templates":
        return _list_templates()

    if action == "design":
        return _design(args)

    return f"错误：未知 action「{action}」，请用 design 或 list_templates"


def _list_templates() -> str:
    lines = ["📋 可用触发类型：\n"]
    for k, vs in _TRIGGER_TEMPLATES.items():
        lines.append(f"**{k}**")
        for v in vs:
            lines.append(f"  - {v}")
        lines.append("")
    lines.append("\n📋 可用动作类型：\n")
    for k, vs in _ACTION_TEMPLATES.items():
        lines.append(f"**{k}**")
        for v in vs:
            lines.append(f"  - {v}")
        lines.append("")
    return "\n".join(lines)


def _design(args: dict) -> str:
    description     = args.get("description", "").strip()
    trigger_type   = args.get("trigger_type", "auto").strip()
    target_platform = args.get("target_platform", "zapier").strip()
    save_path      = args.get("save_path", "").strip() or None

    if not description:
        return "错误：action=design 需要 description 参数（工作流描述）"

    trigger_hint = ""
    if trigger_type != "auto":
        trigger_hint = f"触发类型固定为：{trigger_type}\n"

    prompt = (
        "你是一位自动化工作流架构师。请为以下需求设计完整工作流。\n\n"
        f"需求描述：{description}\n"
        f"{trigger_hint}"
        f"目标平台：{target_platform}\n\n"
        "输出格式（Markdown）：\n"
        "1. 工作流名称（简洁）\n"
        "2. 触发条件（Trigger）\n"
        "3. 动作链路（Step 1 → Step 2 → ...）\n"
        "4. 每个步骤的：输入 / 处理逻辑 / 输出 / 错误处理\n"
        "5. 变量映射表（上一步输出→下一步输入）\n"
        "6. 平台配置示例（JSON/YAML，可导入格式）\n"
        "7. 注意事项 & 限制\n"
        "要求：具体可执行，不要写「配置相关账号」这种空话。"
    )

    result = _llm_stream(prompt)

    resp = f"✅ 工作流设计完成（平台：{target_platform}）\n\n{result}"
    if save_path:
        p = Path(save_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# 自动化工作流设计\n\n{result}", encoding="utf-8")
        resp += f"\n\n✅ 已保存到：{p}"

    return resp
