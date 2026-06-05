"""
Sub-task Runner (v1.5 Phase C/D)

Phase C — 混合并行执行：
  - plan / review（无工具）+ explore（只读工具）→ ThreadPoolExecutor 并行
  - work（全量工具，可能触发 CONFIRM）→ 顺序执行
  - 并行任务用 buffer console，Rich Progress 显示实时状态
  - 前序结果快照传入每个并行任务（启动时状态，不含并行间互相等待）

Phase D — Steering（向排队中的子任务注入补充指令）：
  - 模块级 _steering_buffer: {work_item_id: [message, ...]}
  - steer(work_item_id, msg) 添加消息
  - 每个 subtask 启动前消费 buffer，注入为额外 user message
  - 影响尚未开始的任务，不中断运行中的任务
"""
from __future__ import annotations

import io
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn

from memory.subtask import (
    AGENT_TYPES,
    get as subtask_get,
    get_agent_system_prompt,
    list_for_work,
    set_done,
    set_failed,
    set_running,
)

# ── 并行策略 ─────────────────────────────────────────────────────────────────
# 这些 agent_type 不需要用户交互，可安全并行
_PARALLEL_TYPES = frozenset({"plan", "review", "explore"})
_MAX_PARALLEL = 4

# ── Phase D: Steering buffer ─────────────────────────────────────────────────
_steering_lock = threading.Lock()
_steering_buffer: dict[int, list[str]] = {}   # work_item_id → [msg, ...]


def steer(work_item_id: int, message: str) -> None:
    """向 work_item 下待执行的子任务注入补充指令（Phase D）。"""
    with _steering_lock:
        _steering_buffer.setdefault(work_item_id, []).append(message)


def _consume_steering(work_item_id: int | None) -> list[str]:
    """消费并清空 steering buffer，返回消息列表。"""
    if work_item_id is None:
        return []
    with _steering_lock:
        msgs = _steering_buffer.pop(work_item_id, [])
    return msgs


# ── 工具/模型辅助 ─────────────────────────────────────────────────────────────
_AGENT_SKILLS_FILTER: dict[str, list[str] | None] = {
    "explore": ["web_fetch", "file_search", "obsidian_search", "rss_reader", "weather"],
    "plan":    [],
    "work":    None,
    "review":  [],
}


def _resolve_model(tier: str, cfg: dict) -> str:
    models = cfg.get("models") or [cfg.get("api", {}).get("model", "")]
    if tier == "fast" and len(models) >= 2:
        return models[1]
    return models[0] if models else cfg.get("api", {}).get("model", "")


def _filter_skills(skills: dict, allowed: list[str] | None) -> dict:
    if allowed is None:
        return skills
    return {k: v for k, v in skills.items() if k in allowed}


# ── 消息构建 ─────────────────────────────────────────────────────────────────

def _build_messages(
    subtask: dict,
    prior_results: list[dict],
    steering_msgs: list[str],
) -> list[dict]:
    agent_prompt = get_agent_system_prompt(subtask["agent_type"])
    system = f"{agent_prompt}\n\n输出格式：纯文本，不使用 Markdown 语法。"

    if prior_results:
        parts = [
            f"[子任务 #{pr['id']} - {pr['agent_type']} 结果]\n{pr['result']}"
            for pr in prior_results if pr.get("result")
        ]
        if parts:
            system += "\n\n[前序子任务结果，供参考]\n" + "\n\n".join(parts)

    messages = [{"role": "system", "content": system}]

    if steering_msgs:
        # 将 steering 注入为首条 user 消息
        context = "\n".join(f"· {m}" for m in steering_msgs)
        messages.append({
            "role": "user",
            "content": f"[补充指令]\n{context}\n\n[原始任务]\n{subtask['prompt']}",
        })
    else:
        messages.append({"role": "user", "content": subtask["prompt"]})

    return messages


# ── 单任务执行（可被主线程或 worker 线程调用）────────────────────────────────

