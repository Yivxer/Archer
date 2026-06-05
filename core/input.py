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
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.layout import Float, FloatContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.containers import VerticalAlign
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

HISTORY_FILE = Path.home() / ".archer_history"

_STYLE = Style.from_dict({
    "prompt":                                    "#4dd9d4 bold",
    "continuation":                              "#555555",
    "completion-menu":                           "bg:default",
    "completion-menu.completion":                "bg:default #888888",
    "completion-menu.completion.current":        "bg:default bold #4dd9d4",
    "completion-menu.meta":                      "bg:default",
    "completion-menu.meta.completion":           "bg:default #666666",
    "completion-menu.meta.completion.current":   "bg:default #888888",
    "input-rule":                                "#2a3a48",
    "input-prompt":                              "#4dd9d4 bold",
    "input-status":                              "#4a5a68",
    # 状态栏：仅 dim，>80% token 时加粗提示
    "input-model":                               "#6a7a88",
    "input-tokens":                              "#4a5a68",
    "input-mode":                                "#5a6a78",
    "input-sep":                                 "#2a3a48",
})

_COMMANDS = [
    ("/help",                 "查看所有命令"),
    ("/status",               "查看当前状态"),
    ("/dash",                 "仪表盘：上下文用量 / 记忆分布 / 项目概览"),
    ("/model",                "查看 / 切换模型：/model <模型名>"),
    ("/mode mirror",          "切换：镜面模式（只提问，不建议）"),
    ("/mode coach",           "切换：教练模式（推动行动）"),
    ("/mode critic",          "切换：挑战模式（挑战假设）"),
    ("/mode operator",        "切换：执行模式（直接做）"),
    ("/reflect",              "复盘最近对话"),
    ("/sessions",             "查看最近 7 天会话统计 + 每日柱状图"),
    ("/sessions search ",     "搜索历史会话：/sessions search <关键词>"),
    ("/themes",               "查看行为主题列表"),
    ("/themes detect",        "从记忆库归纳行为模式"),
    ("/project",              "列出所有项目"),
    ("/project new ",         "创建项目：/project new <名称> [描述]"),
    ("/project use ",         "切换活跃项目：/project use <ID|名>"),
    ("/project log ",         "记录项目事件：/project log <ID|名> <内容>"),
    ("/project status ",      "查看项目详情：/project status <ID|名>"),
    ("/project archive ",     "归档项目：/project archive <ID|名>"),
    ("/soul",                 "查看 SOUL 演化提议"),
    ("/soul accept all",      "接受所有提议并追加写入 SOUL.md"),
    ("/soul reject all",      "丢弃所有提议"),
    ("/soul view",            "查看 SOUL.md 最近演化记录"),
    ("/listen",               "进入静默录入模式（输入不发送给 AI）"),
    ("/listen stop",          "退出静默录入模式"),
    ("/save",                 "保存当前会话"),
    ("/clear",                "清空对话历史"),
    ("/compact",              "手动压缩对话历史"),
    ("/exit",                 "退出并保存"),
    ("/memory list",          "列出所有记忆"),
    ("/memory search ",       "搜索记忆：/memory search <关键词>"),
    ("/memory add ",          "手动添加记忆：/memory add <内容>"),
    ("/memory pending",       "查看待确认记忆"),
    ("/memory pending review", "交互审阅待确认记忆"),
    ("/memory accept all",     "确认写入全部待确认记忆"),
    ("/memory reject all",     "丢弃全部待确认记忆"),
    ("/memory update ",       "更新记忆：/memory update <ID> <新内容>"),
    ("/memory archive ",      "归档记忆：/memory archive <ID>"),
    ("/memory delete ",       "删除记忆：/memory delete <ID>"),
    ("/memory review",        "体检记忆库"),
    ("/memory extract",       "立即提炼当前会话记忆"),
    ("/memory export",        "导出全部记忆：/memory export [路径]"),
    ("/skill list",           "列出已安装技能"),
    ("/skill info ",          "技能详情：/skill info <名字>"),
    ("/skill install ",       "安装技能：/skill install <路径或URL>"),
    ("/skill remove ",        "卸载技能：/skill remove <名字>"),
    ("/skill suggest",        "分析技能缺口，--apply 写入路由规则"),
    ("/work list",            "查看进行中的任务"),
    ("/work new ",            "创建任务：/work new \"标题\""),
    ("/work view ",           "查看任务：/work view <ID>"),
    ("/work start ",          "开始任务：/work start <ID>"),
    ("/work done ",           "完成任务：/work done <ID>"),
    ("/work cancel ",         "取消任务：/work cancel <ID>"),
    ("/work add ",            "添加检查项：/work add <ID> \"内容\""),
    ("/work run ",            "执行子代理：/work run <ID>"),
    ("/cron list",            "查看定时任务"),
    ("/cron add ",            "添加定时任务：/cron add <技能> <间隔>"),
    ("/cron remove ",         "删除定时任务：/cron remove <ID>"),
    ("/cron run ",            "立即执行：/cron run <ID>"),
    ("/doctor",               "自检系统状态"),
    ("/doctor --fix",         "自检并自动修复可修复问题"),
    ("/critique scan",        "扫描生成自我批评诊断"),
    ("/critique list",        "查看批评条目"),
    ("/covenant view",        "查看根契约"),
    ("/presence view",        "查看在场方式"),
    ("/insight list",         "查看正向洞察记录"),
    ("/insight search ",      "搜索洞察：/insight search <词>"),
    ("/login",                "邮箱 Magic Link 登录"),
    ("/workflow",             "查看所有工作流"),
    ("/workflow voice ",      "语音转日记：/workflow voice <音频路径>"),
    ("/workflow url ",        "链接转阅读笔记：/workflow url <URL> [关键词]"),
    ("/workflow digest",      "生成周摘要：/workflow digest [天数]"),
    ("/workflow briefing ",   "项目简报：/workflow briefing [项目名]"),
    ("/copy",                 "复制上一条 Archer 回复到剪贴板"),
]

