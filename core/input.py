"""
多行终端输入封装。

快捷键：
  Enter          → 发送
  Alt+Enter      → 换行（macOS: Option+Enter）
  Ctrl+C / D     → 退出
  Tab            → /命令 自动补全
  ↑ / ↓          → 历史导航
  Ctrl+A / E     → 行首 / 行尾
"""
import math
import shutil
from pathlib import Path
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.layout import Float, FloatContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.containers import VerticalAlign
from prompt_toolkit.layout.controls import BufferControl, DummyControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

HISTORY_FILE = Path.home() / ".archer_history"

_STYLE = Style.from_dict({
    "prompt":                                    "#7ec8a4 bold",
    "continuation":                              "#555555",
    "completion-menu":                           "bg:default",
    "completion-menu.completion":                "bg:default #c49060",
    "completion-menu.completion.current":        "bg:default bold #c44e00",
    "completion-menu.meta":                      "bg:default",
    "completion-menu.meta.completion":           "bg:default #888888",
    "completion-menu.meta.completion.current":   "bg:default #c44e00",
    "input-rule":                                "#444444",
    "input-prompt":                              "#7ec8a4 bold",
    "input-status":                              "#444444",
    "input-model":                               "#c44e00 bold",
})

_COMMANDS = [
    ("/help",                 "查看所有命令"),
    ("/status",               "查看当前状态"),
    ("/model",                "查看 / 切换模型：/model <模型名>"),
    ("/mode mirror",          "切换：镜面模式（只提问，不建议）"),
    ("/mode coach",           "切换：教练模式（推动行动）"),
    ("/mode critic",          "切换：挑战模式（挑战假设）"),
    ("/mode operator",        "切换：执行模式（直接做）"),
    ("/reflect",              "复盘最近对话"),
    ("/sessions",             "查看最近 7 天会话统计"),
    ("/themes",               "查看行为主题列表"),
    ("/themes detect",        "从记忆库归纳行为模式"),
    ("/save",                 "保存当前会话"),
    ("/clear",                "清空对话历史"),
    ("/compact",              "手动压缩对话历史"),
    ("/exit",                 "退出并保存"),
    ("/memory list",          "列出所有记忆"),
    ("/memory search ",       "搜索记忆：/memory search <关键词>"),
    ("/memory add ",          "手动添加记忆：/memory add <内容>"),
    ("/memory pending",       "查看待确认记忆"),
    ("/memory accept all",     "确认写入全部待确认记忆"),
    ("/memory reject all",     "丢弃全部待确认记忆"),
    ("/memory update ",       "更新记忆：/memory update <ID> <新内容>"),
    ("/memory archive ",      "归档记忆：/memory archive <ID>"),
    ("/memory delete ",       "删除记忆：/memory delete <ID>"),
    ("/memory review",        "体检记忆库"),
    ("/skill list",           "列出已安装技能"),
    ("/skill info ",          "技能详情：/skill info <名字>"),
    ("/skill install ",       "安装技能：/skill install <路径或URL>"),
    ("/skill remove ",        "卸载技能：/skill remove <名字>"),
]

_INPUT_RULE_CHAR = "─"


class _SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for cmd, desc in _COMMANDS:
            if cmd.startswith(text):
                yield Completion(
                    cmd[len(text):],
                    display=cmd.strip(),
                    display_meta=desc,
                )


def _prompt_app(model: str = "", mode: str = "", usage: str = "") -> str:
    status_parts = []
    if model:
        status_parts.append(("class:input-model", model))
    if usage:
        if status_parts:
            status_parts.append(("class:input-model", " · "))
        status_parts.append(("class:input-model", usage))
    if mode:
        if status_parts:
            status_parts.append(("class:input-model", " · "))
        status_parts.extend([
            ("class:input-model", "/mode 切换 · "),
            ("class:input-model", mode),
        ])

    kb = KeyBindings()
    buffer = Buffer(
        history=FileHistory(str(HISTORY_FILE)),
        completer=_SlashCompleter(),
        complete_while_typing=True,
        multiline=True,
    )
    app: Application | None = None

    def _terminal_width() -> int:
        return max(20, shutil.get_terminal_size((80, 24)).columns)

    @kb.add("enter")
    def _submit(event):
        event.app.exit(result=buffer.text)

    @kb.add("escape", "enter")
    def _newline(event):
        buffer.insert_text("\n")

    @kb.add("c-c")
    def _interrupt(event):
        event.app.exit(exception=KeyboardInterrupt)

    @kb.add("c-d")
    def _eof(event):
        event.app.exit(exception=EOFError)

    def _input_height() -> int:
        width = max(1, _terminal_width() - 2)
        lines = buffer.text.split("\n") or [""]
        visual_lines = 0
        for line in lines:
            visual_lines += max(1, math.ceil(get_cwidth(line) / width))
        return max(1, visual_lines)

    def _is_command_input() -> bool:
        return buffer.text.lstrip().startswith("/")

    def _input_dimension() -> Dimension:
        return Dimension.exact(_input_height())

    def _root_dimension() -> Dimension:
        extra = 10 if _is_command_input() else 3
        return Dimension.exact(_input_height() + extra)

    def _root_width() -> Dimension:
        return Dimension.exact(_terminal_width())

    def _buffer_width() -> Dimension:
        return Dimension.exact(max(1, _terminal_width() - 2))

    def _status_height() -> Dimension:
        return Dimension.exact(0 if _is_command_input() else 1)

    def _invalidate(_buffer) -> None:
        if app is not None:
            app.invalidate()

    buffer.on_text_changed += _invalidate

    top_rule = Window(
        DummyControl(),
        char=_INPUT_RULE_CHAR,
        style="class:input-rule",
        height=Dimension.exact(1),
        width=_root_width,
        dont_extend_height=True,
    )
    buffer_control = BufferControl(buffer=buffer)
    input_row = VSplit([
        Window(
            FormattedTextControl(FormattedText([("class:input-prompt", "❯ ")])),
            width=2,
            height=_input_dimension,
            dont_extend_height=True,
            dont_extend_width=True,
        ),
        Window(
            buffer_control,
            height=_input_dimension,
            width=_buffer_width,
            dont_extend_height=True,
            dont_extend_width=True,
            wrap_lines=True,
        ),
    ], height=_input_dimension, width=_root_width)
    lower_rule = Window(
        DummyControl(),
        char=_INPUT_RULE_CHAR,
        style="class:input-rule",
        height=Dimension.exact(1),
        width=_root_width,
        dont_extend_height=True,
    )
    status_line = Window(
        FormattedTextControl(lambda: FormattedText([] if _is_command_input() else status_parts)),
        height=_status_height,
        width=_root_width,
        dont_extend_height=True,
        dont_extend_width=True,
    )
    completions = CompletionsMenu(max_height=8, scroll_offset=1)

    root = FloatContainer(
        content=HSplit(
            [top_rule, input_row, lower_rule, status_line, completions],
            height=_root_dimension,
            width=_root_width,
            align=VerticalAlign.TOP,
        ),
        floats=[],
    )

    app = Application(
        layout=Layout(root, focused_element=buffer_control),
        key_bindings=kb,
        style=_STYLE,
        full_screen=False,
        erase_when_done=False,
    )
    return app.run().strip()


def prompt(model: str = "", mode: str = "", usage: str = "") -> str:
    """
    显示输入框，返回用户输入的字符串（已 strip）。
    退出时抛出 KeyboardInterrupt 或 EOFError。
    """
    return _prompt_app(model=model, mode=mode, usage=usage)
