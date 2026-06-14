"""终端命令模块。"""
from .registry import register, dispatch, registered_commands
# 触发各子模块注册
from . import session, status, memory, skill, reflect, project, persona, system, plugin, schedule