_COMPLETION_MAX_HEIGHT = 8


class _SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        # 优先从 CommandRegistry 动态获取命令 + 描述
        try:
            from terminal.commands.registry import _registry
            for cmd in _registry.commands():
                if cmd.startswith(text):
                    desc = _registry._descriptions.get(cmd, "")
                    yield Completion(
                        cmd[len(text):],
                        display=cmd,
                        display_meta=desc,
                    )
        except Exception:
            pass
        # 补充静态列表中的子命令补全（如 /memory list, /soul accept all 等）
        for cmd, desc in _COMMANDS:
            if cmd.startswith(text) and " " in cmd:
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
        status_parts.append(("class:input-sep", "  ·  "))
        status_parts.append(("class:input-tokens", usage))
    if mode:
        status_parts.append(("class:input-sep", "  ·  "))
        status_parts.append(("class:input-mode", mode))

    # ── 粘贴压缩 ──────────────────────────────────────────────────────────
    _collapsed_text: str | None = None  # 完整文本（折叠时）
    _collapsed_lines: int = 0
    _MAX_VISIBLE = 4

    def _set_buffer_completer(completer: Completer | None) -> None:
        """prompt_toolkit Buffer 没有 set_completer；直接更新 completer 属性。"""
        buffer.completer = completer

    def _collapsed_preview(line_count: int) -> str:
        return f"[··· 已折叠 {line_count} 行长文本 · 回车发送 · Ctrl+E 展开 · Esc 清空 ···]"

    def _compress_buffer():
        """如果文本超过 _MAX_VISIBLE 行，折叠为单行提示。"""
        nonlocal _collapsed_text, _collapsed_lines
        text = buffer.text
        lines = text.split("\n")
        if len(lines) <= _MAX_VISIBLE:
            _collapsed_text = None
            _collapsed_lines = 0
            return
        # 保存完整文本
        _collapsed_text = text
        _collapsed_lines = len(lines)
        # 替换为单行折叠提示（不显示正文片段）
        _set_buffer_completer(None)  # 压缩后不需要补全
        buffer.reset()
        buffer.insert_text(_collapsed_preview(len(lines)))

    kb = KeyBindings()
    buffer = Buffer(
        history=FileHistory(str(HISTORY_FILE)),
        completer=_SlashCompleter(),
        complete_while_typing=Condition(lambda: buffer.text.lstrip().startswith("/")),
        multiline=True,
    )
    app: Application | None = None

    def _terminal_width() -> int:
        return max(20, shutil.get_terminal_size((80, 24)).columns)

    @kb.add("tab")
    def _complete_or_indent(event):
        if buffer.text.lstrip().startswith("/"):
            buffer.start_completion(select_first=False)

    @kb.add("enter")
    def _submit(event):
        nonlocal _collapsed_text
        if _collapsed_text:
            event.app.exit(result=_collapsed_text)
        else:
            event.app.exit(result=buffer.text)

    @kb.add("escape", "enter")
    def _newline(event):
        if _collapsed_text:
            return  # 折叠状态下忽略换行
        buffer.insert_text("\n")

    @kb.add("c-e")
    def _toggle_expand(event):
        """展开/折叠切换。"""
        nonlocal _collapsed_text, _collapsed_lines
        if _collapsed_text:
            # 展开
            text = _collapsed_text
            _collapsed_text = None
            _set_buffer_completer(_SlashCompleter())
            buffer.reset()
            buffer.insert_text(text)
        elif buffer.text:
            # 检查是否需要折叠
            lines = buffer.text.split("\n")
            if len(lines) > _MAX_VISIBLE:
                _collapsed_text = buffer.text
                _collapsed_lines = len(lines)
                _set_buffer_completer(None)
                buffer.reset()
                buffer.insert_text(_collapsed_preview(len(lines)))
        if app:
            app.invalidate()

    @kb.add("c-k")
    def _kill_to_end(event):
        end_pos = buffer.document.get_end_of_line_position()
        if end_pos == 0 and buffer.cursor_position < len(buffer.text):
            buffer.delete(1)          # 行尾且后面还有内容：删换行符，合并下一行
        else:
            buffer.delete(end_pos)    # 删到行尾

    @kb.add("c-u")
    def _kill_to_start(event):
        buffer.delete_before_cursor(count=buffer.document.cursor_position_col)

    @kb.add("escape")
    def _escape_or_clear(event):
        nonlocal _collapsed_text
        if buffer.complete_state:
            buffer.cancel_completion()
        elif _collapsed_text:
            _collapsed_text = None
            _set_buffer_completer(_SlashCompleter())
            buffer.reset()
            if app:
                app.invalidate()
        else:
            buffer.reset()            # 清空输入框

    @kb.add("c-c")
    def _interrupt(event):
        event.app.exit(exception=KeyboardInterrupt)

    @kb.add("c-d")
    def _eof(event):
        event.app.exit(exception=EOFError)

    def _input_height() -> int:
        width = max(1, _terminal_width() - 2)  # 2 = "❯ " prefix
        lines = buffer.text.split("\n") or [""]
        visual_lines = 0
        for line in lines:
            visual_lines += max(1, math.ceil(get_cwidth(line) / width))
        return max(1, visual_lines)

    def _is_command_input() -> bool:
        return buffer.text.lstrip().startswith("/")

    def _input_dimension() -> Dimension:
        h = _input_height()
        return Dimension(min=h, preferred=h)

    def _root_dimension() -> Dimension:
        h = _input_height()
        completion_state = buffer.complete_state
        completion_rows = 0
        if _is_command_input() and completion_state:
            completion_rows = min(_COMPLETION_MAX_HEIGHT, len(completion_state.completions))
        status_rows = 0 if _is_command_input() else 1
        sep_rows = 0 if _is_command_input() else 1
        total = h + sep_rows + status_rows + completion_rows
        return Dimension(min=h + sep_rows + status_rows, preferred=total)

    def _status_height() -> Dimension:
        return Dimension.exact(0 if _is_command_input() else 1)

    def _invalidate(_buffer) -> None:
        if app is not None:
            app.invalidate()

    buffer.on_text_changed += _invalidate

    # 自动检测粘贴：文本突变 → 自动折叠
    _compressing = False
    def _auto_compress(_buffer):
        nonlocal _collapsed_text, _collapsed_lines, _compressing
        if _compressing:
            return
        text = buffer.text
        lines = text.split("\n")
        if not _collapsed_text and len(lines) > _MAX_VISIBLE:
            _compressing = True
            try:
                _collapsed_text = text
                _collapsed_lines = len(lines)
                _set_buffer_completer(None)
                buffer.reset()
                buffer.insert_text(_collapsed_preview(len(lines)))
            finally:
                _compressing = False
            if app:
                app.invalidate()
    buffer.on_text_changed += _auto_compress

    buffer_control = BufferControl(buffer=buffer)
    status_line = Window(
        FormattedTextControl(lambda: FormattedText([] if _is_command_input() else status_parts)),
        height=_status_height,
        dont_extend_height=True,
        dont_extend_width=True,
    )
    input_row = VSplit([
        Window(
            FormattedTextControl(FormattedText([("class:input-prompt", "❯ ")])),
            width=2,
            dont_extend_height=True,
            dont_extend_width=True,
        ),
        Window(
            buffer_control,
            dont_extend_height=True,
            wrap_lines=True,
        ),
    ], height=_input_dimension)
    completions = CompletionsMenu(max_height=_COMPLETION_MAX_HEIGHT, scroll_offset=1)

    # 分隔线：收窄对话区和输入区的视觉间隙
    separator = Window(
        FormattedTextControl(lambda: FormattedText([
            ("class:input-rule", "─" * _terminal_width())
        ])),
        height=Dimension.exact(0 if _is_command_input() else 1),
        dont_extend_height=True,
    )

    root = FloatContainer(
        content=HSplit(
            [separator, input_row, status_line],
            height=_root_dimension,
            align=VerticalAlign.TOP,
        ),
        floats=[
            Float(
                xcursor=True,
                ycursor=True,
                content=completions,
            )
        ],
    )

    app = Application(
        layout=Layout(root, focused_element=buffer_control),
        key_bindings=kb,
        style=_STYLE,
        cursor=CursorShape.BEAM,
        full_screen=False,
        erase_when_done=False,
    )
    return app.run().strip()


