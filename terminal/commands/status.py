"""状态与帮助命令。"""
from __future__ import annotations

from .registry import register
from terminal.ui import _help, _status, _dash


def _cmd_help(ctx):
    _help(show_all=("--all" in ctx['parts']))


def _cmd_status(ctx):
    _status(ctx['session'], ctx['skills'], ctx['cfg'], active_project_id=ctx.get('active_project_id'))


def _cmd_dash(ctx):
    _dash(ctx['cfg'], ctx['session'], ctx['skills'], active_project_id=ctx.get('active_project_id'))


register("/help", _cmd_help, "查看命令帮助")
register("/status", _cmd_status, "查看当前状态")
register("/dash", _cmd_dash, "仪表盘概览")
