"""复盘与搜索命令。"""
from __future__ import annotations

import json
from pathlib import Path

from .registry import register
from rich.console import Console
from rich.live import Live
from memory.store import (
    save, add_pending,
    get_project, log_project_event,
)
from memory.soul import propose_from_memories
from memory.session_insights import format_report
from terminal.ui import _sessions_search, _brand_spinner, stage_memories
from terminal.state import get_state
from core.llm import stream_chat

console = Console()
_LISTEN_LOG_DIR = Path(__file__).resolve().parent.parent.parent / ".listen_logs"

# ── 复盘 prompt ─────────────────────────────────────────────────────────────
_REFLECT_PROMPT = """你是一个对话复盘助手。请分析以下对话历史，输出结构化复盘结果。

输出格式（严格 JSON）：
{
  "summary": "本次对话一句话总结（20字以内）",
  "user_intent": "用户的核心意图或主要问题",
  "decisions": ["做出的决定，每条具体可落地"],
  "open_questions": ["尚未解决的问题或悬而未决的方向"],
  "memory_candidates": [
    {"content": "值得长期记忆的信息", "type": "decision|insight|project|preference|todo", "importance": 3}
  ],
  "next_actions": ["72小时内可执行的具体下一步"]
}
每类最多 3 条，没有内容写空数组 []。只输出 JSON。"""


def _reflect(session):
    if len(session.history) < 2:
        console.print("[dim]对话太短，无需复盘。[/dim]")
        return

    messages = [{"role": "system", "content": _REFLECT_PROMPT}, *session.history[-10:]]

    raw = ""
    with Live(_brand_spinner("复盘中"), refresh_per_second=20, transient=True, console=console):
        for chunk in stream_chat(messages):
            raw += chunk

    try:
        s, e = raw.find("{"), raw.rfind("}") + 1
        data = json.loads(raw[s:e]) if s >= 0 and e > s else {}
    except Exception:
        data = {}

    if not data:
        console.print("[dim]复盘解析失败，原始输出：[/dim]")
        console.print(raw, markup=False)
        return

    # ── 展示 ──────────────────────────────────────────────────────
    console.print("\n[bold cyan]复盘[/bold cyan]")
    if data.get("summary"):
        console.print(f"\n  [bold]{data['summary']}[/bold]")
    if data.get("user_intent"):
        console.print(f"  [dim]意图：{data['user_intent']}[/dim]")

    def _section(title: str, items: list):
        if items:
            console.print(f"\n  [bold]{title}[/bold]")
            for item in items:
                console.print(f"    · {item}")

    _section("决策",     data.get("decisions", []))
    _section("未解问题", data.get("open_questions", []))
    _section("下一步",   data.get("next_actions", []))

    # P3: 情绪趋势摘要
    from memory.emotion import emotion_summary
    emo = emotion_summary(30)
    if emo:
        console.print(f"\n  [dim]情绪趋势（30 天）：{emo}[/dim]")

    # ── 记忆候选 → pending；SOUL 相关 → soul proposal ────────────────
    candidates = data.get("memory_candidates", [])
    if candidates:
        stage_memories(candidates, source="reflect")
        soul_ids = propose_from_memories(candidates, source="reflect")
        if soul_ids:
            console.print(f"[dim]发现 {len(soul_ids)} 条 SOUL 演化提议，使用 /soul 查看。[/dim]")

    # ── 保存 reflection 摘要到记忆库（不自动注入上下文）────────────
    summary = data.get("summary", "").strip()
    if summary:
        save(summary, type="reflection", importance=3, source="reflect")

    # ── 保存完整 JSON 到 artifact ──────────────────────────────────
    from core.artifacts import save_reflection as _save_reflect_artifact
    artifact_path = _save_reflect_artifact(
        json.dumps(data, ensure_ascii=False, indent=2)
    )
    console.print(f"\n[dim]完整复盘 → {artifact_path}[/dim]")

    # ── 进入 session history，允许追问 ────────────────────────────
    session.add("[/reflect]", _reflect_to_text(data))
    console.print("[dim]复盘已加入对话历史，可直接追问。[/dim]")

    # ── 若有活跃项目，把 summary 写入项目日志 ─────────────────────────
    _active_project_id = get_state().active_project_id
    if _active_project_id and summary:
        log_project_event(_active_project_id, "reflect", summary)
        proj = get_project(_active_project_id)
        if proj:
            console.print(f"[dim]复盘摘要已记录到项目「{proj['name']}」。[/dim]")

    # 注：不再调用 _bg_extract，主循环每 6 轮自动执行后台提炼


