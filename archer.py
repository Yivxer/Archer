#!/usr/bin/env python3
import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.llm import stream_chat, call_with_tools
from core.context import build_messages, load_config
from core.session import Session
from core.input import prompt as get_input
from core.compressor import should_compress, compress
from core.file_ref import parse_refs, build_user_content, ref_summary
from memory.store import init_db, save, list_all, search, delete
from memory.extract import extract
from memory.retrieve import for_context, format_for_prompt
from skills.loader import load_skills, get_tools
from skills.installer import install as skill_install, remove as skill_remove

console = Console()

# ── 欢迎界面 ──────────────────────────────────────────────
def _welcome(skill_count: int):
    console.print(Panel(
        f"[bold cyan]Archer[/bold cyan]  ·  枫弋专属代理\n"
        f"[dim]已加载 {skill_count} 个技能  ·  /help 查看命令\n"
        f"Enter 换行  ·  Alt+Enter 发送  ·  Ctrl+C 退出[/dim]",
        border_style="cyan",
        padding=(0, 2),
    ))

# ── /help ─────────────────────────────────────────────────
def _help():
    rows = [
        ("/help",                       "查看命令"),
        ("/save",                       "保存当前会话"),
        ("/clear",                      "清空对话历史"),
        ("/memory list",                "列出所有记忆"),
        ("/memory search <词>",         "搜索记忆"),
        ("/memory add <内容>",          "手动添加记忆"),
        ("/memory delete <ID>",         "删除记忆"),
        ("/skill list",                 "列出已安装技能"),
        ("/skill install <路径或URL>",  "安装技能"),
        ("/skill remove <名字>",        "卸载技能"),
        ("/skill info <名字>",          "技能详情"),
        ("/exit",                       "退出并保存"),
    ]
    for cmd, desc in rows:
        console.print(f"  [cyan]{cmd:<32}[/cyan]{desc}")

# ── /memory 子命令 ─────────────────────────────────────────
def _memory_list():
    mems = list_all(50)
    if not mems:
        console.print("[dim]记忆库为空。[/dim]")
        return
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("ID",  style="dim", width=4)
    t.add_column("重要", width=6)
    t.add_column("内容")
    t.add_column("标签", style="dim")
    t.add_column("日期", style="dim", width=11)
    for m in mems:
        t.add_row(str(m["id"]), "★" * min(m["importance"], 5),
                  m["content"], m.get("tags", ""), m["created_at"][:10])
    console.print(t)

def _memory_search(keyword: str):
    if not keyword:
        console.print("[yellow]用法：/memory search <关键词>[/yellow]")
        return
    mems = search(keyword)
    if not mems:
        console.print(f"[dim]没有找到「{keyword}」相关记忆。[/dim]")
        return
    for m in mems:
        console.print(f"  [dim]{m['id']}[/dim]  [{'★' * min(m['importance'],5)}] {m['content']}")

def _memory_add(content: str):
    if not content:
        console.print("[yellow]用法：/memory add <内容>[/yellow]")
        return
    mid = save(content, source="manual")
    console.print(f"[green]记忆已添加（ID {mid}）。[/green]")

def _memory_delete(arg: str):
    if not arg.isdigit():
        console.print("[yellow]用法：/memory delete <ID>[/yellow]")
        return
    delete(int(arg))
    console.print(f"[dim]记忆 {arg} 已删除。[/dim]")

def _handle_memory(parts: list[str]):
    sub = parts[1] if len(parts) > 1 else ""
    arg = " ".join(parts[2:])
    match sub:
        case "list":   _memory_list()
        case "search": _memory_search(arg)
        case "add":    _memory_add(arg)
        case "delete": _memory_delete(arg)
        case _:
            console.print("[dim]子命令：list · search <词> · add <内容> · delete <ID>[/dim]")

# ── /skill 子命令 ──────────────────────────────────────────
def _skill_list(skills: dict):
    if not skills:
        console.print("[dim]尚未安装任何技能。[/dim]")
        return
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("名称", style="cyan")
    t.add_column("描述")
    t.add_column("版本", style="dim", width=8)
    for name, mod in skills.items():
        meta = mod.SKILL
        t.add_row(name, meta.get("description", ""), meta.get("version", ""))
    console.print(t)

def _skill_info(skills: dict, name: str):
    if not name:
        console.print("[yellow]用法：/skill info <名字>[/yellow]")
        return
    mod = skills.get(name)
    if not mod:
        console.print(f"[yellow]技能不存在：{name}[/yellow]")
        return
    meta = mod.SKILL
    console.print(f"\n  [bold cyan]{meta['name']}[/bold cyan]  v{meta.get('version','?')}")
    console.print(f"  {meta.get('description','')}")
    if meta.get("author"):
        console.print(f"  [dim]作者：{meta['author']}[/dim]")
    schema = mod.schema()["function"]
    params = schema.get("parameters", {}).get("properties", {})
    if params:
        console.print("\n  参数：")
        for k, v in params.items():
            console.print(f"    [cyan]{k}[/cyan]  {v.get('description','')}")

def _handle_skill(parts: list[str], skills: dict) -> dict:
    """返回（可能已更新的）skills 字典。"""
    sub = parts[1] if len(parts) > 1 else ""
    arg = " ".join(parts[2:])

    match sub:
        case "list":
            _skill_list(skills)

        case "install":
            if not arg:
                console.print("[yellow]用法：/skill install <本地路径 或 GitHub URL>[/yellow]")
            else:
                try:
                    name = skill_install(arg)
                    skills = load_skills()   # 重新加载
                    console.print(f"[green]技能「{name}」安装成功。[/green]")
                except Exception as e:
                    console.print(f"[red]安装失败：{e}[/red]")

        case "remove":
            if not arg:
                console.print("[yellow]用法：/skill remove <名字>[/yellow]")
            else:
                try:
                    skill_remove(arg)
                    skills = load_skills()
                    console.print(f"[dim]技能「{arg}」已卸载。[/dim]")
                except Exception as e:
                    console.print(f"[red]卸载失败：{e}[/red]")

        case "info":
            _skill_info(skills, arg)

        case _:
            console.print("[dim]子命令：list · install <路径/URL> · remove <名字> · info <名字>[/dim]")

    return skills

