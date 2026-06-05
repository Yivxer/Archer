"""工作流注册表与调度入口。"""
from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.panel import Panel


def _load() -> dict:
    from workflows import voice_to_journal, url_to_reading_note, weekly_digest, project_briefing
    mods = [voice_to_journal, url_to_reading_note, weekly_digest, project_briefing]
    return {m.WORKFLOW["name"]: m for m in mods}


_REGISTRY: dict | None = None


def registry() -> dict:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _load()
    return _REGISTRY


def _handle_crystal(args: list[str], console: Console) -> None:
    from memory.workflow_crystal import list_all, save, delete, get, increment_use
    sub = args[0] if args else "list"

    if sub == "list":
        wfs = list_all()
        if not wfs:
            console.print("[dim]暂无结晶工作流。完成多步任务后系统会提示保存。[/dim]")
            return
        t = Table(show_header=True, header_style="bold cyan", box=None)
        t.add_column("ID", style="dim", width=4)
        t.add_column("名称", style="cyan", width=18)
        t.add_column("关键词", width=20)
        t.add_column("步骤数", width=6)
        t.add_column("使用次数", width=8)
        for wf in wfs:
            t.add_row(str(wf["id"]), wf["name"], wf["keywords"],
                      str(len(wf["steps"])), str(wf["use_count"]))
        console.print(t)
        console.print("[dim]/workflow crystal view · run · delete <ID>[/dim]")

    elif sub == "search" and len(args) >= 2:
        from memory.workflow_crystal import search as wc_search
        wfs = wc_search(args[1])
        if not wfs:
            console.print(f"[yellow]未找到包含「{args[1]}」的工作流。[/yellow]")
            return
        t = Table(show_header=True, header_style="bold cyan", box=None)
        t.add_column("ID", style="dim", width=4)
        t.add_column("名称", style="cyan", width=18)
        t.add_column("关键词", width=20)
        t.add_column("步骤数", width=6)
        for wf in wfs:
            t.add_row(str(wf["id"]), wf["name"], wf["keywords"], str(len(wf["steps"])))
        console.print(t)

    elif sub == "save" and len(args) >= 2:
        # /workflow crystal save <名称> [关键词,逗号分隔]
        name = args[1].strip()
        keywords = args[2].strip() if len(args) > 2 else ""

        # 检查重复名称
        existing = list_all()
        duplicate = next((w for w in existing if w["name"] == name), None)
        if duplicate:
            console.print(f"[yellow]⚠️  已存在同名工作流「{name}」（ID {duplicate['id']}）。是否覆盖？[y/N][/yellow] ", end="")
            confirm = input().strip().lower()
            if confirm not in ("y", "yes", "是", "覆盖"):
                console.print("[dim]已取消。[/dim]")
                return
            # 删除旧的
            delete(duplicate["id"])
            console.print(f"[dim]已删除旧版本。[/dim]")

        console.print(f"[dim]名称：{name}  关键词：{keywords or '（未设置）'}[/dim]")
        console.print("[dim]请输入步骤（技能名 参数描述），空行结束。输入 help 查看格式说明。[/dim]")
        steps = []
        try:
            while True:
                console.print("[dim]步骤 → [/dim]", end="")
                line = input().strip()
                if not line:
                    break
                if line.lower() == "help":
                    console.print("[dim]  格式：技能名 参数描述")
                    console.print("  示例：browser_automation 打开 Google 首页")
                    console.print("  注意：技能名不能含空格[/dim]")
                    continue
                if line.lower() == "abort":
                    console.print("[yellow]  已中止输入。[/yellow]")
                    return
                parts_ = line.split(None, 1)
                skill_name = parts_[0]
                desc = parts_[1] if len(parts_) > 1 else ""
                # 格式校验：技能名不含空格
                if not skill_name:
                    console.print("[yellow]  技能名不能为空，此行已跳过。[/yellow]")
                    continue
                if " " in skill_name:
                    console.print("[yellow]  格式有误，技能名不能含空格。此行已跳过。[/yellow]")
                    continue
                steps.append({"skill": skill_name, "args": {"desc": desc}})
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]已取消输入。[/dim]")
            return

        if not steps:
            console.print("[yellow]没有输入步骤，已取消。[/yellow]")
            return

        # 保存前预览
        console.print("\n[bold]即将保存以下工作流：[/bold]")
        console.print(f"  名称：{name}")
        console.print(f"  关键词：{keywords or '（无）'}")
        console.print(f"  步骤数：{len(steps)}")
        for i, s in enumerate(steps, 1):
            desc_preview = s["args"].get("desc", "")[:40]
            console.print(f"  {i}. {s['skill']}  {desc_preview}")
        console.print("\n[dim]确认保存？[y/N][/dim] ", end="")
        confirm = input().strip().lower()
        if confirm not in ("y", "yes", "是", "确认"):
            console.print("[dim]已取消保存。[/dim]")
            return

        wid = save(name, steps, keywords)
        console.print(f"[green]✅ 已保存工作流「{name}」（ID {wid}，{len(steps)} 步）[/green]")

    elif sub == "view" and len(args) >= 2 and args[1].isdigit():
        wf = get(int(args[1]))
        if not wf:
            console.print(f"[yellow]未找到 ID={args[1]}[/yellow]")
            return
        # 格式化输出
        meta = f"[dim]#{wf['id']}  使用 {wf['use_count']} 次  创建于 {wf['created_at'][:10]}[/dim]"
        keywords_str = f"[cyan]关键词：{wf['keywords']}[/cyan]" if wf["keywords"] else "[dim]关键词：无[/dim]"

        steps_text = ""
        for i, s in enumerate(wf["steps"], 1):
            desc = s.get("args", {}).get("desc", "")
            steps_text += f"[cyan]{i:2}.[/cyan] [bold]{s['skill']}[/bold]"
            if desc:
                steps_text += f"  {desc}"
            steps_text += "\n"

        panel = Panel(
            steps_text.strip(),
            title=f"[bold]{wf['name']}[/bold]",
            subtitle=meta,
            border_style="cyan",
            padding=(1, 1),
        )
        console.print(panel)
        console.print(f"{keywords_str}  [dim]· 运行：/workflow crystal run {wf['id']}[/dim]")

    elif sub == "run" and len(args) >= 2 and args[1].isdigit():
        wf = get(int(args[1]))
        if not wf:
            console.print(f"[yellow]未找到 ID={args[1]}[/yellow]")
            return
        increment_use(wf["id"])
        console.print(f"\n[bold cyan]▶ 执行工作流「{wf['name']}」（{len(wf['steps'])} 步）[/bold cyan]\n")

        # 动态加载技能
        from skills.loader import load_skills
        skills = load_skills()

        for i, step in enumerate(wf["steps"], 1):
            skill_name = step["skill"]
            desc = step.get("args", {}).get("desc", "")
            console.print(f"[cyan]{i}/{len(wf['steps'])}[/cyan] [bold]{skill_name}[/bold] {desc}")

            skill_mod = skills.get(skill_name)
            if not skill_mod:
                console.print(f"[red]  ✗ 技能「{skill_name}」不存在，跳过。[/red]")
                continue

            try:
                result = skill_mod.run(desc, console)
                if result:
                    result_str = str(result)[:80]
                    console.print(f"[dim]  └ {result_str}[/dim]")
            except Exception as e:
                console.print(f"[red]  ✗ 执行失败：{e}[/red]")

        console.print(f"\n[green]✅ 工作流「{wf['name']}」执行完成[/green]")

    elif sub == "delete" and len(args) >= 2 and args[1].isdigit():
        wf = get(int(args[1]))
        if not wf:
            console.print(f"[yellow]未找到 ID={args[1]}[/yellow]")
            return
        console.print(f"[dim]确认删除「{wf['name']}」？[y/N][/dim] ", end="")
        confirm = input().strip().lower()
        if confirm not in ("y", "yes", "是", "删除"):
            console.print("[dim]已取消。[/dim]")
            return
        delete(int(args[1]))
        console.print(f"[dim]已删除工作流「{wf['name']}」。[/dim]")

    else:
        console.print("[dim]子命令：list · search <关键词> · save <名称> [关键词]")
        console.print("         view <ID> · run <ID> · delete <ID>[/dim]")


def handle_workflow(parts: list[str], console: Console, cfg: dict) -> None:
    reg = registry()
    sub = parts[1] if len(parts) > 1 else ""

    if not sub or sub in ("list", "ls", "help"):
        console.print("\n[bold cyan]工作流[/bold cyan]\n")
        for name, mod in reg.items():
            wf = mod.WORKFLOW
            console.print(f"  [cyan]{wf['usage']:<42}[/cyan]{wf['description']}")
        console.print()
        return

    if sub == "crystal":
        _handle_crystal(parts[2:], console)
        return

    mod = reg.get(sub)
    if not mod:
        console.print(f"[yellow]未知工作流：{sub}。输入 /workflow 查看可用列表。[/yellow]")
        return

    try:
        mod.run(parts[2:], console, cfg)
    except KeyboardInterrupt:
        console.print("\n[dim]已取消。[/dim]")
    except Exception as e:
        wf_name = mod.WORKFLOW.get("name", sub)
        console.print(f"[red]工作流「{wf_name}」执行失败：{e}[/red]")
        console.print("[dim]提示：可输入 `/workflow {sub} --help` 查看用法，或检查参数格式。[/dim]")