def confirm_select(options: list[tuple[str, str]]) -> str:
    """
    箭头键导航的三选确认菜单。
    options: [(return_value, display_label), ...]
    返回所选项的 return_value。
    Esc / Ctrl+C 返回最后一个选项（通常是"取消"）。
    """
    sel = [0]

    def _render() -> FormattedText:
        parts: list[tuple[str, str]] = [("", "\n")]
        for i, (_, label) in enumerate(options):
            if i == sel[0]:
                parts.append(("bold #f5612a", f"  ▶  {label}\n"))
            else:
                parts.append(("#4a5a68", f"     {label}\n"))
        parts.append(("", "\n"))
        parts.append(("#2a3a48", "  ↑↓ 移动   Enter 确认\n"))
        return FormattedText(parts)

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        sel[0] = (sel[0] - 1) % len(options)
        event.app.invalidate()

    @kb.add("down")
    def _down(event):
        sel[0] = (sel[0] + 1) % len(options)
        event.app.invalidate()

    @kb.add("enter")
    def _enter(event):
        event.app.exit(result=options[sel[0]][0])

    # 数字快捷键 1/2/3
    for _i in range(min(len(options), 9)):
        def _make_num(idx: int) -> None:
            @kb.add(str(idx + 1))
            def _num(event):
                event.app.exit(result=options[idx][0])
        _make_num(_i)

    def _cancel_key(event):
        for k, _ in options:
            if k == "q":
                event.app.exit(result="q")
                return
        event.app.exit(result=options[-1][0])

    kb.add("escape")(_cancel_key)
    kb.add("c-c")(_cancel_key)
    kb.add("c-d")(_cancel_key)

    control = FormattedTextControl(_render, focusable=True)
    win = Window(control, dont_extend_height=True)
    app = Application(
        layout=Layout(win),
        key_bindings=kb,
        full_screen=False,
        erase_when_done=False,
        style=_STYLE,
    )
    return app.run()


def prompt(model: str = "", mode: str = "", usage: str = "") -> str:
    """
    显示输入框，返回用户输入的字符串（已 strip）。
    退出时抛出 KeyboardInterrupt 或 EOFError。
    """
    return _prompt_app(model=model, mode=mode, usage=usage)
