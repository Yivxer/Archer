"""终端全局可变状态壳。"""
from __future__ import annotations
import threading


class State:
    """可变会话状态，在 run() 中实例化后传入各命令。"""
    def __init__(self):
        self.active_project_id: int | None = None
        self.current_session_id: str = ""
        self.last_response: str = ""
        self.listen_mode: bool = False
        self.turn_counter: int = 0
        self.mcp_last_used_turn: int = -999
        self.extract_thread: threading.Thread | None = None
        self.dsml_intercepted: bool = False


# 模块级单例（兼容旧代码逐步迁移）
_default: State | None = None


def get_state() -> State:
    global _default
    if _default is None:
        _default = State()
    return _default


def reset_state() -> State:
    global _default
    _default = State()
    return _default
