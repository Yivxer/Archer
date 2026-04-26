#!/usr/bin/env python3
from difflib import SequenceMatcher
import json
import sys
from pathlib import Path
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table

from core.llm import stream_chat, call_with_tools, load_config, get_last_usage, get_session_tokens
from core.context import build_messages
from core.session import Session
from core.input import prompt as get_input
from core.compressor import should_compress, compress
from core.file_ref import parse_refs, build_user_content, ref_summary
from core.tool_runtime import invoke as runtime_invoke
from core.policy import check as policy_check, Decision
from memory.store import (
    init_db, save, list_all, search, delete,
    update as update_memory, archive as archive_memory,
    add_pending, list_pending, count_pending, accept_pending, reject_pending,
)
from memory.extract import extract
from memory.retrieve import for_context, format_for_prompt
from skills.loader import load_skills, get_tools
from skills.installer import install as skill_install, remove as skill_remove

console = Console()

_CMDS = frozenset({
    "/help", "/status", "/mode", "/model", "/reflect", "/sessions",
    "/save", "/clear", "/compact", "/exit", "/memory", "/skill",
})

_RING_TOP = "[#5ee8e0]◜[/#5ee8e0][#1e7be8]◝[/#1e7be8]"
_RING_BOT = "[#e8212a]◟[/#e8212a][#f5612a]◞[/#f5612a]"

_ARCHER_NAME = (
    "[bold]"
    "[#5ee8e0]A[/#5ee8e0]"
    "[#2aabf0]r[/#2aabf0]"
    "[#1e7be8]c[/#1e7be8]"
    "[#f5c842]h[/#f5c842]"
    "[#f5a030]e[/#f5a030]"
    "[#f5612a]r[/#f5612a]"
    "[/bold]"
)

def _token_limit(cfg: dict) -> int:
    return int(cfg.get("context", {}).get("token_limit", 1_000_000))

def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)

def _usage_status(cfg: dict) -> str:
    return f"session {_fmt_tokens(get_session_tokens())}/{_fmt_tokens(_token_limit(cfg))}"

def _welcome():
    console.print()
    console.print(f"  {_RING_TOP}  {_ARCHER_NAME}")
    console.print(f"  {_RING_BOT}  [dim]一个了解你，并与你共同生长的灵魂[/dim]")
    console.print()

def _help():
    rows = [
        ("/help",                       "查看命令"),
        ("/status",                     "查看当前状态（记忆数 / 技能数 / 历史轮数）"),
        ("/mode <mirror|coach|critic|operator>", "切换对话模式"),
        ("/reflect",                    "复盘最近对话，提取记忆/决策/待办"),
        ("/sessions [天数]",            "查看最近 N 天会话统计（默认 7 天）"),
        ("/save",                       "保存当前会话"),
        ("/clear",                      "清空对话历史"),
        ("/compact",                    "手动压缩对话历史"),
        ("/memory list",                "列出所有记忆"),
        ("/memory search <词>",         "搜索记忆"),
        ("/memory add <内容>",          "手动添加记忆"),
        ("/memory pending",             "查看待确认记忆"),
        ("/memory accept [编号|all]",   "确认写入待确认记忆"),
        ("/memory reject [编号|all]",   "丢弃待确认记忆"),
        ("/memory update <ID> <内容>",  "更新已有记忆"),
        ("/memory archive <ID>",        "归档已有记忆"),
        ("/memory delete <ID>",         "删除记忆"),
        ("/memory review",              "体检记忆库，找重复/冲突/过期线索"),
        ("/skill list",                 "列出已安装技能"),
        ("/skill install <路径或URL>",  "安装技能"),
        ("/skill remove <名字>",        "卸载技能"),
        ("/skill info <名字>",          "技能详情"),
        ("/model [<模型名>]",           "查看 / 切换模型"),
        ("/exit",                       "退出并保存"),
    ]
    for cmd, desc in rows:
        console.print(f"  [cyan]{cmd:<40}[/cyan]{desc}")

