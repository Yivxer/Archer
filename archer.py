#!/usr/bin/env python3
from difflib import SequenceMatcher
import json
import re
import sys
import threading
from pathlib import Path

_TOML_PATH = Path(__file__).parent / "archer.toml"
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table

from core.llm import stream_chat, load_config, get_last_usage, get_session_tokens, pop_config_reloaded
from core.context import build_messages, is_heavy_query, classify_query_intent
from core.session import Session
from core.input import prompt as get_input
from core.compressor import should_compress, compress
from core.file_ref import parse_refs, build_user_content, ref_summary
from core.tool_loop import run_with_tools
from memory.store import (
    init_db, save, list_all, search, delete,
    update as update_memory, archive as archive_memory,
    add_pending, list_pending, count_pending, update_pending, accept_pending, reject_pending,
    create_project, list_projects, get_project, get_project_by_name,
    archive_project, log_project_event, get_project_events,
    count_soul_proposals, generate_session_id,
)
from memory.soul import (
    propose_from_memories, propose_from_obsidian_hints, get_pending as get_soul_pending,
    accept as soul_accept, reject as soul_reject,
)
from memory.extract import extract
from memory.retrieve import for_context, format_for_prompt
from skills.loader import load_skills
from skills.installer import install as skill_install, remove as skill_remove
from core.skill_router import select_skills
from core.scheduler import (
    add_task, remove_task as remove_cron_task, set_enabled as cron_set_enabled,
    list_tasks, run_due_tasks, run_task_by_id, parse_interval, fmt_interval,
)
from core.mcp import load_from_config as mcp_load

console = Console()

_CMDS = frozenset({
    "/help", "/status", "/mode", "/model", "/reflect", "/sessions",
    "/save", "/clear", "/compact", "/exit", "/memory", "/skill",
    "/themes", "/project", "/soul", "/listen", "/doctor", "/cron",
    "/covenant", "/presence", "/critique",
})

# ── 后台提炼状态 ────────────────────────────────────────────────────────────────
_extract_thread: threading.Thread | None = None

# ── 当前会话活跃项目 ─────────────────────────────────────────────────────────────
_active_project_id: int | None = None

# ── 当前会话 ID（v1.2 Phase 3）────────────────────────────────────────────────────
_current_session_id: str = ""

# ── MCP 最近使用追踪（v1.2 Phase 4）──────────────────────────────────────────────
_mcp_last_used_turn: int = -999   # 记录最近一次调用 MCP 工具的 turn 编号
_turn_counter: int = 0

# MCP capability 关键词（命中 → 注入 MCP schema）
_MCP_CAPABILITY_KW = frozenset([
    "url", "网页", "抓取", "fetch", "读取链接", "远程资源",
    "github", "filesystem", "browser", "文件系统", "仓库", "issue", "pull request",
    "搜索网页", "browse", "screenshot", "截图",
])

# ── 静默录入模式 ─────────────────────────────────────────────────────────────────
_listen_mode: bool = False
_LISTEN_LOG_DIR = Path(__file__).parent / ".listen_logs"

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
        ("/memory reindex",             "重建向量索引（需 sqlite-vec + sentence-transformers）"),
        ("/skill list",                 "列出已安装技能"),
        ("/skill install <路径或URL>",  "安装技能"),
        ("/skill remove <名字>",        "卸载技能"),
        ("/skill info <名字>",          "技能详情"),
        ("/model [<模型名>]",           "查看 / 切换模型"),
        ("/doctor [--fix]",             "自检系统状态，--fix 自动修复可修复问题"),
        ("/cron list",                  "查看定时任务"),
        ("/cron add <技能> <daily|weekly|Nh>", "添加定时任务"),
        ("/cron remove <ID>",           "删除定时任务"),
        ("/cron enable/disable <ID>",   "启用 / 禁用定时任务"),
        ("/cron run <ID>",              "立即执行定时任务"),
        ("/covenant view",              "查看根契约"),
        ("/covenant history",           "查看契约历史版本"),
        ("/covenant propose",           "提出契约修改申请（需用户主动触发）"),
        ("/presence view",              "查看当前在场方式"),
        ("/presence edit",              "编辑在场方式（用编辑器打开）"),
        ("/presence suggest",           "生成在场方式调整建议（仅建议，不写入）"),
        ("/presence history",           "查看在场方式历史"),
        ("/critique scan",              "扫描生成自我批评诊断"),
        ("/critique list",              "列出当前开放的批评条目"),
        ("/critique view <ID>",         "查看批评详情（证据 / 假设 / 建议方向）"),
        ("/critique dismiss <ID>",      "驳回批评（诊断不成立）"),
        ("/critique new",               "手动创建批评条目"),
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
    soul_count = count_soul_proposals()
    console.print(f"  记忆库      {mem_count} 条" + (f"  [yellow]（{pending_count} 条待确认）[/yellow]" if pending_count else ""))
    if soul_count:
        console.print(f"  SOUL 提议   [yellow]{soul_count} 条待审阅[/yellow]（/soul 查看）")
    console.print(f"  对话历史    {history_turns} 轮（{len(session.history)} 条消息）")
    console.print(f"  Artifacts   {art_size}（位于 .artifacts/）")
    if _active_project_id:
        proj = get_project(_active_project_id)
        pname = proj["name"] if proj else "?"
        console.print(f"  活跃项目    [cyan]{pname}[/cyan]（ID {_active_project_id}）")

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

