"""
多行终端输入封装。

操作方式（对标 Claude Code）：
  Enter          → 换行
  Alt+Enter      → 发送（macOS: Option+Enter）
  Ctrl+C / D     → 退出
  ↑ / ↓          → 历史导航
  Ctrl+A / E     → 行首 / 行尾
"""
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

HISTORY_FILE = Path.home() / ".archer_history"

_STYLE = Style.from_dict({
    "prompt":        "ansigreen bold",
    "continuation":  "ansigray",
})

def _build_session() -> PromptSession:
    kb = KeyBindings()

    @kb.add("escape", "enter")   # Alt/Option+Enter → 提交
    def _submit(event):
        event.current_buffer.validate_and_handle()

    return PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        key_bindings=kb,
        multiline=True,          # Enter 换行，Alt+Enter 提交
        style=_STYLE,
        prompt_continuation=lambda width, line_number, is_soft_wrap: "  │ ",
    )

_session: PromptSession | None = None

def prompt() -> str:
    """
    显示输入框，返回用户输入的字符串（已 strip）。
    退出时抛出 KeyboardInterrupt 或 EOFError。
    """
    global _session
    if _session is None:
        _session = _build_session()

    text = _session.prompt(
        HTML("<ansigreen><b>你</b></ansigreen>\n❯ "),
    )
    return text.strip()
