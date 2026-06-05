"""系统命令。"""
from __future__ import annotations

from .registry import register
from rich.console import Console
from core.scheduler import (
    add_task, remove_task as remove_cron_task, set_enabled as cron_set_enabled,
    list_tasks, run_due_tasks, run_task_by_id, parse_interval, fmt_interval,
)
from workflows.runner import handle_workflow
from memory.narrative import (
    self_portrait, save_portrait, load_portrait,
    theme_chronicle, save_chronicle, chronicle_history,
)
from terminal.ui import _brand_spinner
from core.llm import get_session_tokens, stream_chat

console = Console()

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
                console.print("[yellow]用法：/cron add <技能名> <daily|weekly|Nh> [--skip] [标签][/yellow]")
                return
            skill_name    = rest[0]
            interval_spec = rest[1]
            remaining     = rest[2:]
            catchup       = "skip" if "--skip" in remaining else "latest"
            label         = " ".join(r for r in remaining if r != "--skip")

            if skill_name not in skills:
                console.print(f"[yellow]技能不存在：{skill_name}。使用 /skill list 查看已加载技能。[/yellow]")
                return
            try:
                h = parse_interval(interval_spec)
            except ValueError as e:
                console.print(f"[yellow]{e}[/yellow]")
                return
            tid = add_task(skill_name, interval_spec, label, catchup=catchup)
            strategy_hint = "（错过时跳过）" if catchup == "skip" else "（错过时补跑一次）"
            console.print(f"[green]已添加定时任务（ID {tid}）：{skill_name}，{fmt_interval(h)}执行一次{strategy_hint}。[/green]")
            console.print(f"[dim]下次启动 Archer 时自动执行，或使用 /cron run {tid} 立即测试。[/dim]")

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


# ── 命令注册 ──────────────────────────────────────────────────────────────────

def _cmd_themes(ctx):
    _handle_themes(ctx['parts'])


def _cmd_workflow(ctx):
    handle_workflow(ctx['parts'], ctx['console'], ctx['cfg'])


def _cmd_cron(ctx):
    _handle_cron(ctx['parts'], ctx['skills'])


def _cmd_portrait(ctx):
    """生成 / 查看自我画像。"""
    from memory.narrative import self_portrait, save_portrait, load_portrait
    parts = ctx['parts']
    arg = parts[1] if len(parts) > 1 else ""
    if arg == "view":
        existing = load_portrait()
        if existing:
            ctx['console'].print(existing)
        else:
            ctx['console'].print("[dim]暂无画像，使用 /portrait 生成。[/dim]")
    else:
        ctx['console'].print("[dim]正在生成自我画像…[/dim]")
        portrait = self_portrait()
        if portrait and not portrait.startswith("画像生成失败"):
            path = save_portrait(portrait)
            ctx['console'].print(f"\n{portrait}\n")
            ctx['console'].print(f"[dim]已保存到 {path}[/dim]")
        else:
            ctx['console'].print(f"[yellow]{portrait}[/yellow]")


def _cmd_chronicle(ctx):
    """生成 / 查看主题记事。"""
    from memory.narrative import theme_chronicle, save_chronicle, chronicle_history
    parts = ctx['parts']
    arg = parts[1] if len(parts) > 1 else ""
    if arg == "history":
        entries = chronicle_history()
        if not entries:
            ctx['console'].print("[dim]暂无主题记事。[/dim]")
        else:
            for e in entries:
                ctx['console'].print(f"  [dim]{e['date']}[/dim]  {e['preview']}")
    else:
        days = int(arg) if arg.isdigit() else 14
        ctx['console'].print(f"[dim]正在生成 {days} 天主题叙事…[/dim]")
        text = theme_chronicle(days)
        if text and not text.startswith("主题叙事生成失败"):
            path = save_chronicle(text)
            ctx['console'].print(f"\n{text}\n")
            ctx['console'].print(f"[dim]已保存到 {path}[/dim]")
        else:
            ctx['console'].print(f"[yellow]{text}[/yellow]")


register("/themes", _cmd_themes, "主题管理")
register("/workflow", _cmd_workflow, "查看/运行工作流")
register("/cron", _cmd_cron, "定时任务管理")
register("/portrait", _cmd_portrait, "生成/查看自我画像")
register("/chronicle", _cmd_chronicle, "生成/查看主题叙事")
