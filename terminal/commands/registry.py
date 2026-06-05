"""命令注册表。"""
from __future__ import annotations
from typing import Callable


class CommandRegistry:
    """命令注册、查找、执行、补全。"""

    def __init__(self):
        self._handlers: dict[str, Callable[[dict], None]] = {}
        self._descriptions: dict[str, str] = {}

    def register(self, name: str, handler: Callable, description: str = "") -> None:
        """注册命令。重复注册覆盖。"""
        self._handlers[name] = handler
        if description:
            self._descriptions[name] = description

    def dispatch(self, cmd: str, ctx: dict) -> bool:
        """查找并执行。返回 True = 已处理。"""
        handler = self._handlers.get(cmd)
        if handler:
            handler(ctx)
            return True
        return False

    def commands(self) -> list[str]:
        """所有已注册命令名（排序）。"""
        return sorted(self._handlers.keys())

    def completions(self, prefix: str = "") -> list[str]:
        """Tab 补全候选。"""
        if not prefix:
            return self.commands()
        return [c for c in self.commands() if c.startswith(prefix)]


_registry = CommandRegistry()


def register(name, handler, description=""):
    _registry.register(name, handler, description)


def dispatch(cmd, ctx):
    return _registry.dispatch(cmd, ctx)


def registered_commands():
    return _registry.commands()