def _status(session, skills: dict, cfg: dict):
    from memory.store import list_all as mem_list_all
    from core.artifacts import dir_size, fmt_size
    mem_count     = len(mem_list_all(999))
    pending_count = count_pending()
    history_turns = len(session.history) // 2
    model         = cfg["api"]["model"]
    modes         = cfg.get("persona", {}).get("modes", {})
    current_mode  = cfg["persona"].get("current_mode", cfg["persona"].get("default_mode", "coach"))
    mode_name     = modes.get(current_mode, {}).get("name", current_mode)
    art_size      = fmt_size(dir_size())
    console.print(f"\n  [bold cyan]Archer 状态[/bold cyan]")
    console.print(f"  模型        {model}")
    console.print(f"  模式        {mode_name}（{current_mode}）")
    console.print(f"  Token       {_usage_status(cfg)}")
    console.print(f"  技能        {len(skills)} 个：{', '.join(sorted(skills.keys()))}")
    console.print(f"  记忆库      {mem_count} 条" + (f"  [yellow]（{pending_count} 条待确认）[/yellow]" if pending_count else ""))
    console.print(f"  对话历史    {history_turns} 轮（{len(session.history)} 条消息）")
    console.print(f"  Artifacts   {art_size}（位于 .artifacts/）")

def _handle_model(parts: list[str], cfg: dict):
    models  = cfg["api"].get("models", [cfg["api"]["model"]])
    current = cfg["api"]["model"]
    if len(parts) < 2:
        console.print(f"\n  当前模型：[bold #c44e00]{current}[/]")
        for m in models:
            marker = "  [dim]←[/]" if m == current else ""
            console.print(f"  [#c44e00]{m}[/]{marker}")
        console.print(f"\n  用法：/model <模型名>")
        return
    new_model = parts[1]
    cfg["api"]["model"] = new_model
    console.print(f"[bold #c44e00]已切换至 {new_model}[/]")

def _handle_mode(parts: list[str], cfg: dict):
    modes = cfg.get("persona", {}).get("modes", {})
    valid = list(modes.keys())
    if len(parts) < 2 or parts[1] not in valid:
        current = cfg["persona"].get("current_mode", cfg["persona"].get("default_mode", "coach"))
        mode_names = "  ".join(f"[cyan]{k}[/cyan]（{v.get('name',k)}）" for k, v in modes.items())
        console.print(f"  当前模式：[bold #c44e00]{current}[/]")
        console.print(f"  可用模式：{mode_names}")
        return
    mode = parts[1]
    cfg["persona"]["current_mode"] = mode
    mode_name = modes[mode].get("name", mode)
    console.print(f"[dim]已切换至 {mode_name} 模式[/dim]")

_REFLECT_PROMPT = """\
你是复盘专家。分析以下对话，严格以 JSON 输出，不要其他内容：
{
  "summary": "本次对话一句话总结（20字以内）",
  "user_intent": "用户的核心意图或主要问题",
  "decisions": ["做出的决定，每条具体可落地"],
  "open_questions": ["尚未解决的问题或悬而未决的方向"],
  "memory_candidates": [
    {"content": "值得长期记忆的信息", "type": "decision|insight|project|preference|todo", "importance": 3}
  ],
  "next_actions": ["72小时内可执行的具体下一步"]
}
每类最多 3 条，没有内容写空数组 []。只输出 JSON。"""


def _reflect_to_text(data: dict) -> str:
    """将复盘结构化数据转为自然语言，注入 session history 供追问。"""
    parts = []
    if data.get("summary"):
        parts.append(f"复盘总结：{data['summary']}")
    if data.get("user_intent"):
        parts.append(f"核心意图：{data['user_intent']}")
    for key, label in [
        ("decisions",      "决策"),
        ("open_questions", "未解问题"),
        ("next_actions",   "下一步行动"),
    ]:
        items = data.get(key, [])
        if items:
            parts.append(f"{label}：" + "；".join(items))
    n = len(data.get("memory_candidates", []))
    if n:
        parts.append(f"已提炼 {n} 条记忆候选（待确认后写入记忆库）")
    return "\n".join(parts) or "复盘完成，无关键信息。"


