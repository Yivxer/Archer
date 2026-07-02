#!/usr/bin/env python3
import json
import re
import sys
import threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_TOML_PATH = _PROJECT_ROOT / "archer.toml"
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from core.hooks import HookContext, run_hooks
from core.llm import stream_chat, load_config, get_last_usage, get_session_tokens, pop_config_reloaded, reset_session_tokens
from core.context import (
    build_messages, is_heavy_query, classify_query_intent,
    augment_retrieval_query,
)
from core.session import Session
from core.input import prompt as get_input
from core.compressor import should_compress, compress
from core.file_ref import parse_refs, build_user_content, ref_summary
from core.tool_loop import run_with_tools
from memory.store import (
    init_db, save, list_all, list_by_type, search, delete,
    update as update_memory, archive as archive_memory,
    add_pending, list_pending, count_pending, update_pending, accept_pending, reject_pending,
    create_project, list_projects, get_project, get_project_by_name,
    archive_project, log_project_event, get_project_events,
    count_soul_proposals, generate_session_id,
)
from memory.soul import (
    propose_from_memories, propose_from_obsidian_hints, get_pending as get_soul_pending,
    accept as soul_accept, reject as soul_reject,
)
from memory.extract import extract
from memory.retrieve import for_context, format_for_prompt
from skills.loader import load_skills
from skills.installer import install as skill_install, remove as skill_remove
from core.scheduler import (
    add_task, remove_task as remove_cron_task, set_enabled as cron_set_enabled,
    list_tasks, run_due_tasks, run_task_by_id, parse_interval, fmt_interval,
)
from core.reflection_scheduler import ensure_hypothesis_scan_schedule
from core.mcp import load_from_config as mcp_load
from workflows.runner import handle_workflow
from terminal.state import get_state, reset_state
from terminal.ui import (
    _VERSION, _RING_TOP, _RING_BOT, _ARCHER_NAME, _DSML_MARKER,
    _MEM_TYPE_COLORS,
    _token_limit, _fmt_tokens, _usage_status,
    _welcome, _onboard, _help, _status, _dash,
    _sessions_search, _memory_export,
    _mem_type_rich, _memory_list, _memory_search, _memory_add,
    _memory_pending, _memory_pending_review,
    _memory_accept, _memory_reject, _memory_update,
    _memory_archive, _memory_delete, _memory_review,
    _strip_md, _brand_spinner,
    stage_memories,
)
from terminal.commands.reflect import _reflect_to_text

console = Console()

# ── 后台提炼状态 ────────────────────────────────────────────────────────────────
_extract_thread: threading.Thread | None = None

# ── 当前会话活跃项目（已迁移至 State 单例）─────────────────────────────────────
_active_project_id: int | None = None

# ── 当前会话 ID（v1.2 Phase 3）────────────────────────────────────────────────────
_current_session_id: str = ""

# ── MCP 最近使用追踪（v1.2 Phase 4）──────────────────────────────────────────────
_mcp_last_used_turn: int = -999   # 记录最近一次调用 MCP 工具的 turn 编号
_turn_counter: int = 0

# ── 最近一条 AI 回复（供 /copy 使用）────────────────────────────────────────────
_last_response: str = ""

# MCP capability 关键词（命中 → 注入 MCP schema）
_MCP_CAPABILITY_KW = frozenset([
    "url", "网页", "抓取", "fetch", "读取链接", "远程资源",
    "github", "filesystem", "browser", "文件系统", "仓库", "issue", "pull request",
    "搜索网页", "browse", "screenshot", "截图",
])

# ── 静默录入模式 ─────────────────────────────────────────────────────────────────
# _listen_mode 已迁移到 terminal.state (State.listen_mode)，此处保留注释供参考
_listen_mode: bool = False
_LISTEN_LOG_DIR = _PROJECT_ROOT / ".listen_logs"
_stage_memories = stage_memories


def _reflect(session):
    """Compatibility wrapper for tests and old imports from root archer.py."""
    from terminal.commands import reflect as reflect_cmd

    original_stream_chat = reflect_cmd.stream_chat
    reflect_cmd.stream_chat = stream_chat
    try:
        return reflect_cmd._reflect(session)
    finally:
        reflect_cmd.stream_chat = original_stream_chat


