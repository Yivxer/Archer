"""
project_briefing: 指定项目 → 事件 + 相关记忆 → LLM 生成项目简报 → 输出到终端
"""
import sys

WORKFLOW = {
    "name": "briefing",
    "description": "某个项目的最新状态一键拉取，含相关记忆分析",
    "usage": "/workflow briefing [项目名称]",
}

_BRIEFING_PROMPT = """\
根据以下项目信息生成简洁的项目简报。格式：

**当前状态**（一句话，直接说）
**最近进展**（从事件推断，具体，不超过三点）
**未解决的问题**（从事件/记忆中提取，没有就写"暂无明确阻塞"）
**下一个明确动作**（最具体可执行的一步）

不要废话，不要鼓励。"""


def run(args: list[str], console, cfg: dict) -> None:
    from memory.store import (
        list_projects, get_project, get_project_by_name,
        get_project_events, search,
    )
    from core.llm import stream_chat

    # 确定目标项目
    proj = None
    if args:
        name = " ".join(args)
        proj = get_project_by_name(name)
        if not proj:
            console.print(f"[yellow]未找到项目：{name}[/yellow]")
            console.print("[dim]使用 /project list 查看所有项目。[/dim]")
            return
    else:
        active = [p for p in list_projects() if p.get("status") == "active"]
        if not active:
            console.print("[dim]没有活跃项目。使用 /project new <名称> 创建，或指定项目名称。[/dim]")
            return
        proj = active[0]  # 按 updated_at 降序，取最近的

    # 获取事件
    events = get_project_events(proj["id"], limit=20)
    evt_text = "\n".join(
        f"- {e['created_at'][:16]} [{e['event_type']}] {e['content'][:100]}"
        for e in events
    ) or "（暂无事件记录）"

    # 搜索相关记忆
    related = search(proj["name"], limit=8)
    mem_text = "\n".join(
        f"- [{m.get('type','')}] {m['content'][:100]}"
        for m in related
    ) or "（暂无相关记忆）"

    console.print(
        f"[dim]▶ 项目：{proj['name']}  {len(events)} 条事件  {len(related)} 条相关记忆…[/dim]\n"
    )

    messages = [
        {"role": "system", "content": _BRIEFING_PROMPT},
        {
            "role": "user",
            "content": (
                f"## 项目：{proj['name']}\n"
                f"描述：{proj.get('description') or '无'}\n"
                f"状态：{proj['status']}  更新：{proj['updated_at'][:16]}\n\n"
                f"## 事件记录（最近 {len(events)} 条）\n{evt_text}\n\n"
                f"## 相关记忆\n{mem_text}"
            ),
        },
    ]

    for chunk in stream_chat(messages):
        sys.stdout.write(chunk)
        sys.stdout.flush()
    sys.stdout.write("\n")
    sys.stdout.flush()