def _reflect(session):
    if len(session.history) < 2:
        console.print("[dim]对话太短，无需复盘。[/dim]")
        return

    messages = [{"role": "system", "content": _REFLECT_PROMPT}, *session.history[-10:]]

    raw = ""
    spinner = Spinner("arc", text="  复盘中…", style="#4dd9d4")
    with Live(spinner, refresh_per_second=20, transient=True, console=console):
        for chunk in stream_chat(messages):
            raw += chunk

    try:
        s, e = raw.find("{"), raw.rfind("}") + 1
        data = json.loads(raw[s:e]) if s >= 0 and e > s else {}
    except Exception:
        data = {}

    if not data:
        console.print("[dim]复盘解析失败，原始输出：[/dim]")
        console.print(raw, markup=False)
        return

    # ── 展示 ──────────────────────────────────────────────────────
    console.print("\n[bold cyan]复盘[/bold cyan]")
    if data.get("summary"):
        console.print(f"\n  [bold]{data['summary']}[/bold]")
    if data.get("user_intent"):
        console.print(f"  [dim]意图：{data['user_intent']}[/dim]")

    def _section(title: str, items: list):
        if items:
            console.print(f"\n{title}")
            for item in items:
                console.print(f"  · {item}")

    _section("决策",     data.get("decisions", []))
    _section("未解问题", data.get("open_questions", []))
    _section("下一步",   data.get("next_actions", []))

    # ── 记忆候选 → pending ─────────────────────────────────────────
    candidates = data.get("memory_candidates", [])
    if candidates:
        _stage_memories(candidates, source="reflect")

    # ── 保存 reflection 摘要到记忆库（不自动注入上下文）────────────
    summary = data.get("summary", "").strip()
    if summary:
        save(summary, type="reflection", importance=3, source="reflect")

    # ── 保存完整 JSON 到 artifact ──────────────────────────────────
    from core.artifacts import save_reflection as _save_reflect_artifact
    artifact_path = _save_reflect_artifact(
        json.dumps(data, ensure_ascii=False, indent=2)
    )
    console.print(f"\n[dim]完整复盘 → {artifact_path}[/dim]")

    # ── 进入 session history，允许追问 ────────────────────────────
    session.add("[/reflect]", _reflect_to_text(data))
    console.print("[dim]复盘已加入对话历史，可直接追问。[/dim]")

def _memory_list():
    mems = list_all(50)
    if not mems:
        console.print("[dim]记忆库为空。[/dim]")
        return
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("ID",   style="dim", width=4)
    t.add_column("重要", width=6)
    t.add_column("类型", style="cyan", width=12)
    t.add_column("内容")
    t.add_column("标签", style="dim")
    t.add_column("日期", style="dim", width=11)
    for m in mems:
        t.add_row(str(m["id"]), "★" * min(m["importance"], 5),
                  m.get("type", "insight"), m["content"],
                  m.get("tags", ""), m.get("created_at", "")[:10])
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

def _stage_memories(mems: list[dict], source: str = "auto", silent: bool = False):
    if not mems:
        return
    count = 0
    for m in mems:
        add_pending(
            content=m.get("content", ""),
            type=m.get("type", "insight"),
            importance=m.get("importance", 3),
            tags=m.get("tags", ""),
            source=source,
            confidence=m.get("confidence", 0.7),
        )
        count += 1
    if not silent:
        console.print(f"[dim]提议写入 {count} 条记忆，使用 /memory pending 查看。[/dim]")

def _memory_pending():
    pends = list_pending()
    if not pends:
        console.print("[dim]没有待确认记忆。[/dim]")
        return
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("ID", style="dim", width=4)
    t.add_column("重要", width=6)
    t.add_column("类型", style="cyan", width=12)
    t.add_column("内容")
    for p in pends:
        t.add_row(
            str(p["id"]),
            "★" * min(int(p.get("importance", 3)), 5),
            p.get("type", "insight"),
            p.get("content", ""),
        )
    console.print(t)
    console.print("[dim]确认：/memory accept <ID|all>  丢弃：/memory reject <ID|all>[/dim]")

