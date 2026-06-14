"""Scheduled task commands (/schedule list|add|remove|…)."""
from __future__ import annotations

from .registry import register
from .system import _handle_cron


def _cmd_schedule(ctx):
    _handle_cron(ctx["parts"], ctx["skills"])


register("/schedule", _cmd_schedule, "定时任务管理")
