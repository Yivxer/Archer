import json
import random
from collections.abc import Callable

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from core.hooks import HookContext, run_hooks
from core.input import confirm_select
from core.llm import call_with_tools
from core.observability import trace_span
from core.policy import Decision, check as policy_check, check_subtask
from core.tool_runtime import invoke as runtime_invoke
from skills.loader import get_tools

def _brand_spinner(label: str = "思考中") -> Spinner:
    """返回带 Archer 品牌彩色名称的 spinner。"""
    t = Text()
    t.append("  ")
    # Archer ring glyph pair
    t.append("◜", style="#5ee8e0")
    t.append("◝", style="#1e7be8")
    t.append(" ")
    # Archer 彩色名称
    for ch, color in zip("Archer", ["#5ee8e0","#2aabf0","#1e7be8","#f5c842","#f5a030","#f5612a"]):
        t.append(ch, style=f"bold {color}")
    t.append(f"  {label}…", style="#4a5a68")
    return Spinner("dots", text=t, style="default")

try:
    from memory.skill_gap import record as _gap_record
except Exception:
    def _gap_record(*a, **kw): pass

try:
    from memory.workflow_crystal import save as _crystal_save
except Exception:
    def _crystal_save(*a, **kw): return 0


_MUTTER_OK = [
    "过了。", "嗯，好。", "一次就过，不错。", "这个简单。", "顺的。", "还行。",
]
_MUTTER_SLOW = [
    "慢了点。", "这次有点久。", "……算了，过了就行。",
]
_MUTTER_FAIL = [
    "出问题了。", "嗯……不对。", "又报错。", "怎么又是这个。",
]


def _maybe_mutter(console: Console, outcome: str, duration_ms: int = 0) -> None:
    if random.random() > 0.22:
        return
    if outcome == "ok":
        pool = _MUTTER_SLOW if duration_ms > 5000 else _MUTTER_OK
    else:
        pool = _MUTTER_FAIL
    console.print(f"[dim italic]  · {random.choice(pool)}[/dim italic]")


def _fmt_args(args: dict) -> str:
    """将工具参数格式化为简短的内联展示字符串。"""
    if not args:
        return ""
    items = []
    for k, v in list(args.items())[:3]:
        sv = str(v).replace("\n", "↵")
        if len(sv) > 48:
            sv = sv[:45] + "…"
        items.append(f"{k}={sv}")
    if len(args) > 3:
        items.append(f"+{len(args) - 3}")
    return "  " + "  ".join(items)


