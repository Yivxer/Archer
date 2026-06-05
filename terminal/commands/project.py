"""项目与任务命令。"""
from __future__ import annotations

from .registry import register
from rich.console import Console
from rich.table import Table
from memory.store import (
    save, list_all, search, delete, add_pending, list_pending, count_pending,
    create_project, list_projects, get_project, get_project_by_name,
    archive_project, log_project_event, get_project_events,
    count_soul_proposals,
)
from memory.work import (
    list_active, create as work_create, update_status,
    add_checklist_item, check_item, delete as work_delete,
)
from memory.subtask import (
    create as sub_create, list_for_work, delete as sub_delete,
    set_running as sub_set_running, set_done as sub_set_done, set_failed as sub_set_failed, cancel as sub_cancel,
)
from terminal.ui import _brand_spinner
from terminal.state import get_state
from core.llm import get_session_tokens, stream_chat

console = Console()

def _handle_project(parts: list[str]):
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
                if get_state().active_project_id == proj["id"]:
                    get_state().active_project_id = None
                console.print(f"[dim]项目「{proj['name']}」已归档。[/dim]")
            else:
                console.print(f"[yellow]归档失败（可能已归档）。[/yellow]")

        case "use" | "switch":
            ident = rest
            if not ident:
                if get_state().active_project_id:
                    proj = get_project(get_state().active_project_id)
                    name = proj["name"] if proj else "?"
                    console.print(f"[cyan]当前活跃项目：[bold]{name}[/bold]（ID {get_state().active_project_id}）[/cyan]")
                else:
                    console.print("[dim]当前会话未设置活跃项目。用法：/project use <ID|名称>[/dim]")
                return
            proj = get_project(int(ident)) if ident.isdigit() else get_project_by_name(ident)
            if not proj:
                console.print(f"[yellow]未找到项目：{ident}[/yellow]")
                return
            get_state().active_project_id = proj["id"]
            console.print(f"[cyan]已切换到项目：[bold]{proj['name']}[/bold]（ID {proj['id']}）[/cyan]")

        case _:
            console.print("[dim]子命令：list · new · use · log · status · archive[/dim]")

