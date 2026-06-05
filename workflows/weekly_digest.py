"""
weekly_digest: 汇总近 N 天记忆 + 活跃项目事件 → LLM 生成周摘要 → 输出到终端
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

WORKFLOW = {
    "name": "digest",
    "description": "汇总近 N 天记忆 + 项目事件，生成周摘要（默认 7 天）",
    "usage": "/workflow digest [天数]",
}

_DIGEST_PROMPT = """\
根据以下材料生成简洁的周摘要。格式：

**这周做了什么**（从记忆和项目事件推断，具体，不鼓励）
**状态评估**（从记忆内容推断精力/情绪/专注方向，一句话）
**下周三件事**（从 NEXT.md 中提取最优先的三件，各一句）
**一个值得注意的信号**（从记忆/事件中找到一个模式或风险，具体说）

克制，不鸡汤，不废话。"""


def run(args: list[str], console, cfg: dict) -> None:
    from memory.store import list_all, list_projects, get_project_events
    from core.llm import stream_chat

    try:
        days = int(args[0]) if args else 7
        days = max(1, min(days, 30))
    except ValueError:
        days = 7

    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    # 收集最近记忆
    all_mems = list_all(300)
    recent_mems = [m for m in all_mems if (m.get("created_at") or "") >= cutoff_str]

    # 收集活跃项目事件
    projects = list_projects()
    active = [p for p in projects if p.get("status") == "active"]
    event_blocks = []
    for proj in active[:6]:
        events = get_project_events(proj["id"], limit=30)
        recent = [e for e in events if (e.get("created_at") or "") >= cutoff_str]
        if recent:
            lines = "\n".join(
                f"  - {e['created_at'][:16]} {e['content'][:80]}"
                for e in recent[:12]
            )
            event_blocks.append(f"【{proj['name']}】\n{lines}")

    # 读取 NEXT.md
    next_path = Path(cfg["persona"]["memory_path"]).parent / "NEXT.md"
    next_content = ""
    if next_path.exists():
        next_content = next_path.read_text(encoding="utf-8")[:1500]

    if not recent_mems and not event_blocks:
        console.print(f"[dim]最近 {days} 天没有记录（记忆和项目事件均为空）。[/dim]")
        return

    mem_text = "\n".join(
        f"- [{m.get('type','')}] {m['content'][:100]}"
        for m in recent_mems[:25]
    )
    evt_text = "\n\n".join(event_blocks) if event_blocks else "（无活跃项目事件）"

    total_events = sum(len(b.strip().split("\n")) - 1 for b in event_blocks)
    console.print(
        f"[dim]▶ 汇总：{len(recent_mems)} 条记忆，{total_events} 条事件，"
        f"{days} 天范围…[/dim]\n"
    )

    messages = [
        {"role": "system", "content": _DIGEST_PROMPT},
        {
            "role": "user",
            "content": (
                f"## 最近 {days} 天记忆（{len(recent_mems)} 条）\n{mem_text or '（无）'}\n\n"
                f"## 项目事件\n{evt_text}\n\n"
                f"## NEXT.md（当前计划）\n{next_content or '（未找到）'}"
            ),
        },
    ]

    for chunk in stream_chat(messages):
        sys.stdout.write(chunk)
        sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()