def run_subtask(
    subtask_id: int,
    skills: dict,
    cfg: dict,
    console: Console,
    prior_results: list[dict] | None = None,
) -> str | None:
    """
    执行单个 subtask，返回结果文本（失败时返回 None）。
    线程安全：每次调用创建独立的 DB 连接。
    """
    st = subtask_get(subtask_id)
    if not st:
        console.print(f"[yellow]  subtask #{subtask_id} 不存在[/yellow]")
        return None
    if st["status"] != "pending":
        console.print(f"[dim]  subtask #{subtask_id} 状态 {st['status']}，跳过[/dim]")
        return st.get("result")

    agent_type = st["agent_type"]
    model      = _resolve_model(st["model_tier"], cfg)
    steering   = _consume_steering(st.get("work_item_id"))
    messages   = _build_messages(st, prior_results or [], steering)
    allowed    = _AGENT_SKILLS_FILTER.get(agent_type, [])
    active_skills = _filter_skills(skills, allowed)

    if steering:
        console.print(f"[dim]  [{agent_type}] #{subtask_id} 注入 {len(steering)} 条 steering 指令[/dim]")
    console.print(f"[dim]  [{agent_type}] #{subtask_id} 开始…[/dim]")
    set_running(subtask_id)

    try:
        if active_skills:
            from core.tool_loop import run_with_tools

            def _stream_fn(msgs: list[dict], mdl: str) -> str:
                from core.llm import stream_chat
                return "".join(stream_chat(msgs, model=mdl))

            result = run_with_tools(
                messages,
                active_skills,
                stream_fn=_stream_fn,
                console=console,
                model=model,
                max_rounds=6,
                cfg=cfg,
            )
        else:
            from core.llm import stream_chat
            result = "".join(stream_chat(messages, model=model))

        set_done(subtask_id, result)
        console.print(f"[dim]  [{agent_type}] #{subtask_id} 完成（{len(result)} 字符）[/dim]")
        return result

    except Exception as e:
        err = str(e)
        set_failed(subtask_id, err)
        console.print(f"[yellow]  [{agent_type}] #{subtask_id} 失败：{err[:80]}[/yellow]")
        return None


# ── 并行 worker（buffer console，不干扰主 Progress）────────────────────────

def _run_buffered(
    subtask_id: int,
    skills: dict,
    cfg: dict,
    prior_results: list[dict],
) -> tuple[int, str | None, str]:
    """在独立线程中执行，用 buffer console 捕获输出。返回 (id, result, output)。"""
    buf = io.StringIO()
    buf_console = Console(file=buf, highlight=False, markup=False)
    result = run_subtask(subtask_id, skills, cfg, buf_console, prior_results=list(prior_results))
    return subtask_id, result, buf.getvalue()


# ── 主入口 ─────────────────────────────────────────────────────────────────

def run_work_subtasks(
    work_item_id: int,
    skills: dict,
    cfg: dict,
    console: Console,
) -> list[dict]:
    """
    执行 work item 下所有 pending subtask：
    - plan/review/explore → ThreadPoolExecutor 并行 + Progress 显示
    - work               → 顺序执行（可能触发 CONFIRM）
    """
    from memory.work import get as work_get
    w = work_get(work_item_id)
    if not w:
        console.print(f"[yellow]Work #{work_item_id} 不存在[/yellow]")
        return []

    all_tasks = list_for_work(work_item_id)
    pending   = [t for t in all_tasks if t["status"] == "pending"]
    if not pending:
        console.print(f"[dim]Work #{work_item_id} 没有待执行的子任务。[/dim]")
        return all_tasks

    console.print(
        f"\n[bold cyan]执行子任务[/bold cyan]  "
        f"Work #{work_item_id}《{w['title']}》  共 {len(pending)} 个\n"
    )

    # 分组
    para_tasks = [t for t in pending if t["agent_type"] in _PARALLEL_TYPES]
    seq_tasks  = [t for t in pending if t["agent_type"] not in _PARALLEL_TYPES]

    # 已完成任务作为初始上下文
    completed: list[dict] = [t for t in all_tasks if t["status"] == "done"]

    # ── 并行组 ───────────────────────────────────────────────────────────────
    if para_tasks:
        _run_parallel(para_tasks, skills, cfg, console, completed)
        # 刷新 completed（拿数据库最新状态）
        completed = [t for t in list_for_work(work_item_id) if t.get("result")]

    # ── 顺序组 ───────────────────────────────────────────────────────────────
    for t in seq_tasks:
        run_subtask(t["id"], skills, cfg, console, prior_results=completed)
        updated = subtask_get(t["id"])
        if updated and updated.get("result"):
            completed.append(updated)

    # ── 汇总 ─────────────────────────────────────────────────────────────────
    final        = list_for_work(work_item_id)
    done_count   = sum(1 for t in final if t["status"] == "done")
    failed_count = sum(1 for t in final if t["status"] == "failed")
    total        = len(final)
    console.print(
        f"\n[dim]完成 {done_count}/{total}"
        + (f"  失败 {failed_count}" if failed_count else "")
        + "[/dim]"
    )

    # ── 结果回流：把子任务结果归档到 Work item ────────────────────────────────
    _flush_results_to_work(work_item_id, final, console)

    return final