def _persist_mode(mode: str) -> None:
    """Compatibility helper for old archer.py imports."""
    text = _TOML_PATH.read_text(encoding="utf-8")
    new_line = f'current_mode = "{mode}"'
    if re.search(r'^current_mode\s*=', text, re.MULTILINE):
        text = re.sub(r'^current_mode\s*=.*$', new_line, text, flags=re.MULTILINE)
    else:
        text = re.sub(r'^(default_mode\s*=.*)$', rf'\1\n{new_line}', text, flags=re.MULTILINE)
    _TOML_PATH.write_text(text, encoding="utf-8")


def _handle_listen(parts: list[str]) -> None:
    """Compatibility helper for the old module-level /listen state."""
    global _listen_mode
    state = get_state()
    sub = parts[1] if len(parts) > 1 else ""
    if sub in ("stop", "off", "exit") or _listen_mode:
        _listen_mode = False
        state.listen_mode = False
        console.print("[dim]已退出静默录入模式。[/dim]")
    else:
        _listen_mode = True
        state.listen_mode = True
        console.print(
            "[cyan]进入静默录入模式。[/cyan]\n"
            "[dim]输入任何内容将记录到日志，不会发送给 AI。\n"
            "再次输入 /listen 退出。[/dim]"
        )


def _listen_write(text: str) -> None:
    """Compatibility helper for writing listen-mode notes."""
    from datetime import datetime as _dt
    from memory.store import log_project_event

    _LISTEN_LOG_DIR.mkdir(exist_ok=True)
    today = _dt.now().strftime("%Y-%m-%d")
    log_file = _LISTEN_LOG_DIR / f"{today}.md"
    timestamp = _dt.now().strftime("%H:%M")
    with open(log_file, "a", encoding="utf-8") as f:
        if log_file.stat().st_size == 0:
            f.write(f"# 静默录入 {today}\n\n")
        f.write(f"- {timestamp}  {text}\n")

    active_pid = _active_project_id if _active_project_id is not None else get_state().active_project_id
    if active_pid:
        try:
            log_project_event(active_pid, "listen", text)
        except Exception:
            pass


def _should_inject_mcp(user_text: str, mcp_skills: dict, cfg: dict) -> bool:
    """
    MCP schema 三条件注入策略（v1.2 Phase 4）：
    1. 最近 N 轮使用过 MCP 工具
    2. 用户输入包含 MCP server 名称
    3. 用户输入包含 capability 关键词
    """
    if not mcp_skills:
        return False
    recent_window = cfg.get("mcp", {}).get("recent_window_turns", 10)
    recent_mcp_used = (_turn_counter - _mcp_last_used_turn) <= recent_window
    if recent_mcp_used:
        return True
    text_lower = user_text.lower()
    # server name 命中（工具名格式：{server}__{tool}）
    server_names = {name.split("__")[0] for name in mcp_skills}
    if any(s in text_lower for s in server_names):
        return True
    # capability keyword 命中
    if any(kw in text_lower for kw in _MCP_CAPABILITY_KW):
        return True
    return False


_dsml_intercepted: bool = False  # set by _stream() when DSML is mid-stream cut


def _stream(messages: list[dict], model: str = "") -> str:
    global _last_response, _dsml_intercepted
    _dsml_intercepted = False
    gen = stream_chat(messages, model=model)
    full = ""
    line_buf = ""
    for chunk in gen:
        # Check for DSML in the combined pending buffer + incoming chunk
        if _DSML_MARKER in (line_buf + chunk):
            combined = line_buf + chunk
            clean = combined.split(_DSML_MARKER)[0]
            if clean:
                sys.stdout.write(_strip_md(clean) + "\n")
                sys.stdout.flush()
            full += clean
            _dsml_intercepted = True
            break
        full += chunk
        line_buf += chunk
        # 每遇到换行，strip 当前行后输出
        while "\n" in line_buf:
            line, line_buf = line_buf.split("\n", 1)
            sys.stdout.write(_strip_md(line) + "\n")
            sys.stdout.flush()
    if not _dsml_intercepted:
        # 输出末尾未换行的剩余内容
        if line_buf:
            sys.stdout.write(_strip_md(line_buf) + "\n")
        else:
            sys.stdout.write("\n")
    sys.stdout.flush()
    _last_response = _strip_md(full)
    return _last_response