def _persist_mode(mode: str) -> None:
    """将 current_mode 写入 archer.toml，插入或替换 [persona] 段中的对应行。"""
    text = _TOML_PATH.read_text(encoding="utf-8")
    new_line = f'current_mode = "{mode}"'
    if re.search(r'^current_mode\s*=', text, re.MULTILINE):
        text = re.sub(r'^current_mode\s*=.*$', new_line, text, flags=re.MULTILINE)
    else:
        text = re.sub(r'^(default_mode\s*=.*)$', rf'\1\n{new_line}', text, flags=re.MULTILINE)
    _TOML_PATH.write_text(text, encoding="utf-8")


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
    _persist_mode(mode)

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

    # ── 记忆候选 → pending；SOUL 相关 → soul proposal ────────────────
    candidates = data.get("memory_candidates", [])
    if candidates:
        _stage_memories(candidates, source="reflect")
        soul_ids = propose_from_memories(candidates, source="reflect")
        if soul_ids:
            console.print(f"[dim]发现 {len(soul_ids)} 条 SOUL 演化提议，使用 /soul 查看。[/dim]")

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

    # ── 若有活跃项目，把 summary 写入项目日志 ─────────────────────────
    if _active_project_id and summary:
        log_project_event(_active_project_id, "reflect", summary)
        proj = get_project(_active_project_id)
        if proj:
            console.print(f"[dim]复盘摘要已记录到项目「{proj['name']}」。[/dim]")

    # ── 后台提炼对话记忆（补充 reflect 结构化输出的遗漏）─────────────
    _bg_extract(session.history[-8:])

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
    if len(keyword.strip()) < 3:
        console.print("[dim]搜索词过短，使用模糊匹配（FTS5 全文索引需 ≥3 个字符）。[/dim]")
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

def _memory_pending(arg: str = ""):
    if arg.strip() in ("review", "interactive"):
        _memory_pending_review()
        return
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
    console.print("[dim]确认：/memory accept <ID|all>  丢弃：/memory reject <ID|all>  交互审阅：/memory pending review[/dim]")