def _memory_accept(arg: str):
    arg = arg.strip() or "all"
    if arg != "all" and not arg.isdigit():
        console.print("[yellow]用法：/memory accept <ID|all>[/yellow]")
        return
    ids = accept_pending(arg)
    if not ids:
        console.print("[yellow]没有匹配的待确认记忆。[/yellow]")
        return
    console.print(f"[green]已写入 {len(ids)} 条记忆：{', '.join(str(i) for i in ids)}[/green]")

def _memory_reject(arg: str):
    arg = arg.strip() or "all"
    if arg != "all" and not arg.isdigit():
        console.print("[yellow]用法：/memory reject <ID|all>[/yellow]")
        return
    n = reject_pending(arg)
    if n == 0:
        console.print("[yellow]没有匹配的待确认记忆。[/yellow]")
        return
    console.print(f"[dim]已丢弃 {n} 条待确认记忆。[/dim]")

def _memory_update(arg: str):
    mid, _, content = arg.partition(" ")
    if not mid.isdigit() or not content.strip():
        console.print("[yellow]用法：/memory update <ID> <新内容>[/yellow]")
        return
    if update_memory(int(mid), content):
        console.print(f"[green]记忆 {mid} 已更新。[/green]")
    else:
        console.print(f"[yellow]未找到可更新的记忆：{mid}[/yellow]")

def _memory_archive(arg: str):
    if not arg.isdigit():
        console.print("[yellow]用法：/memory archive <ID>[/yellow]")
        return
    if archive_memory(int(arg)):
        console.print(f"[dim]记忆 {arg} 已归档。[/dim]")
    else:
        console.print(f"[yellow]未找到可归档的记忆：{arg}[/yellow]")

def _memory_delete(arg: str):
    if not arg.isdigit():
        console.print("[yellow]用法：/memory delete <ID>[/yellow]")
        return
    delete(int(arg))
    console.print(f"[dim]记忆 {arg} 已删除。[/dim]")

def _memory_review():
    mems = list_all(999)
    if not mems:
        console.print("[dim]记忆库为空。[/dim]")
        return

    findings: list[tuple[str, str, str]] = []

    def add(kind: str, ids: str, note: str):
        findings.append((kind, ids, note))

    for i, a in enumerate(mems):
        for b in mems[i + 1:]:
            ratio = SequenceMatcher(None, a["content"], b["content"]).ratio()
            if ratio >= 0.62:
                add("疑似重复", f"{a['id']}, {b['id']}", a["content"][:52])

    temporary_words = ("暂时", "本次", "刚才", "当前", "页面", "输入框", "样式", "Claude Code")
    for m in mems:
        content = m["content"]
        if m.get("importance", 3) >= 4 and m.get("type") in {"insight", "context"}:
            add("高权重洞察", str(m["id"]), "可能不适合长期自动注入：" + content[:44])
        if any(w in content for w in temporary_words) and m.get("importance", 3) >= 4:
            add("疑似过期", str(m["id"]), "像临时任务或阶段性上下文：" + content[:44])

    ability_terms = [m for m in mems if any(w in m["content"] for w in ("本地文件", "主动读取", "无法", "具备", "能力边界"))]
    for i, a in enumerate(ability_terms):
        for b in ability_terms[i + 1:]:
            text = a["content"] + b["content"]
            if ("无法" in text or "无主动" in text) and ("具备" in text or "主动读取" in text):
                add("疑似冲突", f"{a['id']}, {b['id']}", "能力边界相关记忆可能互相打架")

    if not findings:
        console.print("[green]没有发现明显的重复、冲突或过期线索。[/green]")
        return

    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("类型", style="cyan", width=12)
    t.add_column("ID", style="dim", width=10)
    t.add_column("建议")
    for kind, ids, note in findings[:40]:
        t.add_row(kind, ids, note)
    console.print(t)
    console.print("[dim]只做提示，不会自动删除。确认后可用 /memory delete <ID> 清理。[/dim]")