def _run_with_tools(messages: list[dict], skills: dict, model: str = "", cfg: dict | None = None, user_input: str = "") -> str:
    return run_with_tools(messages, skills, stream_fn=_stream, console=console, model=model, cfg=cfg, session_id=_current_session_id, user_input=user_input)

_FAKE_XML_RE = re.compile(
    r"<(读取文件|写入文件|搜索文件|文件查找|参数|tool_call|invoke|function_call|execute)[^>]{0,60}>",
    re.IGNORECASE,
)

def _has_fake_xml(text: str) -> bool:
    """检测 DeepSeek 输出的伪 XML 假标签或 DSML 残留。"""
    return bool(_FAKE_XML_RE.search(text)) or _DSML_MARKER in text or _dsml_intercepted

def _auto_extract(history: list[dict], silent: bool = False):
    if len(history) < 2:
        return
    if not silent:
        console.print("\n[dim]正在提炼记忆…[/dim]")
    try:
        mems, obsidian_hints = extract(history)
        if mems:
            _stage_memories(mems, source="auto", silent=silent)
            # SOUL 相关记忆 → soul proposal（不自动写入）
            soul_ids = propose_from_memories(mems, source="extract")
            if soul_ids and not silent:
                console.print(f"[dim]发现 {len(soul_ids)} 条 SOUL 演化提议，使用 /soul 查看。[/dim]")
        elif not silent:
            console.print("[dim]本次对话无新记忆。[/dim]")

        # P3: 情绪提取
        from memory.emotion import extract_emotion
        emo = extract_emotion(history, _current_session_id, cfg=None)
        if emo and not silent:
            emo_str = "  ".join(f"{k} {v:.0f}" for k, v in sorted(emo.items()))
            console.print(f"[dim]情绪标记：{emo_str}[/dim]")

        if obsidian_hints:
            soul_ids_h = propose_from_obsidian_hints(obsidian_hints, source="extract")
            non_soul = [h for h in obsidian_hints if h.get("file") != "SOUL.md"]
            if non_soul and not silent:
                for hint in non_soul:
                    console.print(
                        f"\n[cyan]建议写入 {hint['file']}：[/cyan]\n"
                        f"  [dim]{hint['content'][:80]}[/dim]"
                    )
            if soul_ids_h and not silent:
                console.print(f"[dim]发现 {len(soul_ids_h)} 条 SOUL 演化提议，使用 /soul 查看。[/dim]")
    except Exception:
        pass


def _bg_extract(history: list[dict]):
    """在后台线程中静默提炼，不阻塞 REPL。若上一次提炼仍在进行则跳过。"""
    global _extract_thread
    if _extract_thread and _extract_thread.is_alive():
        return
    snapshot = list(history)
    _extract_thread = threading.Thread(
        target=_auto_extract, args=(snapshot, True), daemon=True
    )
    _extract_thread.start()


def _wait_for_extract(timeout: float = 12.0):
    """退出前等待后台提炼线程结束，最多等待 timeout 秒。"""
    if _extract_thread and _extract_thread.is_alive():
        _extract_thread.join(timeout=timeout)

# ── 命令系统 ─────────────────────────────────────────────────────────────────────
from terminal.commands import dispatch as cmd_dispatch, registered_commands

