"""终端 UI 渲染函数与常量（从 archer.py 抽取）。"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from rich.console import Console
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text as _RichText

from core.llm import get_session_tokens
from memory.store import (
    save,
    list_all,
    search,
    delete,
    update as update_memory,
    archive as archive_memory,
    add_pending,
    list_pending,
    count_pending,
    accept_pending,
    reject_pending,
    update_pending,
    count_soul_proposals,
    get_project,
    list_projects,
)

# ── 模块级 Console（与 archer.py 中等价）────────────────────────────────────
console = Console()


def stage_memories(mems: list[dict], source: str = "auto", silent: bool = False):
    """将提炼的记忆候选写入 pending，供用户确认。"""
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
            depth=m.get("depth", 3),
        )
        count += 1
    if not silent:
        console.print(f"[dim]提议写入 {count} 条记忆，使用 /memory pending 查看。[/dim]")

# ── 常量 ───────────────────────────────────────────────────────────────────────

_VERSION = "v1.5"

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

_MEM_TYPE_COLORS = {
    "decision":   "#4dd9d4",
    "insight":    "#b8a050",
    "todo":       "#c44e00",
    "project":    "#4dd9d4",
    "preference": "#6a8a78",
    "context":    "dim",
}

_DSML_MARKER = "｜｜DSML｜｜"


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

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


# ── 欢迎与帮助 ────────────────────────────────────────────────────────────────

def _welcome(cfg: dict | None = None):
    console.print()
    console.print(f"  {_RING_TOP}  [#4dd9d4]{_ARCHER_NAME}[/#4dd9d4]  [dim]{_VERSION}[/dim]")
    console.print(f"  {_RING_BOT}  [dim]于时间的荒原里，为自己建一座神庙。[/dim]")
    console.print()


def _onboard() -> dict | None:
    """首次运行引导：收集 API 配置并写入 archer.toml。返回配置 dict 或 None（跳过）。"""
    from prompt_toolkit import prompt as _pt_prompt

    console.print()
    console.print(f"  {_RING_TOP}  [#4dd9d4]{_ARCHER_NAME}[/#4dd9d4]  [dim]{_VERSION}[/dim]")
    console.print(f"  {_RING_BOT}  [dim]于时间的荒原里，为自己建一座神庙。[/dim]")
    console.print()
    console.print("  [#4dd9d4]首次运行 — 快速配置[/#4dd9d4]")
    console.print("  [dim]按 Enter 跳过任何步骤，稍后手动编辑 archer.toml[/dim]")
    console.print()

    # API Base URL
    console.print("  [#f5c842]1.[/#f5c842] API 地址（如 https://api.openai.com/v1）")
    base_url = _pt_prompt("     > ").strip()
    if not base_url:
        base_url = ""

    # API Key
    console.print("  [#f5c842]2.[/#f5c842] API Key")
    api_key = _pt_prompt("     > ").strip()
    if not api_key:
        api_key = ""

    # Model
    console.print("  [#f5c842]3.[/#f5c842] 模型名称（如 gpt-4o、deepseek-chat）")
    model = _pt_prompt("     > ").strip()
    if not model:
        model = ""

    if not api_key and not model:
        console.print()
        console.print("  [dim]未提供配置，跳过。可稍后编辑 archer.toml。[/dim]")
        console.print()
        return None

    # 写入 archer.toml
    import tomli_w
    from terminal.api._config import CONFIG_PATH

    cfg = {
        "api": {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
        }
    }
    try:
        CONFIG_PATH.write_bytes(tomli_w.dumps(cfg))
        console.print()
        console.print(f"  [#4dd9d4]✓[/#4dd9d4] 配置已写入 [dim]{CONFIG_PATH}[/dim]")
        console.print()
    except Exception as e:
        console.print(f"  [red]写入失败：{e}[/red]")
        console.print(f"  [dim]请手动创建 {CONFIG_PATH}[/dim]")
        console.print()

    return cfg


def _help(show_all: bool = False):
    def _section(title: str):
        console.print(f"\n  [#4dd9d4 bold]{title}[/#4dd9d4 bold]")

    def _row(cmd: str, desc: str):
        console.print(f"  [dim]{cmd:<42}[/dim]{desc}")

    _section("对话 & 会话")
    _row("/help [--all]",             "查看命令（--all 显示全部）")
    _row("/status",                    "查看当前状态")
    _row("/dash",                      "仪表盘：上下文 / 记忆 / 项目概览")
    _row("/mode [<模式名>]",            "切换对话模式  /mode create <名称> 新建")
    _row("/model [<模型名>]",           "查看 / 切换模型")
    _row("/reflect",                   "复盘最近对话，提取记忆/决策/待办")
    _row("/sessions [天数]",           "最近 N 天会话统计（默认 7 天）")
    _row("/copy",                      "复制上一条回复到剪贴板")

    _section("记忆 & 灵魂")
    _row("/memory list/search/add",    "管理记忆库")
    _row("/memory pending [review]",   "查看 / 交互审阅待确认记忆")
    _row("/soul",                      "查看 SOUL 演化提议")
    _row("/insight list/search",       "查看正向洞察记录")

    _section("系统 & 技能")
    _row("/skill list/install/remove", "管理技能插件")
    _row("/doctor [--fix]",            "自检系统状态")
    _row("/portrait [view]",           "生成 / 查看自我画像")
    _row("/chronicle [天数|history]",  "生成主题叙事（默认 14 天）")
    _row("/project",                   "列出 / 切换 / 归档项目")
    _row("/work list/new/start/done",  "任务管理")
    _row("/cron list/add/remove",      "定时任务管理")
    _row("/exit",                      "退出并保存")

    if show_all:
        _section("─ 更多")
        _row("/sessions search <词>",      "全文搜索历史会话")
        _row("/save",                      "保存当前会话")
        _row("/clear",                     "清空对话历史")
        _row("/compact",                   "手动压缩对话历史")
        _row("/listen [stop]",             "静默录入模式")
        _row("/memory export [路径]",      "导出全部记忆为 JSON")
        _row("/memory extract",            "立即提炼会话记忆")
        _row("/memory reindex",            "重建向量索引")
        _row("/memory review",             "体检记忆库")
        _row("/soul accept/reject/view",   "接受/拒绝/查看 SOUL 提议")
        _row("/skill suggest [--apply]",   "分析技能缺口")
        _row("/login",                     "邮箱 Magic Link 登录")
        _row("/cron add/remove/run",       "定时任务详情")
        _row("/project new/log/status",    "项目详情操作")
        _row("/portrait [view]",            "生成 / 查看自我画像")
        _row("/chronicle [天数|history]",   "生成 / 查看主题叙事")
        _row("/subtask add/list/run <ID>", "子代理任务管理")
        _row("/workflow",                  "查看 / 运行工作流")
        _row("/critique scan/list/view",   "自我批评诊断")
        _row("/covenant view/propose",     "根契约管理")
        _row("/presence view/edit",        "在场方式管理")
    console.print()


# ── 状态与仪表盘 ───────────────────────────────────────────────────────────────

def _status(session, skills: dict, cfg: dict, active_project_id: int | None = None):
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
    used   = _fmt_tokens(get_session_tokens())
    limit  = _fmt_tokens(_token_limit(cfg))
    console.print(f"  [#4dd9d4 bold]Archer {_VERSION}[/#4dd9d4 bold]")
    console.print(f"  模型        {model}")
    console.print(f"  模式        [dim]{mode_name}[/dim]")
    console.print(f"  上下文      {used} / {limit}")
    console.print(f"  技能        {len(skills)} 个：{', '.join(sorted(skills.keys()))}")
    soul_count = count_soul_proposals()
    console.print(f"  记忆库      {mem_count} 条" + (f"  [dim]（{pending_count} 条待确认）[/dim]" if pending_count else ""))
    if soul_count:
        console.print(f"  SOUL 提议   [dim]{soul_count} 条  /soul 查看[/dim]")
    console.print(f"  对话历史    {history_turns} 轮（{len(session.history)} 条消息）")
    console.print(f"  Artifacts   {art_size}（位于 .artifacts/）")
    if active_project_id:
        proj = get_project(active_project_id)
        pname = proj["name"] if proj else "?"
        console.print(f"  活跃项目    [#4dd9d4]{pname}[/#4dd9d4]（ID {active_project_id}）")


def _dash(cfg: dict, session, skills: dict, active_project_id: int | None = None):
    from memory.session_insights import analyze as si_analyze
    from memory.work import list_active as work_active
    from memory.store import list_all as mem_list_all
    from core.artifacts import dir_size, fmt_size

    mem_all    = mem_list_all(9999)
    mem_count  = len(mem_all)
    pending    = count_pending()
    soul_count = count_soul_proposals()
    projects   = list_projects()
    works      = work_active()
    si         = si_analyze(30)
    used_tok   = get_session_tokens()
    limit_tok  = _token_limit(cfg)
    pct        = used_tok / limit_tok if limit_tok else 0

    type_counts: dict[str, int] = {}
    for m in mem_all:
        t = m.get("type", "insight")
        type_counts[t] = type_counts.get(t, 0) + 1

    console.print()
    console.print(f"  [#4dd9d4 bold]Archer {_VERSION}[/#4dd9d4 bold]  [dim]仪表盘[/dim]")
    console.print()

    # 上下文用量
    filled = int(pct * 20)
    bar = "█" * filled + "░" * (20 - filled)
    pct_label = "[bold]" if pct > 0.8 else ""
    pct_end = "[/bold]" if pct > 0.8 else ""
    console.print(f"  上下文  {bar}  [dim]{_fmt_tokens(used_tok)} / {_fmt_tokens(limit_tok)}{pct_label} ({int(pct*100)}%){pct_end}[/dim]")
    console.print()

    # 记忆库分布
    pending_label = f"  [dim]{pending} 待确认[/dim]" if pending else ""
    console.print(f"  [bold]记忆库[/bold]  [dim]{mem_count} 条[/dim]{pending_label}")
    if type_counts:
        max_c = max(type_counts.values())
        _BAR_COLORS = {"insight": "dim", "decision": "#4dd9d4", "todo": "dim",
                       "preference": "dim", "context": "dim", "project": "#4dd9d4"}
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1])[:6]:
            bar_w = max(1, int(c / max_c * 14))
            color = _BAR_COLORS.get(t, "dim")
            console.print(f"  [dim]  {t:<12}[/dim] [{color}]{'█' * bar_w}[/{color}] [dim]{c}[/dim]")
    console.print()

    # 近 30 天会话
    console.print(
        f"  [bold]近 30 天[/bold]  "
        f"[dim]{si['sessions']} 次会话  {si['turns']} 轮  均 {si['avg_turns_per_session']} 轮/次[/dim]"
    )
    console.print()

    # 项目 & 任务
    active_projects = [p for p in projects if p.get("status") != "archived"]
    if active_projects:
        console.print(f"  [bold]项目[/bold]  [dim]{len(active_projects)} 个[/dim]")
        for p in active_projects[:5]:
            dot = "[#4dd9d4]●[/#4dd9d4]" if p.get("status") == "active" else "[dim]○[/dim]"
            console.print(f"    {dot} [dim]{p['name']}[/dim]")
        console.print()
    if works:
        console.print(f"  [bold]任务[/bold]  [dim]{len(works)} 个进行中[/dim]")
        for w in works[:3]:
            console.print(f"    [dim]· {w['title'][:40]}[/dim]")
        console.print()

    if soul_count:
        console.print(f"  [dim]SOUL 提议  {soul_count} 条  /soul 查看[/dim]")
        console.print()

    # P3: 情绪趋势
    from memory.emotion import emotion_summary, recent_emotion
    recent_emo = recent_emotion(7)
    if recent_emo:
        emo_bars = []
        for e in ["焦虑", "专注", "疲惫", "兴奋", "平静", "沮丧"]:
            s = recent_emo.get(e, 0)
            bar_w = max(1, int(s))
            emo_bars.append(f"{e} {'█' * bar_w}{s:.0f}")
        console.print(f"  [bold]情绪（近 7 天）[/bold]")
        console.print(f"    [dim]{'  '.join(emo_bars)}[/dim]")
        summary = emotion_summary(30)
        if summary:
            console.print(f"    [dim]{summary}[/dim]")
        console.print()


# ── 会话搜索 ─────────────────────────────────────────────────────────────────

def _sessions_search(keyword: str):
    from memory.session_insights import search_sessions
    results = search_sessions(keyword)
    if not results:
        console.print(f"[dim]没有找到包含「{keyword}」的会话。[/dim]")
        return
    for r in results:
        console.print(f"  [dim]{r['session_id']}[/dim]  {r['preview']}")


# ── 记忆导出 ─────────────────────────────────────────────────────────────────

def _memory_export(arg: str):
    import json as _json
    mems = list_all(9999)
    if not mems:
        console.print("[dim]记忆库为空，无需导出。[/dim]")
        return
    out = Path(arg.strip()) if arg.strip() else Path.home() / "archer_memories.json"
    out.write_text(_json.dumps(mems, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[dim]已导出 {len(mems)} 条记忆 → {out}[/dim]")


# ── 记忆类型标签 ──────────────────────────────────────────────────────────────

def _mem_type_rich(t: str) -> str:
    """返回带颜色的记忆类型 Rich 标签。"""
    color = _MEM_TYPE_COLORS.get(t, "#8a9dac")
    return f"[{color}]{t}[/{color}]"


# ── 记忆管理 UI ──────────────────────────────────────────────────────────────

def _memory_list():
    mems = list_all(50)
    if not mems:
        console.print("[dim]记忆库为空。[/dim]")
        return
    for m in mems:
        stars = "[#b8a050]" + "★" * min(m["importance"], 5) + "[/#b8a050]"
        t = m.get("type", "insight")
        tid = _mem_type_rich(t)
        console.print(
            f"  [dim]{m['id']:>4}[/dim]  {stars:<11}  "
            f"{tid:<12}  {m['content']}"
        )


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


def _memory_pending(arg: str = ""):
    if arg.strip() in ("review", "interactive"):
        _memory_pending_review()
        return
    pends = list_pending()
    if not pends:
        console.print("[dim]没有待确认记忆。[/dim]")
        return
    t = Table(show_header=True, header_style="bold #4dd9d4", box=None)
    t.add_column("ID", style="dim", width=4)
    t.add_column("重要", width=6)
    t.add_column("类型", width=12)
    t.add_column("内容")
    for p in pends:
        stars = "[#f5c842]" + "★" * min(int(p.get("importance", 3)), 5) + "[/#f5c842]"
        t.add_row(
            str(p["id"]),
            stars,
            _mem_type_rich(p.get("type", "insight")),
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
        console.print(f"[dim]#{pid}[/dim] {_mem_type_rich(p.get('type', 'insight'))} [#4a5a68]重要度 {p.get('importance', 3)}[/#4a5a68]")
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


# ── Markdown 清理 ─────────────────────────────────────────────────────────────

def _strip_md(text: str) -> str:
    """移除常见 Markdown 语法符号，输出干净的纯文本。"""
    # 加粗 / 斜体
    text = re.sub(r'\*{1,3}([^\*\n]+?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}([^_\n]+?)_{1,2}', r'\1', text)
    # 标题
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # 分隔线
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # 行内代码（保留内容）
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # 链接 [text](url)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # 引用块 >
    text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)
    # 无序列表符号 - / * / + → ·
    text = re.sub(r'^(\s*)[-*+]\s+', r'\1· ', text, flags=re.MULTILINE)
    # 清理多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── 品牌 Spinner ─────────────────────────────────────────────────────────────

def _brand_spinner(label: str = "处理中") -> Spinner:
    """返回带 Archer 品牌彩色名称的 Rich Spinner。"""
    t = _RichText()
    t.append("  ")
    t.append("◜", style="#5ee8e0")
    t.append("◝", style="#1e7be8")
    t.append(" ")
    for ch, color in zip("Archer", ["#5ee8e0","#2aabf0","#1e7be8","#f5c842","#f5a030","#f5612a"]):
        t.append(ch, style=f"bold {color}")
    t.append(f"  {label}…", style="#4a5a68")
    return Spinner("dots", text=t, style="default")