def _handle_memory(parts: list[str]):
    sub = parts[1] if len(parts) > 1 else ""
    arg = " ".join(parts[2:])
    match sub:
        case "list":   _memory_list()
        case "search": _memory_search(arg)
        case "add":    _memory_add(arg)
        case "pending": _memory_pending()
        case "accept": _memory_accept(arg)
        case "reject": _memory_reject(arg)
        case "update": _memory_update(arg)
        case "archive": _memory_archive(arg)
        case "delete": _memory_delete(arg)
        case "review": _memory_review()
        case _:
            console.print("[dim]子命令：list · search <词> · add <内容> · pending · accept · reject · update · archive · delete · review[/dim]")

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
                    skills = load_skills()
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

def _stream(messages: list[dict], model: str = "") -> str:
    gen = stream_chat(messages, model=model)
    console.print(f"\n{_ARCHER_NAME}：")
    full = ""
    for chunk in gen:
        sys.stdout.write(chunk)
        sys.stdout.flush()
        full += chunk
    sys.stdout.write("\n")
    sys.stdout.flush()
    return full

def _run_with_tools(messages: list[dict], skills: dict, model: str = "") -> str:
    tools = get_tools(skills)
    messages = list(messages)
    MAX_ROUNDS = 10

    for round_n in range(MAX_ROUNDS):
        msg = call_with_tools(messages, tools, model=model)

        if not msg.tool_calls:
            break

        messages.append(msg)

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            console.print(f"[dim]→ {fn_name}…[/dim]")

            # ── Policy check ───────────────────────────────────────
            pr = policy_check(fn_name, fn_args, skills)
            if pr.decision == Decision.DENY:
                console.print(f"[red]  ✗ [策略拒绝] {pr.reason}[/red]")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"[策略拒绝] {pr.reason}",
                })
                continue

            if pr.decision == Decision.CONFIRM:
                console.print(f"[yellow]  ⚠ 高风险操作 — {pr.reason}[/yellow]")
                try:
                    answer = input("  执行？[y/N] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    answer = "n"
                if answer != "y":
                    console.print("[dim]  已取消。[/dim]")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "[用户取消] 操作已拒绝",
                    })
                    continue
            # ───────────────────────────────────────────────────────

            tr = runtime_invoke(fn_name, fn_args, skills)
            if not tr.ok:
                console.print(f"[yellow]  ✗ {tr.summary}[/yellow]")
            elif tr.truncated:
                console.print(f"[dim]  ↳ {tr.summary}[/dim]")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tr.to_message_content(),
            })
    else:
        console.print("[dim]已达最大工具调用轮次（10轮）[/dim]")

    return _stream(messages, model=model)

def _auto_extract(history: list[dict], silent: bool = False):
    if len(history) < 2:
        return
    if not silent:
        console.print("\n[dim]正在提炼记忆…[/dim]")
    try:
        mems, obsidian_hints = extract(history)
        if mems:
            _stage_memories(mems, source="auto", silent=silent)
        elif not silent:
            console.print("[dim]本次对话无新记忆。[/dim]")

        if obsidian_hints and not silent:
            for hint in obsidian_hints:
                console.print(
                    f"\n[cyan]建议写入 {hint['file']}：[/cyan]\n"
                    f"  [dim]{hint['content'][:80]}[/dim]"
                )
    except Exception:
        pass