# ── 技能调用循环 ───────────────────────────────────────────
def _run_with_tools(messages: list[dict], skills: dict) -> str:
    """
    function calling 流程：
    1. 非流式调用，携带 tools
    2. 若有 tool_calls，执行技能，把结果追加回 messages
    3. 最终回复用流式输出
    """
    tools = get_tools(skills)
    msg = call_with_tools(messages, tools)

    # 无技能调用 → 直接流式输出
    if not msg.tool_calls:
        messages_plain = messages  # 不带 tools，重新流式
        full = ""
        for chunk in stream_chat(messages_plain):
            console.print(chunk, end="", markup=False)
            full += chunk
        console.print()
        return full

    # 有技能调用 → 执行每个 tool_call
    messages = list(messages)  # 复制，避免污染外部
    messages.append(msg)       # assistant 的 tool_calls 消息

    for tc in msg.tool_calls:
        fn_name = tc.function.name
        try:
            fn_args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            fn_args = {}

        mod = skills.get(fn_name)
        if mod:
            console.print(f"\n[dim]→ 调用技能 [{fn_name}]…[/dim]")
            result = mod.run(fn_args)
        else:
            result = f"技能不存在：{fn_name}"

        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": result,
        })

    # 技能结果注入后，流式输出最终回复
    console.print()
    full = ""
    for chunk in stream_chat(messages):
        console.print(chunk, end="", markup=False)
        full += chunk
    console.print()
    return full

# ── 自动提炼记忆 ──────────────────────────────────────────
def _auto_extract(history: list[dict]):
    if len(history) < 2:
        return
    console.print("\n[dim]正在提炼记忆…[/dim]")
    try:
        mems = extract(history)
        if mems:
            for m in mems:
                save(content=m.get("content", ""), tags=m.get("tags", ""),
                     importance=m.get("importance", 3), source="auto")
            console.print(f"[dim]新增 {len(mems)} 条记忆。[/dim]")
        else:
            console.print("[dim]本次对话无新记忆。[/dim]")
    except Exception as e:
        console.print(f"[dim]记忆提炼失败：{e}[/dim]")

# ── 主循环 ────────────────────────────────────────────────
def run():
    init_db()
    cfg = load_config()
    session = Session()
    skills = load_skills()
    _welcome(len(skills))

    while True:
        # ── 自动压缩（超过阈值时触发）──────────────────────
        if should_compress(session.history):
            console.print("[dim]对话历史过长，正在压缩…[/dim]")
            try:
                session.history = compress(session.history)
                console.print("[dim]压缩完成，上下文已精简。[/dim]")
            except Exception as e:
                console.print(f"[dim]压缩失败，跳过：{e}[/dim]")

        # ── 多行输入 ────────────────────────────────────────
        console.print()
        try:
            user_input = get_input()
        except (KeyboardInterrupt, EOFError):
            _auto_extract(session.history)
            session.save()
            console.print("[dim]已退出。[/dim]")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            parts = user_input.split()
            match parts[0]:
                case "/exit":
                    _auto_extract(session.history)
                    saved = session.save()
                    console.print(f"[dim]会话已保存 → {saved}[/dim]")
                    break
                case "/save":
                    console.print(f"[dim]会话已保存 → {session.save()}[/dim]")
                case "/clear":
                    session.clear()
                    console.print("[dim]历史已清空。[/dim]")
                case "/memory":
                    _handle_memory(parts)
                case "/skill":
                    skills = _handle_skill(parts, skills)
                case "/help":
                    _help()
                case _:
                    console.print(f"[yellow]未知命令：{parts[0]}，输入 /help 查看。[/yellow]")
            continue

        # ── @ 文件引用解析 ──────────────────────────────────
        user_text, refs = parse_refs(user_input)
        if refs:
            summary = ref_summary(refs)
            console.print(f"[dim]附件：{summary}[/dim]")
        user_content = build_user_content(user_text, refs)

        # ── 检索记忆注入 ────────────────────────────────────
        db_mems   = for_context(user_text, limit=cfg["memory"]["max_context_memories"])
        mem_block = format_for_prompt(db_mems)
        messages  = build_messages(session.history, user_content, cfg, db_memories=mem_block)

        # ── 图片时切换 vision 模型 ──────────────────────────
        has_images = any(r["type"] == "image" for r in refs)
        if has_images:
            vision_model = cfg["api"].get("vision_model", cfg["api"]["model"])
            console.print(f"[dim]图片模式 → {vision_model}[/dim]")

        console.print("\n[bold cyan]Archer[/bold cyan]")
        try:
            if skills:
                full_response = _run_with_tools(messages, skills)
            else:
                full_response = ""
                for chunk in stream_chat(messages):
                    console.print(chunk, end="", markup=False)
                    full_response += chunk
                console.print()
        except Exception as e:
            console.print(f"[red]错误：{e}[/red]")
            continue

        # 历史只存纯文本（图片数据不存入，避免历史膨胀）
        history_user = user_text
        if refs:
            names = [r["name"] for r in refs if r["type"] != "error"]
            if names:
                history_user += f"\n[附件：{', '.join(names)}]"
        session.add(history_user, full_response)

if __name__ == "__main__":
    run()
