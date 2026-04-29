import json
from collections.abc import Callable

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner

from core.llm import call_with_tools
from core.policy import Decision, check as policy_check
from core.tool_runtime import invoke as runtime_invoke
from skills.loader import get_tools


def run_with_tools(
    messages: list[dict],
    skills: dict,
    *,
    stream_fn: Callable[[list[dict], str], str],
    console: Console,
    model: str = "",
    max_rounds: int = 10,
) -> str:
    tools = get_tools(skills)
    messages = list(messages)

    for _round_n in range(max_rounds):
        with Live(Spinner("arc", text="  [dim]思考中…[/dim]"), refresh_per_second=20, transient=True, console=console):
            msg = call_with_tools(messages, tools, model=model)

        if not msg.tool_calls:
            break

        messages.append(msg)

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            console.print(f"[dim]→ {fn_name}…[/dim]")

            pr = policy_check(fn_name, fn_args, skills)
            if pr.decision == Decision.DENY:
                console.print(f"[red]  ✗ [策略拒绝] {pr.reason}[/red]")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"[策略拒绝] {pr.reason}",
                })
                continue

            if pr.decision == Decision.CONFIRM:
                console.print(f"\n[yellow]  ⚠  {pr.reason}[/yellow]")
                console.print("  [bold white]需要确认：[/bold white]")
                console.print("  [green bold]y[/green bold] 确认执行    [yellow bold]n[/yellow bold] 跳过此步    [red bold]q[/red bold] 取消任务\n")
                try:
                    answer = input("  → ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    answer = "q"
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
                console.print(f"\n[red]  🔴  {pr.reason}[/red]")
                console.print("  [bold white]高风险操作需要强确认：[/bold white]")
                console.print("  输入 [red bold]YES[/red bold] 执行    输入其他内容跳过    输入 [red bold]q[/red bold] 取消任务\n")
                try:
                    answer = input("  → ").strip()
                except (EOFError, KeyboardInterrupt):
                    answer = "q"
                if answer.lower() == "q":
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

            tr = runtime_invoke(fn_name, fn_args, skills)
            if not tr.ok:
                console.print(f"[yellow]  ✗ {tr.summary}[/yellow]")
            elif tr.truncated:
                console.print(f"[dim]  ↳ {tr.summary}[/dim]")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tr.to_message_content(),
            })
    else:
        console.print(f"[dim]已达最大工具调用轮次（{max_rounds}轮）[/dim]")

    return stream_fn(messages, model)