def run_with_tools(
    messages: list[dict],
    skills: dict,
    *,
    stream_fn: Callable[[list[dict], str], str],
    console: Console,
    model: str = "",
    max_rounds: int = 10,
    cfg: dict | None = None,
    session_id: str = "",
    user_input: str = "",
) -> str:
    if cfg:
        max_rounds = cfg.get("tools", {}).get("max_rounds", max_rounds)

    tools = get_tools(skills)
    messages = list(messages)
    _executed: list[dict] = []   # 记录本轮成功执行的步骤

    for _round_n in range(max_rounds):
        with Live(_brand_spinner("思考中"), refresh_per_second=20, transient=True, console=console):
            msg = call_with_tools(messages, tools, model=model)

        if not msg.tool_calls:
            # DeepSeek 有时在 function calling 上下文中输出裸 DSML 而非正式 tool_calls
            # 检测到后注入纠正消息，重试当前轮次，最多纠正 2 次
            if (msg.content or "").count("｜｜DSML｜｜") >= 2 and _round_n < max_rounds - 2:
                messages.append({
                    "role": "user",
                    "content": "请用 function calling 格式调用工具，不要输出原始 DSML 标记。",
                })
                continue
            break

        messages.append(msg)

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            console.print(f"[dim]→ {fn_name}{_fmt_args(fn_args)}[/dim]")

            pr = (
                check_subtask(fn_name, fn_args, skills, cfg=cfg)
                if cfg and cfg.get("subtask_mode")
                else policy_check(fn_name, fn_args, skills, cfg=cfg)
            )
            if fn_name not in skills:
                _gap_record(fn_name, "missing", session_id=session_id)

            if pr.decision == Decision.DENY:
                console.print(f"[red]  ✗ [策略拒绝] {pr.reason}[/red]")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"[策略拒绝] {pr.reason}",
                })
                continue

            if pr.decision == Decision.CONFIRM:
                # 中风险：黄色边框提示
                console.print(f"\n[#f5c842]  ⚠  中风险操作[/#f5c842]  [#4a5a68]{fn_name}[/#4a5a68]")
                console.print(f"  [#6a7a88]{pr.reason}[/#6a7a88]")
                answer = confirm_select([
                    ("y",  "确认执行"),
                    ("n",  "跳过此步"),
                    ("q",  "取消任务"),
                ])
                if answer == "q":
                    console.print("[dim]  任务已取消。[/dim]")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "[用户取消] 任务已终止",
                    })
                    break
                if answer != "y":
                    console.print("[dim]  已跳过此步。[/dim]")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "[用户跳过] 此步骤已跳过",
                    })
                    continue
            elif pr.decision == Decision.STRONG_CONFIRM:
                # 高风险：红色警告框
                console.print(f"\n[bold #e8212a]  🔴  高风险操作[/bold #e8212a]  [#4a5a68]{fn_name}[/#4a5a68]")
                console.print(f"  [#e8212a]{pr.reason}[/#e8212a]")
                console.print(f"  [dim]此操作可能不可撤销，请仔细确认。[/dim]")
                answer = confirm_select([
                    ("YES", "确认执行（高风险操作）"),
                    ("n",   "跳过此步"),
                    ("q",   "取消任务"),
                ])
                if answer == "q":
                    console.print("[dim]  任务已取消。[/dim]")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "[用户取消] 任务已终止",
                    })
                    break
                if answer != "YES":
                    console.print("[dim]  已跳过高风险操作。[/dim]")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "[用户跳过] 高风险操作已跳过",
                    })
                    continue

            hook_ctx = HookContext(
                event="PreToolUse",
                tool_name=fn_name,
                tool_args=dict(fn_args),
                session_id=session_id,
                metadata={"user_input": user_input},
            )
            pre_hook = run_hooks("PreToolUse", hook_ctx, cfg=cfg)
            if not pre_hook.continue_:
                console.print(f"[yellow]  ✗ [Hook] {pre_hook.message or 'blocked'}[/yellow]")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"[Hook 阻断] {pre_hook.message or 'blocked by hook'}",
                })
                continue
            if pre_hook.tool_args is not None:
                fn_args = pre_hook.tool_args

            with trace_span("tool.invoke", tool_name=fn_name) as span:
                tr = runtime_invoke(fn_name, fn_args, skills)
                span["ok"] = tr.ok
                if tr.meta.get("duration_ms") is not None:
                    span["tool_duration_ms"] = tr.meta["duration_ms"]
            if not tr.ok:
                console.print(f"[yellow]  ✗ {tr.summary}[/yellow]")
                _gap_record(fn_name, "failed", session_id=session_id)
                _executed.clear()   # 有失败则不结晶
                _maybe_mutter(console, "fail")
            else:
                _gap_record(fn_name, "success", session_id=session_id)
                _executed.append({"skill": fn_name, "args": fn_args})
                if tr.truncated:
                    console.print(f"[dim]  ↳ {tr.summary}[/dim]")
                _maybe_mutter(console, "ok", duration_ms=tr.meta.get("duration_ms", 0))

            post_hook = run_hooks(
                "PostToolUse",
                HookContext(
                    event="PostToolUse",
                    tool_name=fn_name,
                    tool_args=dict(fn_args),
                    tool_output=tr.to_message_content(),
                    session_id=session_id,
                    metadata={"ok": tr.ok},
                ),
                cfg=cfg,
            )
            if post_hook.errors and tr.ok:
                console.print(f"[dim]  hook warnings: {'; '.join(post_hook.errors)}[/dim]")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tr.to_message_content(),
            })
    else:
        console.print(f"\n[yellow]  ⚠  已调用 {max_rounds} 轮工具，任务仍未完成。[/yellow]")
        console.print("[dim]  建议：把需求说得更具体，或拆成更小的步骤再试。[/dim]\n")
        messages.append({
            "role": "user",
            "content": "工具调用已达上限，请直接用已获取的信息给出最终回答，不要再调用工具。",
        })

    # 多步成功链 → 提示可结晶
    if len(_executed) >= 2:
        skills_used = " → ".join(s["skill"] for s in _executed)
        console.print(f"[dim]多步工具链完成（{skills_used}）。用 /workflow crystal 保存为可复用工作流。[/dim]")

    # 注入最终回答提示，防止 DeepSeek 在工具调用上下文残留时输出 DSML
    if _executed:
        messages.append({
            "role": "user",
            "content": "请用自然语言给出最终回答，总结你已完成的操作和结果。不要调用工具，不要输出 XML 或 DSML 标记。",
        })

    final_stream = stream_fn(messages, model)

    # B1.1: 终端兜底 —— stream_fn 返回空文本时，打印兜底文案，避免用户看到"模型无回复"
    def _wrap_with_fallback(stream):
        has_content = False
        try:
            for chunk in stream:
                if chunk:
                    has_content = True
                yield chunk
        finally:
            if not has_content:
                fallback = "已执行操作，详见上方卡片。" if _executed else "模型没有返回内容，请重试或检查诊断。"
                console.print(f"[yellow]{fallback}[/yellow]")

    return _wrap_with_fallback(final_stream)