def _memory_pending_review():
    pends = list_pending()
    if not pends:
        console.print("[dim]没有待确认记忆。[/dim]")
        return

    accepted = rejected = edited = skipped = 0
    console.print("[dim]交互审阅：a 接受 · r 丢弃 · e 编辑后接受 · s 跳过 · q 退出[/dim]")
    for p in pends:
        pid = int(p["id"])
        console.print()
        console.print(f"[cyan]#{pid}[/cyan] [{p.get('type', 'insight')}] 重要度 {p.get('importance', 3)}")
        console.print(p.get("content", ""), markup=False)
        try:
            action = input("  a/r/e/s/q → ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            action = "q"

        if action == "q":
            break
        if action == "s" or not action:
            skipped += 1
            continue
        if action == "r":
            rejected += reject_pending(pid)
            console.print("[dim]  已丢弃。[/dim]")
            continue
        if action == "e":
            try:
                new_content = input("  新内容 → ").strip()
            except (EOFError, KeyboardInterrupt):
                new_content = ""
            if not new_content:
                console.print("[yellow]  内容为空，已跳过。[/yellow]")
                skipped += 1
                continue
            if update_pending(pid, new_content):
                edited += 1
                mids = accept_pending(pid)
                accepted += len(mids)
                console.print(f"[green]  已编辑并写入记忆 {', '.join(str(i) for i in mids)}。[/green]")
            else:
                console.print("[yellow]  这条待确认记忆已不存在。[/yellow]")
            continue
        if action == "a":
            mids = accept_pending(pid)
            if mids:
                accepted += len(mids)
                console.print(f"[green]  已写入记忆 {', '.join(str(i) for i in mids)}。[/green]")
            else:
                console.print("[yellow]  这条待确认记忆已不存在。[/yellow]")
            continue

        console.print("[yellow]  未识别操作，已跳过。[/yellow]")
        skipped += 1

    console.print(f"[dim]审阅结束：接受 {accepted} · 丢弃 {rejected} · 编辑 {edited} · 跳过 {skipped}[/dim]")

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

def _listen_write(text: str):
    """把静默录入内容写入当日日志文件，同时写入活跃项目（若有）。"""
    from datetime import datetime as _dt
    _LISTEN_LOG_DIR.mkdir(exist_ok=True)
    today = _dt.now().strftime("%Y-%m-%d")
    log_file = _LISTEN_LOG_DIR / f"{today}.md"
    timestamp = _dt.now().strftime("%H:%M")
    with open(log_file, "a", encoding="utf-8") as f:
        if log_file.stat().st_size == 0:
            f.write(f"# 静默录入 {today}\n\n")
        f.write(f"- {timestamp}  {text}\n")
    if _active_project_id:
        try:
            log_project_event(_active_project_id, "listen", text)
        except Exception:
            pass


def _handle_listen(parts: list[str]):
    global _listen_mode
    sub = parts[1] if len(parts) > 1 else ""
    if sub in ("stop", "off", "exit") or _listen_mode:
        _listen_mode = False
        console.print("[dim]已退出静默录入模式。[/dim]")
    else:
        _listen_mode = True
        console.print(
            "[cyan]进入静默录入模式。[/cyan]\n"
            "[dim]输入任何内容将记录到日志，不会发送给 AI。\n"
            "再次输入 /listen 退出。[/dim]"
        )


def _handle_soul(parts: list[str], cfg: dict):
    soul_path = cfg.get("paths", {}).get("soul_path", "")
    sub = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    match sub:
        case "" | "list":
            proposals = get_soul_pending()
            if not proposals:
                console.print("[dim]没有待审阅的 SOUL 演化提议。[/dim]")
                return
            console.print(f"\n[bold cyan]SOUL 演化提议[/bold cyan]  [dim]（{len(proposals)} 条待审阅）[/dim]\n")
            for p in proposals:
                console.print(f"  [dim]{p['id']}[/dim]  [yellow]{p['created_at'][:16]}[/yellow]  [{p['source']}]")
                console.print(f"    {p['content']}\n")
            console.print("[dim]/soul accept <ID|all> 写入SOUL.md · /soul reject <ID|all> 丢弃[/dim]")

        case "accept":
            if not arg:
                console.print("[yellow]用法：/soul accept <ID|all>[/yellow]")
                return
            if not soul_path:
                console.print("[red]未配置 soul_path，请在 archer.toml 的 [paths] 中设置。[/red]")
                return
            pid = arg if arg == "all" else arg
            if pid != "all" and not pid.isdigit():
                console.print("[yellow]ID 应为数字或 all[/yellow]")
                return
            ids, written = soul_accept(pid, soul_path)
            if not ids:
                console.print("[yellow]没有匹配的待审阅提议。[/yellow]")
                return
            console.print(f"[green]已追加 {len(ids)} 条内容到 SOUL.md：[/green]")
            for w in written:
                console.print(f"  · {w[:72]}")

        case "reject":
            if not arg:
                console.print("[yellow]用法：/soul reject <ID|all>[/yellow]")
                return
            pid = arg if arg == "all" else arg
            if pid != "all" and not pid.isdigit():
                console.print("[yellow]ID 应为数字或 all[/yellow]")
                return
            ids = soul_reject(pid)
            console.print(f"[dim]已丢弃 {len(ids)} 条 SOUL 演化提议。[/dim]")

        case "view":
            if not soul_path:
                console.print("[red]未配置 soul_path[/red]")
                return
            p = Path(soul_path).expanduser()
            if not p.exists():
                console.print(f"[yellow]SOUL.md 不存在：{soul_path}[/yellow]")
                return
            text = p.read_text(encoding="utf-8")
            # 只显示末尾演化记录部分，避免刷屏
            if "## 演化记录" in text:
                idx = text.rfind("## 演化记录")
                snippet = text[max(0, idx - 50):]
                console.print(f"[dim]… （仅显示最近演化记录）[/dim]\n")
                console.print(snippet[:1200], markup=False)
            else:
                console.print(f"[dim]SOUL.md 中暂无演化记录。文件路径：{soul_path}[/dim]")

        case _:
            console.print("[dim]子命令：list · accept <ID|all> · reject <ID|all> · view[/dim]")


def _handle_covenant(parts: list[str], cfg: dict):
    """根契约管理：view / history / propose。"""
    covenant_path = cfg.get("persona", {}).get("covenant_path", "")
    history_dir   = cfg.get("persona", {}).get("history", {}).get("covenant_dir", "")
    sub = parts[1] if len(parts) > 1 else "view"

    match sub:
        case "view":
            if not covenant_path:
                console.print("[yellow]未配置 persona.covenant_path[/yellow]")
                return
            p = Path(covenant_path).expanduser()
            if not p.exists():
                console.print(f"[yellow]COVENANT.md 不存在：{p}[/yellow]")
                return
            console.print(p.read_text(encoding="utf-8"), markup=False)

        case "history":
            if not history_dir:
                console.print("[dim]未配置 persona.history.covenant_dir，暂无历史记录。[/dim]")
                return
            hdir = Path(history_dir).expanduser()
            if not hdir.exists() or not list(hdir.glob("*.md")):
                console.print("[dim]尚无历史版本。[/dim]")
                return
            files = sorted(hdir.glob("*.md"), reverse=True)
            for f in files[:5]:
                console.print(f"  [dim]{f.name}[/dim]")

        case "propose":
            console.print(
                "[yellow]根契约修改需要你主动提出具体变更内容。[/yellow]\n"
                "[dim]请告诉我：你想修改哪一条，改成什么，以及原因。[/dim]\n"
                "[dim]修改会存入待审提议，需要强确认后才会备份并写入。[/dim]"
            )

        case _:
            console.print("[dim]子命令：view · history · propose[/dim]")


def _handle_presence(parts: list[str], cfg: dict):
    """在场方式管理：view / edit / suggest / history。"""
    presence_path = cfg.get("persona", {}).get("presence_path", "")
    history_dir   = cfg.get("persona", {}).get("history", {}).get("presence_dir", "")
    sub = parts[1] if len(parts) > 1 else "view"

    match sub:
        case "view":
            if not presence_path:
                console.print("[yellow]未配置 persona.presence_path[/yellow]")
                return
            p = Path(presence_path).expanduser()
            if not p.exists():
                console.print(f"[yellow]PRESENCE.md 不存在：{p}[/yellow]")
                return
            console.print(p.read_text(encoding="utf-8"), markup=False)

        case "edit":
            if not presence_path:
                console.print("[yellow]未配置 persona.presence_path[/yellow]")
                return
            import subprocess
            p = Path(presence_path).expanduser()
            editor = __import__("os").environ.get("EDITOR", "nano")
            try:
                # 备份当前版本
                if history_dir and p.exists():
                    hdir = Path(history_dir).expanduser()
                    hdir.mkdir(parents=True, exist_ok=True)
                    from datetime import datetime
                    backup = hdir / f"PRESENCE_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                    backup.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
                subprocess.run([editor, str(p)])
                console.print(f"[green]PRESENCE.md 已更新。[/green]")
            except Exception as e:
                console.print(f"[red]打开编辑器失败：{e}[/red]")

        case "suggest":
            console.print(
                "[dim]在场方式建议模式：我会根据最近对话分析，生成调整建议。[/dim]\n"
                "[dim]建议不会自动写入，需要你通过 /presence edit 手动确认更新。[/dim]\n\n"
                "请告诉我：最近哪些交互让你觉得我的回应节奏或方式不对？"
            )

        case "history":
            if not history_dir:
                console.print("[dim]未配置 persona.history.presence_dir，暂无历史记录。[/dim]")
                return
            hdir = Path(history_dir).expanduser()
            if not hdir.exists() or not list(hdir.glob("*.md")):
                console.print("[dim]尚无历史版本。[/dim]")
                return
            files = sorted(hdir.glob("*.md"), reverse=True)
            for f in files[:5]:
                console.print(f"  [dim]{f.name}[/dim]")

        case _:
            console.print("[dim]子命令：view · edit · suggest · history[/dim]")


def _handle_critique(parts: list[str], cfg: dict):
    """自我批评管理：scan / list / view / dismiss / new。"""
    from memory.critique import (
        scan_critiques, list_critiques, get_critique,
        dismiss_critique, create_critique,
    )
    sub = parts[1] if len(parts) > 1 else "list"
    arg = parts[2] if len(parts) > 2 else ""

    match sub:
        case "list":
            items = list_critiques(status="open")
            if not items:
                console.print("[dim]当前没有开放的自我批评条目。使用 /critique scan 生成。[/dim]")
                return
            console.print(f"\n[bold cyan]自我批评[/bold cyan]  [dim]（{len(items)} 条开放）[/dim]\n")
            for c in items:
                sev = "⚠" if c.get("severity", 3) >= 4 else "·"
                console.print(
                    f"  [dim]{c['id']}[/dim]  {sev}  [yellow]{c['title']}[/yellow]"
                    f"  [dim]{(c.get('created_at') or '')[:10]}  [{c.get('source','')}][/dim]"
                )
            console.print("\n[dim]/critique view <ID> · /critique dismiss <ID>[/dim]")

        case "view":
            if not arg.isdigit():
                console.print("[yellow]用法：/critique view <ID>[/yellow]")
                return
            c = get_critique(int(arg))
            if not c:
                console.print(f"[yellow]找不到 ID={arg} 的批评条目。[/yellow]")
                return
            console.print(f"\n[bold]{c['title']}[/bold]  [dim]#{c['id']}  {(c.get('created_at') or '')[:16]}[/dim]")
            console.print(f"来源：{c.get('source','')}  严重度：{c.get('severity',3)}/5  置信度：{c.get('confidence',0.7):.0%}")
            console.print(f"\n观察：\n{c.get('observation','')}")
            if c.get("hypothesis"):
                console.print(f"\n假设：\n{c['hypothesis']}")
            if c.get("suggested_direction"):
                console.print(f"\n建议方向：\n{c['suggested_direction']}")
            evidence = c.get("evidence_json") or "[]"
            try:
                import json
                evs = json.loads(evidence)
                if evs:
                    console.print(f"\n证据（{len(evs)} 条）：")
                    for ev in evs[:3]:
                        console.print(f"  · {ev}")
            except Exception:
                pass

        case "dismiss":
            if not arg.isdigit():
                console.print("[yellow]用法：/critique dismiss <ID>[/yellow]")
                return
            reason = " ".join(parts[3:]) if len(parts) > 3 else ""
            dismiss_critique(int(arg), reason)
            console.print(f"[dim]已驳回 ID={arg} 的批评条目。[/dim]")

        case "scan":
            items = scan_critiques(cfg)
            if not items:
                console.print("[dim]扫描完成，未发现需要记录的批评条目。[/dim]")
                return
            console.print(f"[green]扫描完成，生成 {len(items)} 条自我批评条目。使用 /critique list 查看。[/green]")

        case "new":
            console.print("[dim]手动创建批评条目。请描述你观察到的问题（至少 30 字）：[/dim]")
            try:
                obs = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                return
            if len(obs) < 30:
                console.print("[yellow]描述太短，至少需要 30 字。[/yellow]")
                return
            title = obs[:20] + "…" if len(obs) > 20 else obs
            cid = create_critique(
                title=title, observation=obs, source="manual",
                evidence=[], session_id=None,
            )
            console.print(f"[green]已创建批评条目 #{cid}。[/green]")

        case _:
            console.print("[dim]子命令：scan · list · view <ID> · dismiss <ID> · new[/dim]")


def _should_inject_mcp(user_text: str, mcp_skills: dict, cfg: dict) -> bool:
    """
    MCP schema 三条件注入策略（v1.2 Phase 4）：
    1. 最近 N 轮使用过 MCP 工具
    2. 用户输入包含 MCP server 名称
    3. 用户输入包含 capability 关键词
    """
    if not mcp_skills:
        return False
    recent_window = cfg.get("mcp", {}).get("recent_window_turns", 10)
    recent_mcp_used = (_turn_counter - _mcp_last_used_turn) <= recent_window
    if recent_mcp_used:
        return True
    text_lower = user_text.lower()
    # server name 命中（工具名格式：{server}__{tool}）
    server_names = {name.split("__")[0] for name in mcp_skills}
    if any(s in text_lower for s in server_names):
        return True
    # capability keyword 命中
    if any(kw in text_lower for kw in _MCP_CAPABILITY_KW):
        return True
    return False


def _handle_project(parts: list[str]):
    global _active_project_id
    sub  = parts[1] if len(parts) > 1 else ""
    rest = " ".join(parts[2:]).strip()

    match sub:
        case "list" | "ls" | "":
            projs = list_projects()
            if not projs:
                console.print("[dim]还没有项目。使用 /project new <名称> 创建。[/dim]")
                return
            t = Table(show_header=True, header_style="bold cyan", box=None)
            t.add_column("ID", style="dim", width=4)
            t.add_column("项目名", style="cyan", width=20)
            t.add_column("状态", width=8)
            t.add_column("最近更新", style="dim", width=20)
            t.add_column("描述")
            for p in projs:
                t.add_row(
                    str(p["id"]), p["name"], p["status"],
                    p["updated_at"][:16], p.get("description", ""),
                )
            console.print(t)
            console.print("[dim]/project new · log · status · archive[/dim]")

        case "new" | "create":
            if not rest:
                console.print("[yellow]用法：/project new <名称> [描述][/yellow]")
                return
            parts2 = rest.split(None, 1)
            name = parts2[0]
            desc = parts2[1] if len(parts2) > 1 else ""
            pid = create_project(name, desc)
            console.print(f"[green]项目已创建：[bold]{name}[/bold]（ID {pid}）[/green]")

        case "log":
            # /project log <ID|名称> <内容>
            tokens = rest.split(None, 1)
            if len(tokens) < 2:
                console.print("[yellow]用法：/project log <ID|名称> <事件内容>[/yellow]")
                return
            ident, content = tokens[0], tokens[1]
            proj = get_project(int(ident)) if ident.isdigit() else get_project_by_name(ident)
            if not proj:
                console.print(f"[yellow]未找到项目：{ident}[/yellow]")
                return
            eid = log_project_event(proj["id"], "note", content)
            console.print(f"[dim]已记录到「{proj['name']}」（事件 {eid}）[/dim]")

        case "status" | "show":
            ident = rest
            if not ident:
                console.print("[yellow]用法：/project status <ID|名称>[/yellow]")
                return
            proj = get_project(int(ident)) if ident.isdigit() else get_project_by_name(ident)
            if not proj:
                console.print(f"[yellow]未找到项目：{ident}[/yellow]")
                return
            console.print(f"\n[bold cyan]{proj['name']}[/bold cyan]  [{proj['status']}]")
            if proj.get("description"):
                console.print(f"[dim]{proj['description']}[/dim]")
            console.print(f"[dim]创建：{proj['created_at'][:16]}  更新：{proj['updated_at'][:16]}[/dim]\n")
            events = get_project_events(proj["id"], limit=15)
            if events:
                t = Table(show_header=True, header_style="bold cyan", box=None)
                t.add_column("时间", style="dim", width=20)
                t.add_column("类型", style="cyan", width=10)
                t.add_column("内容")
                for e in events:
                    t.add_row(e["created_at"][:16], e["event_type"], e["content"])
                console.print(t)
            else:
                console.print("[dim]暂无事件记录。[/dim]")

        case "archive":
            ident = rest
            if not ident:
                console.print("[yellow]用法：/project archive <ID|名称>[/yellow]")
                return
            proj = get_project(int(ident)) if ident.isdigit() else get_project_by_name(ident)
            if not proj:
                console.print(f"[yellow]未找到项目：{ident}[/yellow]")
                return
            if archive_project(proj["id"]):
                if _active_project_id == proj["id"]:
                    _active_project_id = None
                console.print(f"[dim]项目「{proj['name']}」已归档。[/dim]")
            else:
                console.print(f"[yellow]归档失败（可能已归档）。[/yellow]")

        case "use" | "switch":
            ident = rest
            if not ident:
                if _active_project_id:
                    proj = get_project(_active_project_id)
                    name = proj["name"] if proj else "?"
                    console.print(f"[cyan]当前活跃项目：[bold]{name}[/bold]（ID {_active_project_id}）[/cyan]")
                else:
                    console.print("[dim]当前会话未设置活跃项目。用法：/project use <ID|名称>[/dim]")
                return
            proj = get_project(int(ident)) if ident.isdigit() else get_project_by_name(ident)
            if not proj:
                console.print(f"[yellow]未找到项目：{ident}[/yellow]")
                return
            _active_project_id = proj["id"]
            console.print(f"[cyan]已切换到项目：[bold]{proj['name']}[/bold]（ID {proj['id']}）[/cyan]")

        case _:
            console.print("[dim]子命令：list · new · use · log · status · archive[/dim]")


def _handle_doctor(parts: list[str], cfg: dict, skills: dict):
    from core.doctor import run_checks, apply_fixes, Level

    do_fix = len(parts) > 1 and parts[1] == "--fix"
    from datetime import datetime as _dt
    console.print(f"\n[bold cyan]Archer Doctor Report[/bold cyan]  [dim]{_dt.now().strftime('%Y-%m-%d %H:%M')}[/dim]\n")

    results = run_checks(cfg, skills)

    _STYLE = {
        Level.OK:    ("[green]OK   [/green]",    "green"),
        Level.INFO:  ("[cyan]INFO [/cyan]",       "cyan"),
        Level.WARN:  ("[yellow]WARN [/yellow]",   "yellow"),
        Level.ERROR: ("[red]ERROR[/red]",         "red"),
    }

    for r in results:
        badge, _ = _STYLE[r.level]
        console.print(f"  {badge}  [bold]{r.name:<12}[/bold]{r.message}")

    warns  = sum(1 for r in results if r.level == Level.WARN)
    errors = sum(1 for r in results if r.level == Level.ERROR)
    total  = len(results)

    console.print()
    if errors:
        console.print(f"  [red]✗ {errors} 个错误，{warns} 个警告[/red]（共 {total} 项）")
    elif warns:
        console.print(f"  [yellow]△ {warns} 个警告[/yellow]（共 {total} 项正常）")
    else:
        console.print(f"  [green]✓ 全部 {total} 项检查通过[/green]")

    if do_fix:
        console.print()
        fixes = apply_fixes(results)
        if fixes:
            for msg in fixes:
                console.print(f"  [cyan]{msg}[/cyan]")
        else:
            console.print("  [dim]没有可自动修复的问题。[/dim]")
    elif warns or errors:
        fixable = [r for r in results if r.fix_fn is not None and r.level in (Level.WARN, Level.ERROR)]
        if fixable:
            console.print(f"\n  [dim]运行 /doctor --fix 可自动修复 {len(fixable)} 个问题。[/dim]")


def _handle_cron(parts: list[str], skills: dict):
    sub  = parts[1] if len(parts) > 1 else ""
    rest = parts[2:] if len(parts) > 2 else []

    match sub:
        case "list" | "ls" | "":
            tasks = list_tasks()
            if not tasks:
                console.print("[dim]没有定时任务。用 /cron add <技能> <daily|weekly|Nh> [标签] 创建。[/dim]")
                return
            t = Table(show_header=True, header_style="bold cyan", box=None)
            t.add_column("ID",   style="dim", width=4)
            t.add_column("状态", width=6)
            t.add_column("技能", style="cyan", width=18)
            t.add_column("频率", width=10)
            t.add_column("标签")
            t.add_column("下次执行", style="dim", width=20)
            for tk in tasks:
                status = "[green]启用[/green]" if tk["enabled"] else "[dim]禁用[/dim]"
                t.add_row(
                    str(tk["id"]),
                    status,
                    tk["skill_name"],
                    fmt_interval(tk["interval_h"]),
                    tk.get("label", ""),
                    tk["next_run_at"][:16],
                )
            console.print(t)

        case "add":
            if len(rest) < 2:
                console.print("[yellow]用法：/cron add <技能名> <daily|weekly|Nh> [标签][/yellow]")
                return
            skill_name     = rest[0]
            interval_spec  = rest[1]
            label          = " ".join(rest[2:]) if len(rest) > 2 else ""

            if skill_name not in skills:
                console.print(f"[yellow]技能不存在：{skill_name}。使用 /skill list 查看已加载技能。[/yellow]")
                return
            try:
                h = parse_interval(interval_spec)
            except ValueError as e:
                console.print(f"[yellow]{e}[/yellow]")
                return
            tid = add_task(skill_name, interval_spec, label)
            console.print(f"[green]已添加定时任务（ID {tid}）：{skill_name}，{fmt_interval(h)}执行一次。[/green]")
            console.print("[dim]下次启动 Archer 时自动执行，或使用 /cron run {tid} 立即测试。[/dim]")

        case "remove" | "rm" | "delete":
            ident = rest[0] if rest else ""
            if not ident.isdigit():
                console.print("[yellow]用法：/cron remove <ID>[/yellow]")
                return
            if remove_cron_task(int(ident)):
                console.print(f"[dim]定时任务 {ident} 已删除。[/dim]")
            else:
                console.print(f"[yellow]未找到任务：{ident}[/yellow]")

        case "enable":
            ident = rest[0] if rest else ""
            if not ident.isdigit():
                console.print("[yellow]用法：/cron enable <ID>[/yellow]")
                return
            if cron_set_enabled(int(ident), True):
                console.print(f"[dim]任务 {ident} 已启用。[/dim]")
            else:
                console.print(f"[yellow]未找到任务：{ident}[/yellow]")

        case "disable":
            ident = rest[0] if rest else ""
            if not ident.isdigit():
                console.print("[yellow]用法：/cron disable <ID>[/yellow]")
                return
            if cron_set_enabled(int(ident), False):
                console.print(f"[dim]任务 {ident} 已禁用。[/dim]")
            else:
                console.print(f"[yellow]未找到任务：{ident}[/yellow]")

        case "run":
            ident = rest[0] if rest else ""
            if not ident.isdigit():
                console.print("[yellow]用法：/cron run <ID>[/yellow]")
                return
            tid = int(ident)
            tr = run_task_by_id(tid, skills)
            if tr is None:
                tasks = list_tasks()
                task_names = {t["id"]: t["skill_name"] for t in tasks}
                if tid not in task_names:
                    console.print(f"[yellow]未找到任务：{ident}[/yellow]")
                else:
                    console.print(f"[yellow]技能 {task_names[tid]!r} 未加载，无法执行。[/yellow]")
                return
            if tr.ok:
                console.print(f"[green]✓ 执行成功[/green]")
                if tr.content_preview:
                    console.print(tr.content_preview[:600], markup=False)
            else:
                console.print(f"[red]✗ 执行失败：{tr.summary}[/red]")

        case _:
            console.print("[dim]子命令：list · add · remove · enable · disable · run[/dim]")


def _handle_themes(parts: list[str]):
    from memory.patterns import detect_and_save, themes_summary, theme_detail

    sub = parts[1] if len(parts) > 1 else ""

    if sub == "detect":
        console.print("[dim]正在分析记忆库，识别行为模式…[/dim]")
        try:
            saved = detect_and_save()
        except Exception as e:
            console.print(f"[red]检测失败：{e}[/red]")
            return
        if not saved:
            console.print("[dim]记忆量不足或未发现新主题。[/dim]")
            return
        console.print(f"[green]识别到 {len(saved)} 个主题：[/green]")
        for t in saved:
            console.print(f"  [cyan]{t['name']}[/cyan]  {t['description']}")
        return

    if sub.isdigit():
        tid = int(sub)
        meta, mems = theme_detail(tid)
        if meta is None:
            console.print(f"[yellow]未找到主题 {tid}[/yellow]")
            return
        console.print(f"\n[bold cyan]{meta['name']}[/bold cyan]  [{meta['category']}]")
        if meta.get("description"):
            console.print(f"[dim]{meta['description']}[/dim]")
        console.print(f"[dim]出现次数：{meta['occurrence_count']}  最后见于：{meta['last_seen_at']}[/dim]\n")
        if mems:
            t = Table(show_header=True, header_style="bold cyan", box=None)
            t.add_column("★", width=6)
            t.add_column("类型", style="cyan", width=12)
            t.add_column("关联度", width=8)
            t.add_column("内容")
            for m in mems:
                t.add_row(
                    "★" * min(int(m.get("importance", 3)), 5),
                    m.get("type", ""),
                    f"{m.get('strength', 0.5):.1f}",
                    m.get("content", ""),
                )
            console.print(t)
        else:
            console.print("[dim]该主题暂无关联记忆。[/dim]")
        return

    # default: list
    themes = themes_summary(15)
    if not themes:
        console.print("[dim]尚未归纳任何主题。使用 /themes detect 开始分析。[/dim]")
        return
    t = Table(show_header=True, header_style="bold cyan", box=None)
    t.add_column("ID", style="dim", width=4)
    t.add_column("主题", style="cyan", width=16)
    t.add_column("类型", width=12)
    t.add_column("次数", width=6)
    t.add_column("描述")
    for th in themes:
        t.add_row(
            str(th["id"]),
            th["name"],
            th["category"],
            str(th["occurrence_count"]),
            th.get("description", ""),
        )
    console.print(t)
    console.print("[dim]/themes detect 归纳新主题 · /themes <ID> 查看详情[/dim]")


def _handle_memory(parts: list[str], session=None):
    sub = parts[1] if len(parts) > 1 else ""
    arg = " ".join(parts[2:])
    match sub:
        case "list":   _memory_list()
        case "search": _memory_search(arg)
        case "add":    _memory_add(arg)
        case "pending": _memory_pending(arg)
        case "accept": _memory_accept(arg)
        case "reject": _memory_reject(arg)
        case "update": _memory_update(arg)
        case "archive": _memory_archive(arg)
        case "delete": _memory_delete(arg)
        case "review": _memory_review()
        case "extract":
            history = session.history if session else []
            if len(history) < 2:
                console.print("[dim]对话历史不足，无法提炼。[/dim]")
            else:
                _wait_for_extract()
                _auto_extract(history, silent=False)
        case "reindex":
            console.print("[dim]正在重建向量索引（首次需要下载模型 ~120 MB）…[/dim]")
            try:
                from memory.vector_store import reindex_all
                ok, total = reindex_all()
                console.print(f"[green]向量索引重建完成：{ok}/{total} 条记忆已编码。[/green]")
            except Exception as e:
                console.print(f"[yellow]向量索引失败（sqlite-vec 或 sentence-transformers 未安装？）：{e}[/yellow]")
        case _:
            console.print("[dim]子命令：list · search <词> · add <内容> · pending [review] · accept · reject · update · archive · delete · review · extract · reindex[/dim]")

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
    return run_with_tools(messages, skills, stream_fn=_stream, console=console, model=model)

def _auto_extract(history: list[dict], silent: bool = False):
    if len(history) < 2:
        return
    if not silent:
        console.print("\n[dim]正在提炼记忆…[/dim]")
    try:
        mems, obsidian_hints = extract(history)
        if mems:
            _stage_memories(mems, source="auto", silent=silent)
            # SOUL 相关记忆 → soul proposal（不自动写入）
            soul_ids = propose_from_memories(mems, source="extract")
            if soul_ids and not silent:
                console.print(f"[dim]发现 {len(soul_ids)} 条 SOUL 演化提议，使用 /soul 查看。[/dim]")
        elif not silent:
            console.print("[dim]本次对话无新记忆。[/dim]")

        if obsidian_hints:
            soul_ids_h = propose_from_obsidian_hints(obsidian_hints, source="extract")
            non_soul = [h for h in obsidian_hints if h.get("file") != "SOUL.md"]
            if non_soul and not silent:
                for hint in non_soul:
                    console.print(
                        f"\n[cyan]建议写入 {hint['file']}：[/cyan]\n"
                        f"  [dim]{hint['content'][:80]}[/dim]"
                    )
            if soul_ids_h and not silent:
                console.print(f"[dim]发现 {len(soul_ids_h)} 条 SOUL 演化提议，使用 /soul 查看。[/dim]")
    except Exception:
        pass


def _bg_extract(history: list[dict]):
    """在后台线程中静默提炼，不阻塞 REPL。若上一次提炼仍在进行则跳过。"""
    global _extract_thread
    if _extract_thread and _extract_thread.is_alive():
        return
    snapshot = list(history)
    _extract_thread = threading.Thread(
        target=_auto_extract, args=(snapshot, True), daemon=True
    )
    _extract_thread.start()


def _wait_for_extract(timeout: float = 12.0):
    """退出前等待后台提炼线程结束，最多等待 timeout 秒。"""
    if _extract_thread and _extract_thread.is_alive():
        _extract_thread.join(timeout=timeout)

def run():
    global _current_session_id, _turn_counter, _mcp_last_used_turn
    init_db()
    _current_session_id = generate_session_id()
    # 初始化向量索引表（sqlite-vec 未安装时静默跳过）
    try:
        from memory.vector_store import init_vec_table
        init_vec_table()
    except Exception:
        pass
    cfg = load_config()
    session = Session()
    skills = load_skills()

    # ── MCP 初始化（可选，配置驱动）─────────────────────────────────────────
    _mcp_manager = None
    _mcp_skills: dict = {}
    try:
        _mcp_manager = mcp_load(cfg)
        if _mcp_manager:
            _mcp_skills = _mcp_manager.make_skill_modules()
            if _mcp_skills:
                console.print(f"[dim]MCP：已加载 {len(_mcp_skills)} 个工具（{', '.join(sorted(_mcp_skills))}）[/dim]")
    except Exception as _e:
        console.print(f"[dim]MCP 初始化失败，已跳过：{_e}[/dim]")

    _welcome()

    # ── 启动时执行到期定时任务 ─────────────────────────────────────────────────
    startup_cron = run_due_tasks(skills)
    for task, tr in startup_cron:
        label = task.get("label") or task["skill_name"]
        if tr is None:
            console.print(f"[yellow]⏰ 定时任务「{label}」：技能未加载，已跳过。[/yellow]")
        elif tr.ok:
            console.print(f"[dim]⏰ 定时任务「{label}」已执行。[/dim]")
            if tr.content_preview:
                console.print(tr.content_preview[:400], markup=False)
        else:
            console.print(f"[yellow]⏰ 定时任务「{label}」执行失败：{tr.summary}[/yellow]")

    turn_count = 0

    while True:
        # ── 配置热加载 ─────────────────────────────────────────────────
        cfg = load_config()
        if pop_config_reloaded():
            console.print("[dim]archer.toml 已更新，配置已重新加载。[/dim]")

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

        # 静默录入模式在状态栏显示特殊标识
        display_mode = "🎙 静默录入" if _listen_mode else mode_name

        console.print()
        try:
            user_input = get_input(
                model=current_model,
                mode=display_mode,
                usage=_usage_status(cfg),
            )
        except (KeyboardInterrupt, EOFError):
            console.print()
            _wait_for_extract()
            if len(session.history) >= 2:
                _auto_extract(session.history, silent=True)
            session.save()
            if _mcp_manager:
                _mcp_manager.stop()
            console.print("[dim]已退出。[/dim]")
            break

        if not user_input:
            continue

        # ── 静默录入模式拦截 ────────────────────────────────────────────
        if _listen_mode:
            if user_input.strip() in ("/listen", "/listen stop"):
                _handle_listen(["/listen", "stop"])
            else:
                _listen_write(user_input)
                console.print("[dim]已记录。[/dim]")
            continue

        parts = user_input.split()
        if user_input.startswith("/") and parts[0] in _CMDS:
            match parts[0]:
                case "/exit":
                    if len(session.history) >= 2:
                        console.print("[dim]正在提炼本次会话记忆…[/dim]")
                        _wait_for_extract()
                        _auto_extract(session.history, silent=False)
                    saved = session.save()
                    console.print(f"[dim]会话已保存 → {saved}[/dim]")
                    if _mcp_manager:
                        _mcp_manager.stop()
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
                    _handle_memory(parts, session)
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
                case "/themes":
                    _handle_themes(parts)
                case "/project":
                    _handle_project(parts)
                case "/soul":
                    _handle_soul(parts, cfg)
                case "/covenant":
                    _handle_covenant(parts, cfg)
                case "/presence":
                    _handle_presence(parts, cfg)
                case "/critique":
                    _handle_critique(parts, cfg)
                case "/listen":
                    _handle_listen(parts)
                case "/doctor":
                    _handle_doctor(parts, cfg, skills)
                case "/cron":
                    _handle_cron(parts, skills)
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
        intent_info = classify_query_intent(user_text)
        heavy       = intent_info["needs_memory"]
        intent      = intent_info["intent"]
        project     = get_project(_active_project_id) if _active_project_id else None
        proj_evts   = get_project_events(_active_project_id, limit=3) if _active_project_id else []
        messages    = build_messages(
            session.history, user_content, cfg,
            db_memories=mem_block, project=project,
            project_events=proj_evts, heavy=heavy,
            intent=intent,
        )

        has_images = any(r["type"] == "image" for r in refs)
        active_model = ""
        if has_images:
            vision_model = cfg["api"].get("vision_model", "")
            text_model   = cfg["api"]["model"]
            if not vision_model or vision_model == text_model:
                console.print("[yellow]图片需要支持视觉的模型，请在 archer.toml 中配置 vision_model。[/yellow]")
                has_images = False
                user_content = user_text
                messages = build_messages(
                    session.history, user_content, cfg,
                    db_memories=mem_block, project=project,
                    project_events=proj_evts, heavy=heavy,
                )
            else:
                active_model = vision_model
                console.print(f"[dim]图片模式 → {active_model}[/dim]")

        try:
            active_skills = select_skills(user_text, skills)
            # MCP 工具：三条件策略注入（recent/server_name/capability_keyword）
            if _mcp_skills and _should_inject_mcp(user_text, _mcp_skills, cfg):
                active_skills = {**active_skills, **_mcp_skills}
            if active_skills:
                full_response = _run_with_tools(messages, active_skills, model=active_model)
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
        _turn_counter += 1

        if turn_count % 6 == 0 and len(session.history) >= 6:
            _bg_extract(session.history[-8:])

if __name__ == "__main__":
    run()
