"""人格管理命令。"""
from __future__ import annotations

from .registry import register
from rich.console import Console
from memory.store import (
    save, list_all, search, delete, add_pending, list_pending, count_pending,
)
from terminal.ui import _brand_spinner
from core.llm import get_session_tokens, stream_chat

console = Console()

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
    """自我批评管理：scan / list / view / reject / new。"""
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
            console.print("\n[dim]/critique view <ID> · /critique reject <ID>[/dim]")

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

        case "reject" | "dismiss":
            if not arg.isdigit():
                console.print("[yellow]用法：/critique reject <ID>[/yellow]")
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
            console.print("[dim]子命令：scan · list · view <ID> · reject <ID> · new[/dim]")


# ── 命令注册 ──────────────────────────────────────────────────────────────────

def _cmd_covenant(ctx):
    _handle_covenant(ctx['parts'], ctx['cfg'])


def _cmd_presence(ctx):
    _handle_presence(ctx['parts'], ctx['cfg'])


def _cmd_critique(ctx):
    _handle_critique(ctx['parts'], ctx['cfg'])


register("/covenant", _cmd_covenant, "根契约管理")
register("/presence", _cmd_presence, "在场方式管理")
register("/critique", _cmd_critique, "自我批评诊断")