def run():
    global _current_session_id, _turn_counter, _mcp_last_used_turn
    init_db()
    _current_session_id = generate_session_id()
    # 初始化向量索引表（sqlite-vec 未安装时静默跳过）
    try:
        from memory.vector_store import init_vec_table
        init_vec_table()
    except Exception:
        pass
    cfg = load_config()
    session = Session()
    reset_session_tokens()
    skills = load_skills()
    run_hooks(
        "SessionStart",
        HookContext(event="SessionStart", session_id=_current_session_id),
        cfg=cfg,
    )

    # ── MCP 初始化（可选，配置驱动）─────────────────────────────────────────
    _mcp_manager = None
    _mcp_skills: dict = {}
    try:
        _mcp_manager = mcp_load(cfg)
        if _mcp_manager:
            _mcp_skills = _mcp_manager.make_deferred_registry()
    except Exception as _e:
        console.print(f"[dim]MCP 初始化失败，已跳过：{_e}[/dim]")

    # ── 首次运行引导 / 欢迎横幅 ────────────────────────────────────────────
    from core.model_profiles import active_api_config
    active_api = active_api_config(cfg)
    if not active_api.get("api_key") and not active_api.get("model"):
        onboarded = _onboard()
        if onboarded:
            cfg = load_config()
    else:
        _welcome(cfg)

    # ── 启动时执行到期定时任务 ─────────────────────────────────────────────────
    ensure_hypothesis_scan_schedule()
    startup_cron = run_due_tasks(skills)
    for task, tr in startup_cron:
        label = task.get("label") or task["skill_name"]
        if tr is None:
            console.print(f"[yellow]⏰ 定时任务「{label}」：技能未加载，已跳过。[/yellow]")
        elif tr.ok:
            console.print(f"[dim]⏰ 定时任务「{label}」已执行。[/dim]")
            if tr.content_preview:
                console.print(tr.content_preview[:400], markup=False)
        else:
            console.print(f"[yellow]⏰ 定时任务「{label}」执行失败：{tr.summary}[/yellow]")

    turn_count = 0
    last_stance = cfg["persona"].get("default_mode", "listener")

    while True:
        # ── 配置热加载 ─────────────────────────────────────────────────
        cfg = load_config()
        if pop_config_reloaded():
            console.print("[dim]archer.toml 已更新，配置已重新加载。[/dim]")

        last_usage = get_last_usage()
        if should_compress(
            session.history,
            prompt_tokens=last_usage["prompt_tokens"],
            token_limit=_token_limit(cfg),
        ):
            console.print("[dim]上下文接近预算，正在压缩…[/dim]")
            try:
                session.history = compress(session.history, cfg=cfg)
                console.print("[dim]压缩完成，上下文已精简。[/dim]")
            except Exception as e:
                console.print(f"[dim]压缩失败，跳过：{e}[/dim]")

        active_api = active_api_config(cfg)
        current_model = active_api["model"]
        mode_auto = cfg["persona"].get("mode_auto", True)
        current_mode = last_stance if mode_auto else cfg["persona"].get("current_mode", cfg["persona"].get("default_mode", "coach"))
        modes = cfg.get("persona", {}).get("modes", {})
        mode_name = modes.get(current_mode, {}).get("name", current_mode)
        if mode_auto:
            mode_name = f"自动·{mode_name}"

        # 静默录入模式在状态栏显示特殊标识
        display_mode = "🎙 静默录入" if get_state().listen_mode else mode_name

        console.print()
        try:
            user_input = get_input(
                model=current_model,
                mode=display_mode,
                usage=_usage_status(cfg),
            )
        except (KeyboardInterrupt, EOFError):
            console.print()
            run_hooks(
                "SessionStop",
                HookContext(event="SessionStop", session_id=_current_session_id),
                cfg=cfg,
            )
            _wait_for_extract()
            if len(session.history) >= 2:
                _auto_extract(session.history, silent=True)
            session.save()
            if _mcp_manager:
                _mcp_manager.stop()
            console.print("[dim]已退出。[/dim]")
            break

        if not user_input:
            continue

        # ── 静默录入模式拦截 ────────────────────────────────────────────
        # 已注册命令（含 /listen）正常放行到命令分发，仅拦截非命令文本
        if get_state().listen_mode:
            _parts = user_input.split()
            if user_input.startswith("/") and _parts and _parts[0] in registered_commands():
                pass  # 放行到下方命令分发
            else:
                _listen_write(user_input)
                console.print("[dim]已记录。[/dim]")
                continue

        parts = user_input.split()
        if user_input.startswith("/") and parts[0] in registered_commands():
            cmd_ctx: dict = {
                "parts": parts,
                "session": session,
                "skills": skills,
                "cfg": cfg,
                "console": console,
                "state": {"last_response": _last_response},
                "active_project_id": get_state().active_project_id,
            }
            if cmd_dispatch(parts[0], cmd_ctx):
                # 检查 /skill 是否更新了技能
                if "skills" in cmd_ctx["state"]:
                    skills = cmd_ctx["state"]["skills"]
                # 检查 /exit 是否设置了退出标志
                if cmd_ctx["state"].get("should_exit"):
                    if _mcp_manager:
                        _mcp_manager.stop()
                    break
                continue
            else:
                console.print(f"[yellow]未知命令：{parts[0]}[/yellow]")
                continue

        user_text, refs = parse_refs(user_input)
        if refs:
            summary = ref_summary(refs)
            console.print(f"[dim]附件：{summary}[/dim]")
        user_content = build_user_content(user_text, refs)

        intent_info = classify_query_intent(
            user_text, history=session.history, llm_fallback=True,
        )
        from core.orchestrator import (
            build_task_plan,
            collect_soul_insight_context,
            format_mode_constraints_for_prompt,
            format_task_plan_for_prompt,
            orchestrate_user_input,
        )
        orchestration = orchestrate_user_input(
            user_text,
            manual_mode=None if cfg["persona"].get("mode_auto", True) else cfg["persona"].get("current_mode"),
            active_project_id=get_state().active_project_id,
            history=session.history,
            soul_insight=collect_soul_insight_context(limit=3),
        )
        task_plan_block = format_task_plan_for_prompt(
            build_task_plan(user_text, orchestration)
        )
        mode_constraint_block = format_mode_constraints_for_prompt(orchestration)
        heavy       = intent_info["needs_memory"]
        intent      = intent_info["intent"]
        from core.context import resolve_context_limits
        context_limits = resolve_context_limits(
            orchestration.memory_scope,
            needs_memory=heavy,
        )
        memory_limit = context_limits.retrieve_total
        retrieval_query = augment_retrieval_query(user_text, session.history)
        core_mems, related_mems = for_context(retrieval_query, limit=memory_limit, intent=intent)
        mem_block = format_for_prompt(core_mems, related_mems)
        project     = get_project(get_state().active_project_id) if get_state().active_project_id else None
        proj_evts   = get_project_events(get_state().active_project_id, limit=context_limits.project_events) if get_state().active_project_id else []
        # 动态对话姿态：优先 orchestrator mode；/mode 锁定时让位
        active_stance = orchestration.mode
        if not cfg["persona"].get("mode_auto", True):
            active_stance = cfg["persona"].get("current_mode") or active_stance
        elif active_stance != last_stance:
            console.print(f"[dim]· 姿态 → {active_stance}（orchestrator）[/dim]")
        last_stance = active_stance
        # P6: 对峙检测
        from memory.narrative import confrontation_hook
        from memory.emotion import infer_turn_emotion_hint
        from core.thread import resolve_topic_thread
        confrontation_hints = confrontation_hook(user_text, session.history)
        emotion_hint = infer_turn_emotion_hint(user_text, session.history)
        thread_hint = resolve_topic_thread(user_text, session.history)
        messages    = build_messages(
            session.history, user_content, cfg,
            db_memories=mem_block, project=project,
            project_events=proj_evts, heavy=heavy,
            intent=intent, confrontation_hints=confrontation_hints or None,
            mode_override=active_stance,
            emotion_hint=emotion_hint,
            thread_hint=thread_hint,
            writing_query=user_text,
            memory_scope=orchestration.memory_scope,
            task_plan_block=task_plan_block,
            mode_constraint_block=mode_constraint_block,
            needs_project_context=orchestration.needs_project_context,
            context_limits=context_limits,
        )

        has_images = any(r["type"] == "image" for r in refs)
        active_model = ""
        if has_images:
            active_api = active_api_config(cfg)
            vision_model = active_api.get("vision_model", "")
            text_model   = active_api["model"]
            if not vision_model or vision_model == text_model:
                console.print("[yellow]图片需要支持视觉的模型，请在 archer.toml 中配置 vision_model。[/yellow]")
                has_images = False
                user_content = user_text
                messages = build_messages(
                    session.history, user_content, cfg,
                    db_memories=mem_block, project=project,
                    project_events=proj_evts, heavy=heavy,
                    intent=intent, confrontation_hints=confrontation_hints or None,
                    mode_override=active_stance,
                    emotion_hint=emotion_hint,
                    thread_hint=thread_hint,
                    writing_query=user_text,
                    memory_scope=orchestration.memory_scope,
                    task_plan_block=task_plan_block,
                    mode_constraint_block=mode_constraint_block,
                    needs_project_context=orchestration.needs_project_context,
                )
            else:
                active_model = vision_model
                console.print(f"[dim]图片模式 → {active_model}[/dim]")

        if not active_model:
            from core.model_select import resolve_active_model
            active_model, model_reason = resolve_active_model(
                cfg,
                user_text=user_text,
                intent=intent,
                needs_tools=bool(intent_info.get("needs_tools")),
                has_images=has_images,
            )
            if active_api_config(cfg).get("model_auto", True) and model_reason not in ("locked", "single"):
                console.print(f"[dim]· 模型 → {active_model}（{model_reason}）[/dim]")

        try:
            # 品牌标记
            spinner = _brand_spinner("思考中")
            console.print(spinner)
            from core.desktop_tool_router import plan_desktop_turn
            _turn = plan_desktop_turn(
                user_text, skills,
                intent=intent,
                needs_tools=bool(intent_info.get("needs_tools")),
                llm_fallback=True,
            )
            active_skills = _turn.filtered_skills
            # MCP 工具：三条件策略注入（recent/server_name/capability_keyword）
            if _mcp_skills and _should_inject_mcp(user_text, _mcp_skills, cfg):
                from skills.loader import ChainSkillRegistry
                active_skills = ChainSkillRegistry(active_skills, _mcp_skills)
            if active_skills:
                full_response = _run_with_tools(messages, active_skills, model=active_model, cfg=cfg, user_input=user_text)
                # DSML 救援：tool_loop 末尾 stream_fn 在工具调用上下文残留时输出 DSML
                if _dsml_intercepted:
                    console.print("[dim]检测到 DSML 残留，重新发起最终回答…[/dim]")
                    rescue_msgs = list(messages) + [
                        {"role": "user", "content": "请直接给出最终回答，不要调用工具。"},
                    ]
                    full_response = _stream(rescue_msgs, model=active_model)
            else:
                full_response = _stream(messages, model=active_model)
                # 假 XML / DSML 救援：DeepSeek 在无工具上下文时会输出伪标签
                if _has_fake_xml(full_response) and skills:
                    console.print("[dim]检测到假标签，切换到工具调用模式…[/dim]")
                    rescue_msgs = list(messages) + [
                        {"role": "assistant", "content": full_response},
                        {"role": "user", "content": (
                            "你刚才输出了假标签（如 <读取文件>），这些不会被执行。"
                            "请直接用 function calling 调用工具完成刚才说要做的事，不要再输出 XML。"
                        )},
                    ]
                    full_response = _run_with_tools(rescue_msgs, skills, model=active_model, cfg=cfg, user_input=user_text)
        except Exception as e:
            err = str(e)
            if "image_url" in err or "image" in err.lower():
                console.print("[yellow]图片模式 API 报错，请检查 vision_model 配置。[/yellow]")
            else:
                console.print(f"[red]错误：{e}[/red]")
            continue

        history_user = user_text
        if refs:
            names = [r["name"] for r in refs if r["type"] != "error"]
            if names:
                history_user += f"\n[附件：{', '.join(names)}]"
        session.add(history_user, full_response)
        turn_count += 1
        _turn_counter += 1

        # 交互反馈信号检测
        try:
            from memory.feedback import detect as _fb_detect, should_propose, generate_presence_proposal
            _fb_detect(user_text, prev_response=full_response[:120], session_id=_current_session_id)
            if turn_count % 10 == 0 and should_propose():
                proposal = generate_presence_proposal(cfg)
                if proposal:
                    from memory.store import add_pending
                    add_pending(content=proposal, type="insight", importance=3,
                                tags="presence,feedback", source="feedback")
                    console.print("[dim]检测到多次纠正信号，已生成在场方式调整提议（/memory pending 查看）。[/dim]")
        except Exception:
            pass

        if turn_count % 6 == 0 and len(session.history) >= 6:
            _bg_extract(session.history[-8:])

if __name__ == "__main__":
    run()
