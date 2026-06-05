"""会话管理命令。"""
from __future__ import annotations

from .registry import register
from core.compressor import compress


def _cmd_exit(ctx):
    session = ctx['session']
    if len(session.history) >= 2:
        ctx['console'].print("[dim]正在提炼本次会话记忆…[/dim]")
        auto_extract = ctx.get('_auto_extract')
        wait_for_extract = ctx.get('_wait_for_extract')
        if wait_for_extract:
            wait_for_extract()
        if auto_extract:
            auto_extract(session.history, silent=False)
    saved = session.save()
    ctx['console'].print(f"[dim]会话已保存 → {saved}[/dim]")
    ctx['state']['should_exit'] = True


def _cmd_save(ctx):
    saved = ctx['session'].save()
    ctx['console'].print(f"[dim]会话已保存 → {saved}[/dim]")


def _cmd_clear(ctx):
    ctx['session'].clear()
    ctx['console'].print("[dim]历史已清空。[/dim]")


def _cmd_compact(ctx):
    session = ctx['session']
    if len(session.history) < 2:
        ctx['console'].print("[dim]对话历史不足，无需压缩。[/dim]")
    else:
        ctx['console'].print("[dim]正在压缩…[/dim]")
        try:
            session.history = compress(session.history)
            ctx['console'].print(f"[dim]压缩完成，当前 {len(session.history)} 条消息。[/dim]")
        except Exception as e:
            ctx['console'].print(f"[red]压缩失败：{e}[/red]")


register("/exit", _cmd_exit, "退出并保存")
register("/save", _cmd_save, "保存当前会话")
register("/clear", _cmd_clear, "清空对话历史")
register("/compact", _cmd_compact, "手动压缩对话历史")