def _handle_work(parts: list[str], skills: dict | None = None, cfg: dict | None = None):
    """Work item 任务追踪：new / list / view / add / check / start / done / cancel / all。"""
    from memory.work import (
        create as work_create, get as work_get,
        list_active, list_all as work_list_all,
        update_status, add_checklist_item, check_item, delete as work_delete,
    )
    sub = parts[1] if len(parts) > 1 else "list"
    rest = parts[2:]

    def _status_tag(s: str) -> str:
        return {
            "pending":     "[dim]待开始[/dim]",
            "in_progress": "[yellow]进行中[/yellow]",
            "done":        "[green]完成[/green]",
            "cancelled":   "[dim]已取消[/dim]",
        }.get(s, s)

    def _print_list(items: list):
        if not items:
            console.print("[dim]没有任务。用 /work new \"标题\" 创建。[/dim]")
            return
        t = Table(show_header=True, header_style="bold cyan", box=None)
        t.add_column("ID",   style="dim", width=4)
        t.add_column("状态", width=8)
        t.add_column("标题")
        t.add_column("进度", width=8)
        t.add_column("更新", style="dim", width=11)
        for w in items:
            cl = w["checklist"]
            progress = f"{sum(1 for c in cl if c['done'])}/{len(cl)}" if cl else "—"
            t.add_row(
                str(w["id"]),
                _status_tag(w["status"]),
                w["title"],
                progress,
                (w.get("updated_at") or "")[:10],
            )
        console.print(t)

    match sub:
        case "list" | "ls" | "":
            _print_list(list_active())

        case "all":
            _print_list(work_list_all())

        case "new" | "create":
            if not rest:
                console.print("[yellow]用法：/work new \"标题\" [--desc \"描述\"][/yellow]")
                return
            # 解析 --desc
            title_parts, desc_parts, in_desc = [], [], False
            for tok in rest:
                if tok == "--desc":
                    in_desc = True
                elif in_desc:
                    desc_parts.append(tok)
                else:
                    title_parts.append(tok)
            title = " ".join(title_parts).strip('"').strip("'")
            desc  = " ".join(desc_parts).strip('"').strip("'")
            if not title:
                console.print("[yellow]标题不能为空。[/yellow]")
                return
            wid = work_create(title, description=desc)
            console.print(f"[green]已创建 Work #{wid}：{title}[/green]")
            console.print(f"[dim]用 /work add {wid} \"检查项\" 添加步骤，/work start {wid} 开始执行。[/dim]")

        case "view":
            if not rest or not rest[0].isdigit():
                console.print("[yellow]用法：/work view <ID>[/yellow]")
                return
            w = work_get(int(rest[0]))
            if not w:
                console.print(f"[yellow]找不到 Work #{rest[0]}。[/yellow]")
                return
            console.print(f"\n[bold]{w['title']}[/bold]  [dim]#{w['id']}  {(w.get('created_at') or '')[:16]}[/dim]")
            console.print(f"状态：{_status_tag(w['status'])}")
            if w["description"]:
                console.print(f"说明：{w['description']}")
            if w["checklist"]:
                console.print(f"\n检查项（{len(w['checklist'])} 项）：")
                for i, c in enumerate(w["checklist"], 1):
                    mark = "[green]✓[/green]" if c["done"] else "○"
                    console.print(f"  {i}. {mark} {c['item']}")
            if w["artifacts"]:
                console.print(f"\n产出文件：")
                for a in w["artifacts"]:
                    console.print(f"  · {a}")
            console.print()

        case "add":
            if len(rest) < 2 or not rest[0].isdigit():
                console.print("[yellow]用法：/work add <ID> \"检查项文本\"[/yellow]")
                return
            item_text = " ".join(rest[1:]).strip('"').strip("'")
            if add_checklist_item(int(rest[0]), item_text):
                console.print(f"[dim]已添加检查项到 Work #{rest[0]}。[/dim]")
            else:
                console.print(f"[yellow]找不到 Work #{rest[0]}。[/yellow]")

        case "check":
            if len(rest) < 2 or not rest[0].isdigit() or not rest[1].isdigit():
                console.print("[yellow]用法：/work check <ID> <检查项序号>[/yellow]")
                return
            if check_item(int(rest[0]), int(rest[1])):
                console.print(f"[dim]Work #{rest[0]} 第 {rest[1]} 项已勾选。[/dim]")
            else:
                console.print(f"[yellow]找不到对应的检查项。[/yellow]")

        case "uncheck":
            if len(rest) < 2 or not rest[0].isdigit() or not rest[1].isdigit():
                console.print("[yellow]用法：/work uncheck <ID> <检查项序号>[/yellow]")
                return
            if check_item(int(rest[0]), int(rest[1]), done=False):
                console.print(f"[dim]Work #{rest[0]} 第 {rest[1]} 项已取消勾选。[/dim]")
            else:
                console.print(f"[yellow]找不到对应的检查项。[/yellow]")

        case "start":
            if not rest or not rest[0].isdigit():
                console.print("[yellow]用法：/work start <ID>[/yellow]")
                return
            if update_status(int(rest[0]), "in_progress"):
                console.print(f"[dim]Work #{rest[0]} 已开始。[/dim]")
            else:
                console.print(f"[yellow]找不到 Work #{rest[0]}。[/yellow]")

        case "done":
            if not rest or not rest[0].isdigit():
                console.print("[yellow]用法：/work done <ID>[/yellow]")
                return
            if update_status(int(rest[0]), "done"):
                console.print(f"[green]Work #{rest[0]} 已完成。[/green]")
            else:
                console.print(f"[yellow]找不到 Work #{rest[0]}。[/yellow]")

        case "cancel":
            if not rest or not rest[0].isdigit():
                console.print("[yellow]用法：/work cancel <ID>[/yellow]")
                return
            if update_status(int(rest[0]), "cancelled"):
                console.print(f"[dim]Work #{rest[0]} 已取消。[/dim]")
            else:
                console.print(f"[yellow]找不到 Work #{rest[0]}。[/yellow]")

        case "delete" | "rm":
            if not rest or not rest[0].isdigit():
                console.print("[yellow]用法：/work delete <ID>[/yellow]")
                return
            if work_delete(int(rest[0])):
                console.print(f"[dim]Work #{rest[0]} 已删除。[/dim]")
            else:
                console.print(f"[yellow]找不到 Work #{rest[0]}。[/yellow]")

        case "run":
            if not rest or not rest[0].isdigit():
                console.print("[yellow]用法：/work run <ID>[/yellow]")
                return
            if not skills or not cfg:
                console.print("[yellow]无法执行：skills/cfg 未传入。[/yellow]")
                return
            from core.subtask_runner import run_work_subtasks
            run_work_subtasks(int(rest[0]), skills, cfg, console)

        case _:
            console.print("[dim]子命令：new · list · view · add · check · uncheck · start · done · cancel · run · all[/dim]")