def _reflect_to_text(data: dict) -> str:
    """将复盘结构化数据转为自然语言，注入 session history 供追问。"""
    parts = []
    if data.get("summary"):
        parts.append(f"复盘总结：{data['summary']}")
    if data.get("user_intent"):
        parts.append(f"核心意图：{data['user_intent']}")
    for key, label in [
        ("decisions",      "决策"),
        ("open_questions", "未解问题"),
        ("next_actions",   "下一步行动"),
    ]:
        items = data.get(key, [])
        if items:
            parts.append(f"{label}：" + "；".join(items))
    n = len(data.get("memory_candidates", []))
    if n:
        parts.append(f"已提炼 {n} 条记忆候选（待确认后写入记忆库）")
    return "\n".join(parts) or "复盘完成，无关键信息。"


def _handle_listen(parts: list[str]):
    state = get_state()
    sub = parts[1] if len(parts) > 1 else ""
    if sub in ("stop", "off", "exit") or state.listen_mode:
        state.listen_mode = False
        console.print("[dim]已退出静默录入模式。[/dim]")
    else:
        state.listen_mode = True
        console.print(
            "[cyan]进入静默录入模式。[/cyan]\n"
            "[dim]输入任何内容将记录到日志，不会发送给 AI。\n"
            "再次输入 /listen 退出。[/dim]"
        )


def _listen_write(text: str):
    """把静默录入内容写入当日日志文件，同时写入活跃项目（若有）。"""
    from datetime import datetime as _dt
    _LISTEN_LOG_DIR.mkdir(exist_ok=True)
    today = _dt.now().strftime("%Y-%m-%d")
    log_file = _LISTEN_LOG_DIR / f"{today}.md"
    timestamp = _dt.now().strftime("%H:%M")
    with open(log_file, "a", encoding="utf-8") as f:
        if log_file.stat().st_size == 0:
            f.write(f"# 静默录入 {today}\n\n")
        f.write(f"- {timestamp}  {text}\n")
    _active_project_id = get_state().active_project_id
    if _active_project_id:
        try:
            log_project_event(_active_project_id, "listen", text)
        except Exception:
            pass


# ── 命令注册 ──────────────────────────────────────────────────────────────────

def _cmd_reflect(ctx):
    _reflect(ctx['session'])


def _cmd_sessions(ctx):
    parts = ctx['parts']
    from memory.session_insights import format_report
    if len(parts) > 1 and parts[1] == "search":
        kw = " ".join(parts[2:])
        if kw:
            _sessions_search(kw)
        else:
            ctx['console'].print("[yellow]用法：/sessions search <关键词>[/yellow]")
    else:
        days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 7
        ctx['console'].print(format_report(days))


def _cmd_copy(ctx):
    last = ctx['state'].get('last_response', '')
    if not last:
        ctx['console'].print("[dim]还没有可复制的回复。[/dim]")
    else:
        import subprocess as _sp
        try:
            _sp.run(["pbcopy"], input=last.encode(), check=True)
            preview = last[:60].replace("\n", " ")
            ctx['console'].print(f"[dim]已复制（{len(last)} 字符）：{preview}…[/dim]")
        except FileNotFoundError:
            ctx['console'].print("[yellow]pbcopy 不可用（仅支持 macOS）。[/yellow]")
        except Exception as _e:
            ctx['console'].print(f"[red]复制失败：{_e}[/red]")


def _cmd_listen(ctx):
    _handle_listen(ctx['parts'])


register("/reflect", _cmd_reflect, "复盘最近对话")
register("/sessions", _cmd_sessions, "最近会话统计")
register("/copy", _cmd_copy, "复制上一条回复")
register("/listen", _cmd_listen, "静默录入模式")
