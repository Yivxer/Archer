import tomllib
from datetime import datetime, timedelta
from pathlib import Path

SKILL = {
    "name": "weekly_review",
    "description": "生成本周复盘报告，整合 Obsidian 记忆、NEXT.md 和 MEMORY.md",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "weekly_review",
            "description": (
                "生成本周复盘报告。自动读取 Obsidian 中的 NEXT.md 和 MEMORY.md，"
                "结合用户输入生成结构化周复盘：完成了什么、没完成什么、下周优先级。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "week_summary": {
                        "type": "string",
                        "description": "本周主要做了什么（用户主动提供，可选）",
                    },
                    "focus": {
                        "type": "string",
                        "description": "本次复盘重点关注方向，例如「博客」「小程序」「身体状态」",
                    },
                },
            },
        },
    }

def run(args: dict) -> str:
    cfg_path = Path(__file__).parent.parent / "archer.toml"
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)

    vault        = Path(cfg["obsidian"]["vault_path"])
    week_summary = args.get("week_summary", "")
    focus        = args.get("focus", "")

    now        = datetime.now()
    week_start = now - timedelta(days=now.weekday())

    parts = [
        f"# 周复盘材料\n",
        f"**时间**：{now.strftime('%Y-%m-%d %H:%M')}",
        f"**本周**：{week_start.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}",
    ]
    if focus:
        parts.append(f"**复盘重点**：{focus}")

    next_path = vault / "20个人系统🚀/205AI记忆🦞/NEXT.md"
    if next_path.exists():
        content = next_path.read_text(encoding="utf-8")[:2000]
        parts.append(f"\n---\n\n## NEXT.md（当前计划与待办）\n\n{content}")

    memory_path = Path(cfg["persona"]["memory_path"])
    if memory_path.exists():
        content = memory_path.read_text(encoding="utf-8")[:1500]
        parts.append(f"\n---\n\n## MEMORY.md（当前状态）\n\n{content}")

    if week_summary:
        parts.append(f"\n---\n\n## 本周自述\n\n{week_summary}")

    parts.append(
        "\n---\n\n"
        "请基于以上材料生成本周复盘报告，包含：\n"
        "1. **完成了什么**（对照 NEXT.md，具体）\n"
        "2. **没完成什么，为什么**（不找借口，直说）\n"
        "3. **状态评估**（身体 / 情绪 / 精力 / 专注度）\n"
        "4. **下周三件事**（优先级排序，各一句话）\n"
        "5. **一句话校准**（当前方向是否偏了）\n\n"
        "风格：克制直接，不鸡汤，不空话，指向具体问题。"
    )

    return "\n".join(parts)
