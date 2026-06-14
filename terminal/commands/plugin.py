"""Plugin bundle commands (/plugin install|list|remove)."""
from __future__ import annotations

from rich.console import Console
from rich.table import Table

from skills.installer import install_plugin_bundle, list_plugins, remove_plugin_bundle

from .registry import register

console = Console()


def _handle_plugin(parts: list[str]) -> None:
    sub = parts[1] if len(parts) > 1 else ""
    arg = " ".join(parts[2:]).strip()
    force = "--force" in parts

    if sub == "install":
        source = arg.replace("--force", "").strip()
        if not source:
            console.print("[yellow]用法：/plugin install <插件目录路径> [--force][/yellow]")
            return
        try:
            record = install_plugin_bundle(source, force=force)
            console.print(
                f"[green]插件「{record['name']}」v{record['version']} 安装成功"
                f"（skills={record.get('skill_count', 0)}, modes={record.get('mode_count', 0)}）。[/green]"
            )
        except Exception as exc:
            console.print(f"[red]安装失败：{exc}[/red]")
        return

    if sub == "list":
        items = list_plugins()
        if not items:
            console.print("[dim]尚未安装任何插件。[/dim]")
            return
        table = Table(show_header=True, header_style="bold cyan", box=None)
        table.add_column("名称", style="cyan")
        table.add_column("版本", width=10)
        table.add_column("skills", width=8)
        table.add_column("modes", width=8)
        table.add_column("描述")
        for item in items:
            table.add_row(
                str(item.get("name", "")),
                str(item.get("version", "")),
                str(item.get("skill_count", 0)),
                str(item.get("mode_count", 0)),
                str(item.get("description", "")),
            )
        console.print(table)
        return

    if sub == "remove":
        if not arg:
            console.print("[yellow]用法：/plugin remove <插件名>[/yellow]")
            return
        try:
            remove_plugin_bundle(arg)
            console.print(f"[dim]插件「{arg}」已卸载。[/dim]")
        except Exception as exc:
            console.print(f"[red]卸载失败：{exc}[/red]")
        return

    console.print("[dim]子命令：install · list · remove[/dim]")


def _cmd_plugin(ctx):
    _handle_plugin(ctx["parts"])


register("/plugin", _cmd_plugin, "安装/管理插件 bundle")
