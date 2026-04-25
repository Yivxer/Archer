"""
多行终端输入封装。

快捷键：
  Enter          → 换行
  Alt+Enter      → 发送（macOS: Option+Enter）
  Ctrl+C / D     → 退出
  Tab            → /命令 自动补全
  ↑ / ↓          → 历史导航
  Ctrl+A / E     → 行首 / 行尾
"""
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import Completer, Completion

HISTORY_FILE = Path.home() / ".archer_history"

_STYLE = Style.from_dict({
    "prompt":        "ansigreen bold",
    "continuation":  "ansigray",
    "completion-menu.completion":         "bg:#1e1e1e #aaaaaa",
    "completion-menu.completion.current": "bg:#005f87 #ffffff bold",
})

# 所有可补全的 / 命令，格式：(命令, 说明)
_COMMANDS = [
    ("/help",                 "查看所有命令"),
    ("/status",               "查看当前状态（记忆数 / 技能数 / 历史轮数）"),
    ("/save",                 "保存当前会话"),
    ("/clear",                "清空对话历史"),
    ("/compact",              "手动压缩对话历史"),
    ("/exit",                 "退出并保存"),
    ("/memory list",          "列出所有记忆"),
    ("/memory search ",       "搜索记忆：/memory search <关键词>"),
    ("/memory add ",          "手动添加记忆：/memory add <内容>"),
    ("/memory delete ",       "删除记忆：/memory delete <ID>"),
    ("/skill list",           "列出已安装技能"),
    ("/skill info ",          "技能详情：/skill info <名字>"),
    ("/skill install ",       "安装技能：/skill install <路径或URL>"),
    ("/skill remove ",        "卸载技能：/skill remove <名字>"),
]

class _SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for cmd, desc in _COMMANDS:
            if cmd.startswith(text):
                yield Completion(
                    cmd[len(text):],   # 只补全剩余部分
                    display=cmd.strip(),
                    display_meta=desc,
                )

def _build_session() -> PromptSession:
    kb = KeyBindings()

    @kb.add("escape", "enter")   # Alt/Option+Enter → 提交
    def _submit(event):
        event.current_buffer.validate_and_handle()

    return PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        key_bindings=kb,
        multiline=True,
        style=_STYLE,
        completer=_SlashCompleter(),
        complete_while_typing=True,
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