def _flush_results_to_work(
    work_item_id: int,
    final_tasks: list[dict],
    console: Console,
) -> None:
    """将已完成子任务的结果摘要写回 Work item 的 artifacts 字段。"""
    from memory.work import add_artifact, update_status, get as work_get

    done = [t for t in final_tasks if t["status"] == "done" and t.get("result")]
    if not done:
        return

    # 每个已完成子任务生成一行摘要，存为虚拟 artifact（文本标记）
    for t in done:
        result_preview = (t["result"] or "")[:120].replace("\n", " ")
        tag = f"[{t['agent_type']}#{t['id']}] {result_preview}"
        add_artifact(work_item_id, tag)

    # 如果所有子任务都完成（无 pending/running/failed），自动把 Work 标记为 done
    active_statuses = {t["status"] for t in final_tasks}
    if active_statuses <= {"done", "cancelled"}:
        w = work_get(work_item_id)
        if w and w["status"] == "in_progress":
            update_status(work_item_id, "done")
            console.print(f"[green]Work #{work_item_id} 所有子任务完成，已自动标记为 done。[/green]")


def _run_parallel(
    tasks: list[dict],
    skills: dict,
    cfg: dict,
    console: Console,
    prior_snapshot: list[dict],
) -> None:
    """用 Progress + ThreadPoolExecutor 并行执行任务列表。"""
    n = min(len(tasks), _MAX_PARALLEL)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        TextColumn("[dim]{task.fields[status]}"),
        console=console,
        transient=False,
    ) as progress:

        prog_ids: dict[int, TaskID] = {}
        for t in tasks:
            label = f"[{t['agent_type']}] #{t['id']}"
            ptid  = progress.add_task(label, status="排队中", total=1)
            prog_ids[t["id"]] = ptid

        futures: dict = {}
        with ThreadPoolExecutor(max_workers=n) as pool:
            for t in tasks:
                progress.update(prog_ids[t["id"]], status="执行中")
                f = pool.submit(_run_buffered, t["id"], skills, cfg, prior_snapshot)
                futures[f] = t["id"]

            for future in as_completed(futures):
                st_id = futures[future]
                ptid  = prog_ids[st_id]
                try:
                    sid, result, output = future.result()
                    st = subtask_get(sid)
                    status_text = "完成" if (st and st["status"] == "done") else "失败"
                    progress.update(ptid, status=status_text, completed=1)
                    # 输出缓冲的工具调用日志（在 Progress 外打印会更干净，但 transient=False 时可以直接 print）
                    if output.strip():
                        for line in output.strip().splitlines():
                            if line.strip():
                                progress.console.print(f"  [dim]{line.strip()}[/dim]")
                except Exception as e:
                    progress.update(ptid, status=f"异常: {str(e)[:25]}", completed=1)