def _handle_subtask(parts: list[str], skills: dict | None = None, cfg: dict | None = None):
    """子代理任务管理：add / list / view / run / cancel / delete。"""
    from memory.subtask import (
        create as st_create, get as st_get, list_for_work, list_pending as st_pending,
        cancel as st_cancel, delete as st_delete, AGENT_TYPES,
    )
    sub  = parts[1] if len(parts) > 1 else "list"
    rest = parts[2:]

    def _status_tag(s: str) -> str:
        return {
            "pending":   "[dim]待执行[/dim]",
            "running":   "[yellow]执行中[/yellow]",
            "done":      "[green]完成[/green]",
            "failed":    "[red]失败[/red]",
            "cancelled": "[dim]已取消[/dim]",
        }.get(s, s)

    match sub:
        case "add":
            # /subtask add <work_id> <agent_type> [--fast] "prompt"
            if len(rest) < 3 or not rest[0].isdigit():
                console.print("[yellow]用法：/subtask add <work_id> <explore|plan|work|review> [--fast] \"任务提示\"[/yellow]")
                return
            work_id    = int(rest[0])
            agent_type = rest[1] if rest[1] in AGENT_TYPES else "work"
            tier_flag  = "--fast" in rest
            model_tier = "fast" if tier_flag else "default"
            prompt_parts = [r for r in rest[2:] if r != "--fast"]
            prompt = " ".join(prompt_parts).strip('"').strip("'")
            if not prompt:
                console.print("[yellow]任务提示不能为空。[/yellow]")
                return
            tid = st_create(prompt, agent_type=agent_type, model_tier=model_tier, work_item_id=work_id)
            console.print(f"[green]已创建子任务 #{tid}（{agent_type} / {model_tier}）→ Work #{work_id}[/green]")

        case "list":
            work_id_filter = int(rest[0]) if rest and rest[0].isdigit() else None
            if work_id_filter:
                tasks = list_for_work(work_id_filter)
            else:
                tasks = st_pending()
            if not tasks:
                console.print("[dim]没有子任务。用 /subtask add <work_id> <type> \"提示\" 创建。[/dim]")
                return
            t = Table(show_header=True, header_style="bold cyan", box=None)
            t.add_column("ID",     style="dim", width=4)
            t.add_column("Work",   style="dim", width=5)
            t.add_column("类型",   width=8)
            t.add_column("模型",   width=8)
            t.add_column("状态",   width=8)
            t.add_column("提示",)
            for tk in tasks:
                preview = (tk.get("prompt") or "")[:50]
                t.add_row(
                    str(tk["id"]),
                    str(tk.get("work_item_id") or "—"),
                    tk.get("agent_type", ""),
                    tk.get("model_tier", ""),
                    _status_tag(tk.get("status", "")),
                    preview,
                )
            console.print(t)

        case "view":
            if not rest or not rest[0].isdigit():
                console.print("[yellow]用法：/subtask view <ID>[/yellow]")
                return
            st = st_get(int(rest[0]))
            if not st:
                console.print(f"[yellow]找不到子任务 #{rest[0]}。[/yellow]")
                return
            console.print(f"\n[bold]子任务 #{st['id']}[/bold]  [{st['agent_type']} / {st['model_tier']}]")
            console.print(f"Work: #{st.get('work_item_id') or '—'}  状态: {_status_tag(st['status'])}")
            console.print(f"\n提示：\n{st['prompt']}")
            if st.get("result"):
                preview = st["result"][:300]
                console.print(f"\n结果：\n{preview}{'…' if len(st['result']) > 300 else ''}")
            if st.get("error_msg"):
                console.print(f"\n[red]错误：{st['error_msg']}[/red]")
            console.print()

        case "run":
            if not rest or not rest[0].isdigit():
                console.print("[yellow]用法：/subtask run <subtask_id>[/yellow]")
                return
            if not skills or not cfg:
                console.print("[yellow]无法执行：需要在主 REPL 中调用。[/yellow]")
                return
            from core.subtask_runner import run_subtask
            st = st_get(int(rest[0]))
            if not st:
                console.print(f"[yellow]找不到子任务 #{rest[0]}。[/yellow]")
                return
            result = run_subtask(int(rest[0]), skills, cfg, console)
            if result:
                preview = result[:200]
                console.print(f"\n[dim]结果摘要：{preview}{'…' if len(result) > 200 else ''}[/dim]")

        case "steer":
            # /subtask steer <work_id> "补充指令"
            if len(rest) < 2 or not rest[0].isdigit():
                console.print("[yellow]用法：/subtask steer <work_id> \"补充指令\"[/yellow]")
                return
            from core.subtask_runner import steer as st_steer
            work_id = int(rest[0])
            msg     = " ".join(rest[1:]).strip('"').strip("'")
            if not msg:
                console.print("[yellow]指令不能为空。[/yellow]")
                return
            st_steer(work_id, msg)
            console.print(f"[dim]已向 Work #{work_id} 的待执行子任务注入补充指令。[/dim]")

        case "cancel":
            if not rest or not rest[0].isdigit():
                console.print("[yellow]用法：/subtask cancel <ID>[/yellow]")
                return
            if st_cancel(int(rest[0])):
                console.print(f"[dim]子任务 #{rest[0]} 已取消。[/dim]")
            else:
                console.print(f"[yellow]子任务 #{rest[0]} 不在 pending 状态，无法取消。[/yellow]")

        case "delete" | "rm":
            if not rest or not rest[0].isdigit():
                console.print("[yellow]用法：/subtask delete <ID>[/yellow]")
                return
            if st_delete(int(rest[0])):
                console.print(f"[dim]子任务 #{rest[0]} 已删除。[/dim]")
            else:
                console.print(f"[yellow]找不到子任务 #{rest[0]}。[/yellow]")

        case _:
            console.print("[dim]子命令：add · list [work_id] · view · run · steer · cancel · delete[/dim]")


# ── 命令注册 ──────────────────────────────────────────────────────────────────

def _cmd_project(ctx):
    _handle_project(ctx['parts'])


def _cmd_work(ctx):
    _handle_work(ctx['parts'], skills=ctx['skills'], cfg=ctx['cfg'])


def _cmd_subtask(ctx):
    _handle_subtask(ctx['parts'], skills=ctx['skills'], cfg=ctx['cfg'])


register("/project", _cmd_project, "列出/切换/归档项目")
register("/work", _cmd_work, "任务管理")
register("/subtask", _cmd_subtask, "子代理任务管理")