def run():
    init_db()
    cfg = load_config()
    session = Session()
    skills = load_skills()
    _welcome()
    turn_count = 0

    while True:
        last_usage = get_last_usage()
        if should_compress(
            session.history,
            prompt_tokens=last_usage["prompt_tokens"],
            token_limit=_token_limit(cfg),
        ):
            console.print("[dim]上下文接近预算，正在压缩…[/dim]")
            try:
                session.history = compress(session.history)
                console.print("[dim]压缩完成，上下文已精简。[/dim]")
            except Exception as e:
                console.print(f"[dim]压缩失败，跳过：{e}[/dim]")

        current_model = cfg["api"]["model"]
        current_mode = cfg["persona"].get("current_mode", cfg["persona"].get("default_mode", "coach"))
        modes = cfg.get("persona", {}).get("modes", {})
        mode_name = modes.get(current_mode, {}).get("name", current_mode)
        console.print()
        try:
            user_input = get_input(
                model=current_model,
                mode=mode_name,
                usage=_usage_status(cfg),
            )
        except (KeyboardInterrupt, EOFError):
            session.save()
            console.print("[dim]已退出。[/dim]")
            break

        if not user_input:
            continue

        parts = user_input.split()
        if user_input.startswith("/") and parts[0] in _CMDS:
            match parts[0]:
                case "/exit":
                    saved = session.save()
                    console.print(f"[dim]会话已保存 → {saved}[/dim]")
                    break
                case "/save":
                    console.print(f"[dim]会话已保存 → {session.save()}[/dim]")
                case "/clear":
                    session.clear()
                    console.print("[dim]历史已清空。[/dim]")
                case "/compact":
                    if len(session.history) < 2:
                        console.print("[dim]对话历史不足，无需压缩。[/dim]")
                    else:
                        console.print("[dim]正在压缩…[/dim]")
                        try:
                            session.history = compress(session.history)
                            console.print(f"[dim]压缩完成，当前 {len(session.history)} 条消息。[/dim]")
                        except Exception as e:
                            console.print(f"[red]压缩失败：{e}[/red]")
                case "/status":
                    _status(session, skills, cfg)
                case "/memory":
                    _handle_memory(parts)
                case "/skill":
                    skills = _handle_skill(parts, skills)
                case "/model":
                    _handle_model(parts, cfg)
                case "/mode":
                    _handle_mode(parts, cfg)
                case "/reflect":
                    _reflect(session)
                case "/sessions":
                    from memory.session_insights import format_report
                    days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 7
                    console.print(format_report(days))
                case "/help":
                    _help()
                case _:
                    console.print(f"[yellow]未知命令：{parts[0]}[/yellow]")
            continue

        user_text, refs = parse_refs(user_input)
        if refs:
            summary = ref_summary(refs)
            console.print(f"[dim]附件：{summary}[/dim]")
        user_content = build_user_content(user_text, refs)

        core_mems, related_mems = for_context(user_text, limit=cfg["memory"]["max_context_memories"])
        mem_block = format_for_prompt(core_mems, related_mems)
        messages  = build_messages(session.history, user_content, cfg, db_memories=mem_block)

        has_images = any(r["type"] == "image" for r in refs)
        active_model = ""
        if has_images:
            vision_model = cfg["api"].get("vision_model", "")
            text_model   = cfg["api"]["model"]
            if not vision_model or vision_model == text_model:
                console.print("[yellow]图片需要支持视觉的模型，请在 archer.toml 中配置 vision_model。[/yellow]")
                has_images = False
                user_content = user_text
                messages = build_messages(session.history, user_content, cfg, db_memories=mem_block)
            else:
                active_model = vision_model
                console.print(f"[dim]图片模式 → {active_model}[/dim]")

        try:
            if skills:
                full_response = _run_with_tools(messages, skills, model=active_model)
            else:
                full_response = _stream(messages, model=active_model)
        except Exception as e:
            err = str(e)
            if "image_url" in err or "image" in err.lower():
                console.print("[yellow]图片模式 API 报错，请检查 vision_model 配置。[/yellow]")
            else:
                console.print(f"[red]错误：{e}[/red]")
            continue

        history_user = user_text
        if refs:
            names = [r["name"] for r in refs if r["type"] != "error"]
            if names:
                history_user += f"\n[附件：{', '.join(names)}]"
        session.add(history_user, full_response)
        turn_count += 1

        if turn_count % 3 == 0 and len(session.history) >= 6:
            _auto_extract(session.history[-6:], silent=False)

if __name__ == "__main__":
    run()
