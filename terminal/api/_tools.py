"""Tool event system and chat streaming for the Archer Desktop API."""

from __future__ import annotations

import logging
from uuid import uuid4

from terminal.api._config import (
    PENDING_TOOL_DRAFTS,
    set_tool_draft,
    get_tool_draft,
    pop_tool_draft,
    TEXT_FILE_EXTENSIONS,
    _clean_chat_messages,
    _load_config,
)
from terminal.api.turn_context import (
    clean_file_refs as _clean_file_refs,
    clean_memory_mode as _clean_memory_mode,
    clean_obsidian_mode as _clean_obsidian_mode,
    merge_inline_markdown_refs,
)
from terminal.api.context_assembly import (
    assemble_memory_context,
    assemble_obsidian_context,
    assemble_vault_focus,
    assemble_web_context,
    file_reference_context,
    build_memory_context_event,
)
from terminal.api.chat_turn_context import FullTurnDependencies, prepare_full_turn
from terminal.api.hugo_turn import HugoTurnDependencies, iter_hugo_turn_events
from terminal.api.chat_reply import ChatReplyDependencies, iter_chat_reply_events
from terminal.api.post_reply_drafts import PostReplyDraftDependencies, iter_post_reply_draft_events
from terminal.api.turn_pipeline import (
    assemble_model_messages,
    classify_turn,
    orchestrate_turn,
    select_turn_tools,
    plain_chat_message as _plain_chat_message,
    trim_model_messages as _trim_model_messages_for_context,
)
from terminal.api.tool_stage import summarize_api_tool_events
from terminal.api.model_stream import has_fake_tool_markup as _has_fake_xml, iter_model_stream, iter_rescue_stream, model_trace_metadata, select_model_for_turn, split_safe_model_chunk as _split_safe_model_chunk, stream_failure_events, default_profile_fallback, token_context_snapshot
from terminal.api.memory_extraction import _bg_extract_api, _do_extract_api
from terminal.api.turn_receipt import empty_reply_events, memory_compaction_events

logger = logging.getLogger("archer_api")
MODEL_STREAM_HEARTBEAT_SECONDS = 8.0
MODEL_STREAM_TOTAL_TIMEOUT_SECONDS = 180.0
HUGO_WORKFLOW_HEARTBEAT_SECONDS = 8.0
HUGO_WORKFLOW_TOTAL_TIMEOUT_SECONDS = 300.0

from terminal.api.part8_runtime import (
    _initiative_event_from_log,
    _record_part8_shadow_material,
    _yield_shadow_initiative_events,
)


from terminal.api.runtime_context import build_route_runtime_context as _runtime_context_event


def _failure_hint_event(exc: Exception, *, stage: str, trace_id: str = "") -> dict:
    detail = str(exc)[:300] or type(exc).__name__
    lowered = detail.lower()
    # B6.1: provider 连接/鉴权/限流失败 → provider_connection_failed keyword
    # _connection_hint 抛 "无法连接 LLM API"，_status_hint 抛 "模型 API 鉴权失败/额度受限"
    is_llm_stage = stage in ("model_stream", "llm", "call_with_tools")
    is_provider_error = (
        "无法连接" in str(exc)
        or "llm api" in lowered
        or "模型 api" in lowered
        or "连接" in str(exc)
        or "timeout" in lowered
        or "connect" in lowered
    )
    if is_llm_stage and is_provider_error:
        keyword = "provider_connection_failed"
        recoverable = True
    elif "timeout" in lowered or "connect" in lowered:
        keyword = "command_timeout"
        recoverable = True
    elif "permission" in lowered or "denied" in lowered:
        keyword = "write_permission"
        recoverable = False
    elif "not found" in lowered or "no such file" in lowered or "missing" in lowered:
        keyword = "dependency_missing"
        recoverable = True
    elif "syntax" in lowered or "parse" in lowered or "json" in lowered:
        keyword = "syntax_mismatch"
        recoverable = True
    else:
        keyword = "runtime_failure"
        recoverable = True
    return {
        "id": f"failure-hint-{uuid4().hex[:8]}",
        "traceId": trace_id,
        "keyword": keyword,
        "stage": stage,
        "recoverable": recoverable,
        "detail": detail,
    }


def _with_trace_id(event: dict, trace_id: str) -> dict:
    if not trace_id or not isinstance(event, dict):
        return event
    event_type = event.get("type")
    payload_keys = {
        "tool_event": "toolEvent",
        "orchestrationEvent": "orchestrationEvent",
        "planEvent": "planEvent",
        "runtimeContextEvent": "runtimeContextEvent",
        "statusEvent": "statusEvent",
        "initiativeEvent": "initiativeEvent",
        "failureHintEvent": "failureHintEvent",
    }
    payload_key = payload_keys.get(str(event_type))
    payload = event.get(payload_key) if payload_key else None
    if isinstance(payload, dict):
        payload.setdefault("traceId", trace_id)
        if payload_key == "toolEvent" and isinstance(payload.get("draft"), dict):
            payload["draft"].setdefault("traceId", trace_id)
    return event


# ---------------------------------------------------------------------------
# Intent detection helpers（委托 core/desktop_tool_router，保留旧函数名兼容测试）
# ---------------------------------------------------------------------------

from core.desktop_tool_router import (
    extract_github_args as _extract_github_args,
    extract_obsidian_target_path as _extract_obsidian_target_path,
    extract_shell_command as _extract_shell_command,
    filter_skills_for_intent as _filter_skills_for_intent,
    parse_obsidian_write_request as _parse_obsidian_write_request,
    plan_desktop_turn as _plan_desktop_turn,
    plan_desktop_tools as _plan_desktop_tools,
    should_draft_obsidian_write as _should_draft_obsidian_write,
    should_preview_obsidian as _should_preview_obsidian,
    should_trigger_github as _should_trigger_github,
    should_trigger_shell as _should_trigger_shell,
    wants_hugo_creation as _wants_hugo_creation,
    wants_hugo_deploy as _wants_hugo_deploy,
    wants_hugo_publish as _wants_hugo_publish,
)


# ---------------------------------------------------------------------------
# Shared API tool helper compatibility facade
# ---------------------------------------------------------------------------

from terminal.api.api_tool_helpers import (
    _execute_api_tool_preview,
    _execute_shell_command,
    _expert_scoped_skills,
    _filter_api_skills_for_intent,
    _is_dangerous_shell,
    _make_api_tool_request,
    _obsidian_work_intent,
    _obsidian_write_draft,
    _select_api_skills,
    _tool_event,
    _tool_event_from_request,
    _tool_event_from_result,
)


# ---------------------------------------------------------------------------
# Hugo workflow compatibility facade
# ---------------------------------------------------------------------------

from terminal.api.hugo_workflow import (
    _collect_hugo_markdown_sources,
    _extract_frontmatter_hints,
    _extract_md_path_from_query,
    _extract_md_paths_from_text,
    _format_hugo_chat_summary,
    _hugo_confirmation_result,
    _hugo_workflow_event,
    _parse_markdown_for_hugo,
    _read_md_source,
    _run_hugo_agent_turn,
    _run_hugo_publish_workflow,
    _try_direct_hugo_delete,
    _try_direct_hugo_deploy_existing,
    _try_direct_hugo_publish,
    _try_direct_hugo_redeploy_with_attachment,
    _wants_hugo_delete,
)


# ---------------------------------------------------------------------------
# Desktop tool execution compatibility facade
# ---------------------------------------------------------------------------

from terminal.api.desktop_tool_execution import (
    _API_TOOL_EVENT_BUILDERS,
    _append_obsidian_draft,
    _execute_github_operation,
    _generate_hugo_draft_from_reply,
    _generate_obsidian_draft_with_ai,
    _iter_api_tool_events,
    _iter_github_events,
    _iter_hugo_blog_events,
    _iter_obsidian_read_events,
    _iter_obsidian_search_events,
    _iter_obsidian_write_events,
    _iter_shell_events,
    _run_desktop_tool_loop,
)


def _file_reference_context(
    file_refs: list[dict],
    per_file_limit: int = 6000,
    total_limit: int = 12000,
    max_file_bytes: int = 1_000_000,
) -> tuple[str, list[dict]]:
    return file_reference_context(
        file_refs,
        event_factory=_tool_event,
        allowed_extensions=TEXT_FILE_EXTENSIONS,
        per_file_limit=per_file_limit,
        total_limit=total_limit,
        max_file_bytes=max_file_bytes,
    )


# ---------------------------------------------------------------------------
# Simple chat (non-streaming)
# ---------------------------------------------------------------------------

def _chat(payload: dict) -> dict:
    messages = _clean_chat_messages(payload.get("messages"))
    from core.llm import stream_chat
    chunks: list[str] = []
    for chunk in stream_chat(messages):
        chunks.append(chunk)
    return {"role": "assistant", "text": "".join(chunks)}


# ---------------------------------------------------------------------------
# Background memory extraction
# ---------------------------------------------------------------------------

def _yield_memory_compaction_events():
    from core.orchestrator import maybe_run_memory_compaction_after_turn
    yield from memory_compaction_events(
        compact=maybe_run_memory_compaction_after_turn,
        event_factory=_tool_event,
        warn=lambda detail: logger.warning("[memory] compaction failed: %s", detail),
    )


def _soul_insight_for_orchestration() -> dict:
    try:
        from core.orchestrator import collect_soul_insight_context

        return collect_soul_insight_context(limit=3)
    except Exception:
        return {}


def _full_turn_dependencies() -> FullTurnDependencies:
    from core.context import resolve_context_limits
    from core.experts import active_expert, active_expert_id, expert_skill_allowlist, format_expert_block

    return FullTurnDependencies(
        classify=classify_turn,
        orchestrate=orchestrate_turn,
        soul_insight=_soul_insight_for_orchestration,
        resolve_limits=resolve_context_limits,
        load_config=_load_config,
        active_expert=active_expert,
        active_expert_id=active_expert_id,
        expert_allowlist=expert_skill_allowlist,
        format_expert=format_expert_block,
        scoped_skills=_expert_scoped_skills,
        select_tools=lambda query, scoped_skills, **kwargs: select_turn_tools(
            query, scoped_skills, planner=_plan_desktop_turn, **kwargs,
        ),
        decide=__import__("core.turn_decision", fromlist=["decide_turn"]).decide_turn,
        shadow_events=_yield_shadow_initiative_events,
        file_context=_file_reference_context,
        vault=assemble_vault_focus,
        memory=assemble_memory_context,
        obsidian=assemble_obsidian_context,
        web=assemble_web_context,
        event_factory=_tool_event,
        trace_event=_with_trace_id,
        runtime_event=_runtime_context_event,
        extract_obsidian_path=_extract_obsidian_target_path,
    )


def _hugo_turn_dependencies() -> HugoTurnDependencies:
    return HugoTurnDependencies(
        delete=_try_direct_hugo_delete,
        redeploy=lambda query, refs, messages: _try_direct_hugo_redeploy_with_attachment(
            query, refs, messages=messages,
        ),
        deploy_existing=_try_direct_hugo_deploy_existing,
        publish=lambda query, refs, messages: _try_direct_hugo_publish(
            query, refs, messages=messages,
        ),
        agent=lambda messages, query, refs, authorized_action: _run_hugo_agent_turn(
            messages, query, file_refs=refs, authorized_action=authorized_action,
        ),
        trace_event=_with_trace_id,
        failure_hint=_failure_hint_event,
    )


def _chat_reply_dependencies() -> ChatReplyDependencies:
    return ChatReplyDependencies(
        select_model=select_model_for_turn,
        load_config=_load_config,
        iter_stream=iter_model_stream,
        iter_rescue=iter_rescue_stream,
        has_fake_markup=_has_fake_xml,
        split_safe_chunk=_split_safe_model_chunk,
        failure_events=lambda exc, *, trace_id: stream_failure_events(
            exc,
            trace_id=trace_id,
            hint_factory=_failure_hint_event,
        ),
        empty_events=empty_reply_events,
        model_trace=model_trace_metadata,
        fallback_factory=default_profile_fallback,
        token_context=token_context_snapshot,
    )


def _post_reply_draft_dependencies() -> PostReplyDraftDependencies:
    def compute_preview(payload: dict) -> dict:
        from skills.obsidian_write import compute_preview as preview

        return preview(payload)

    def execute_request(request: dict) -> dict:
        from core.api_tool_service import execute_tool_request
        from skills.loader import load_skills

        return execute_tool_request(request, load_skills(), cfg=_load_config())

    return PostReplyDraftDependencies(
        parse_obsidian=_parse_obsidian_write_request,
        generate_obsidian=_generate_obsidian_draft_with_ai,
        compute_preview=compute_preview,
        generate_hugo=_generate_hugo_draft_from_reply,
        make_request=_make_api_tool_request,
        event_from_request=_tool_event_from_request,
        set_draft=set_tool_draft,
        execute_request=execute_request,
        tool_event=_tool_event,
        obsidian_work_intent=_obsidian_work_intent,
    )


# ---------------------------------------------------------------------------
# Streaming chat with tool events
# ---------------------------------------------------------------------------

def _iter_simple_chat_path(
    messages: list[dict],
    *,
    query: str,
    intent_info: dict,
    file_refs: list[dict] | None,
    trace_id: str,
    memory_mode: str,
    obsidian_mode: str,
    runtime_context=None,
):
    """B5.1 simple path：轻量闲聊跳过 orchestration/router/memory/vault/tool_loop。

    只做：
    1. yield ready + 最小化 statusEvent
    2. 构建 enriched_messages（messages + file_context + vault focus）
    3. 构建简化 model_messages（core_persona + stance，无 task_plan/mode_constraint/matched_skills）
    4. 主模型 stream + heartbeat + DSML 救援 + fallback
    5. yield done
    """
    _cfg = _load_config()
    from core.experts import active_expert, format_expert_block, active_expert_id
    _expert = active_expert(_cfg)
    _expert_block = format_expert_block(_expert)

    # shadow initiative events（被动扫描，开销小，simple path 保留）
    for event in _yield_shadow_initiative_events(runtime_context):
        yield event

    # ready 信号
    yield {"type": "ready", "ready": True}

    # 最小化 statusEvent（让 UI 有锚点，不丢状态契约）
    yield _with_trace_id({
        "type": "statusEvent",
        "statusEvent": {
            "intentType": "chat",
            "intentLabel": intent_info.get("intent_label", "闲聊"),
            "matchedSkills": [],
            "isBackground": False,
            "memoryScope": [],
            "expertId": active_expert_id(_cfg),
            "expertLabel": str(_expert.get("label", "")),
            "traceId": trace_id,
            "simplePath": True,  # 标识 simple path，UI 可选简化渲染
        },
    }, trace_id)

    # enriched_messages = messages + file_context + vault focus
    enriched_messages = list(messages)
    file_context, file_events = _file_reference_context(file_refs or [])
    for event in file_events:
        yield event
    if file_context:
        enriched_messages = [{"role": "system", "content": file_context}, *enriched_messages]
    vault_result = assemble_vault_focus(
        enriched_messages,
        obsidian_mode=obsidian_mode,
        event_factory=_tool_event,
        include_tool_receipt=False,
    )
    enriched_messages = vault_result.messages
    yield from vault_result.events

    prior_history = messages[:-1] if messages and messages[-1].get("role") == "user" else messages
    memory_result = assemble_memory_context(
        enriched_messages,
        query=query,
        prior_history=prior_history,
        intent="chat",
        needs_memory=bool(intent_info.get("needs_memory")),
        memory_mode=memory_mode,
        retrieve_limit=6,
        expert=_expert,
        event_factory=_tool_event,
    )
    enriched_messages = memory_result.messages
    yield from memory_result.events
    from core.persona_sources import persona_source_status
    yield _with_trace_id(build_memory_context_event(
        trace_id=trace_id,
        intent="chat",
        persona_injected=persona_source_status(_cfg)["injected"],
        prior_history=prior_history,
        messages=messages,
        retrieval_receipt=memory_result.receipt,
    ), trace_id)

    # 构建 system prompt（简化版：core_persona + stance + expert_block，无 task_plan）
    try:
        from core.context import build_desktop_core_prompt, _get_mode_prompt
        core_persona = build_desktop_core_prompt()
        stance_prompt = ""
        if _cfg["persona"].get("mode_auto", True):
            # simple path 不跑 orchestration，stance 用默认
            pass
        else:
            current_mode = _cfg["persona"].get("current_mode")
            if current_mode:
                stance_prompt = _get_mode_prompt(_cfg, current_mode)
        if stance_prompt:
            core_persona = f"{core_persona}\n\n{stance_prompt}"
        if _expert_block:
            core_persona = f"{core_persona}\n\n{_expert_block}"
    except Exception:
        core_persona = "Archer 的核心身份是长期陪伴型 AI 灵魂伴生体。"

    model_messages = assemble_model_messages(
        enriched_messages,
        core_persona=core_persona,
        simple=True,
    )
    yield {"type": "_metric", "stage": "context_ready", "traceId": trace_id}

    yield from iter_chat_reply_events(
        model_messages,
        query=query,
        intent="chat",
        file_refs=file_refs,
        selected_tools={},
        memory_scope=[],
        trace_id=trace_id,
        had_tool_activity=False,
        runtime_context=runtime_context,
        dependencies=_chat_reply_dependencies(),
        heartbeat_seconds=MODEL_STREAM_HEARTBEAT_SECONDS,
        total_timeout_seconds=MODEL_STREAM_TOTAL_TIMEOUT_SECONDS,
    )

    yield {"type": "done", "done": True}

def _iter_chat_chunks(
    messages: list[dict],
    memory_mode: str = "conservative",
    obsidian_mode: str = "summary",
    file_refs: list[dict] | None = None,
    runtime_context=None,
):
    from terminal.api.turn_metrics import instrument_turn_events

    yield from instrument_turn_events(_iter_chat_chunks_impl(
        messages,
        memory_mode=memory_mode,
        obsidian_mode=obsidian_mode,
        file_refs=file_refs,
        runtime_context=runtime_context,
    ))


def _iter_chat_chunks_impl(
    messages: list[dict],
    memory_mode: str = "conservative",
    obsidian_mode: str = "summary",
    file_refs: list[dict] | None = None,
    runtime_context=None,
):
    from core.llm import stream_chat

    classified_turn = classify_turn(messages)
    query = classified_turn.query
    file_refs = merge_inline_markdown_refs(query, file_refs)
    trace_id = f"trace-{uuid4().hex[:12]}"
    yield {"type": "_metric", "stage": "trace_started", "traceId": trace_id}
    _record_part8_shadow_material(messages, runtime_context)
    # 历史（不含当前这条用户消息），用于历史感知意图与检索改写
    prior_history = classified_turn.prior_history
    intent_info = classified_turn.intent_info
    # ── B5.1: simple path 分叉（轻量闲聊跳过 orchestration/router/memory/vault/tool_loop） ──
    try:
        from core.desktop_tool_router import is_simple_chat_path
        if is_simple_chat_path(query, intent_info, file_refs=file_refs):
            yield from _iter_simple_chat_path(
                messages, query=query, intent_info=intent_info,
                file_refs=file_refs, trace_id=trace_id,
                memory_mode=memory_mode, obsidian_mode=obsidian_mode,
                runtime_context=runtime_context,
            )
            return
    except Exception:
        pass  # simple path 判定异常 → 回退到 full path
    prepared_turn = prepare_full_turn(
        messages,
        memory_mode=memory_mode,
        obsidian_mode=obsidian_mode,
        file_refs=file_refs,
        runtime_context=runtime_context,
        trace_id=trace_id,
        dependencies=_full_turn_dependencies(),
        classified_turn=classified_turn,
    )
    yield {"type": "_metric", "stage": "context_ready", "traceId": trace_id}
    query = prepared_turn.query
    prior_history = prepared_turn.prior_history
    intent_info = prepared_turn.intent_info
    orchestration = prepared_turn.orchestration
    memory_scope = prepared_turn.memory_scope
    context_limits = prepared_turn.context_limits
    _cfg = prepared_turn.config
    _expert = prepared_turn.expert
    _expert_block = prepared_turn.expert_block
    task_plan_block = prepared_turn.task_plan_block
    mode_constraint_block = prepared_turn.mode_constraint_block
    matched_skills_block = prepared_turn.matched_skills_block
    _turn_plan = prepared_turn.turn_plan
    _selected_tools = prepared_turn.selected_tools
    _tool_plan = prepared_turn.tool_plan
    _turn_decision = prepared_turn.turn_decision
    intent = intent_info["intent"]
    enriched_messages = prepared_turn.enriched_messages
    for event in prepared_turn.events:
        yield event
    # 动态对话姿态：优先使用 orchestrator 的 mode；手动锁定时让位
    active_stance = orchestration.mode if orchestration else None
    stance_prompt = ""
    try:
        from core.context import _get_mode_prompt
        if not _cfg["persona"].get("mode_auto", True):
            active_stance = _cfg["persona"].get("current_mode") or active_stance
        if active_stance:
            stance_prompt = _get_mode_prompt(_cfg, active_stance)
    except Exception:
        active_stance = None
        stance_prompt = ""
    from terminal.api.action_mediation_stage import run_action_mediation

    def run_hugo(authorized_action: str):
        return iter_hugo_turn_events(
            query=query,
            file_refs=file_refs,
            messages=enriched_messages,
            intent=intent,
            selected_tools=_selected_tools,
            memory_scope=memory_scope,
            trace_id=trace_id,
            dependencies=_hugo_turn_dependencies(),
            heartbeat_seconds=HUGO_WORKFLOW_HEARTBEAT_SECONDS,
            total_timeout_seconds=HUGO_WORKFLOW_TOTAL_TIMEOUT_SECONDS,
            authorized_action=authorized_action,
        )

    mediated = run_action_mediation(
        _turn_decision, query, _selected_tools, enriched_messages, trace_id,
        run_hugo=run_hugo, delete=_try_direct_hugo_delete,
        make_request=_make_api_tool_request, set_draft=set_tool_draft,
        event_from_request=_tool_event_from_request,
    )
    enriched_messages = mediated.enriched_messages
    pre_model_tool_events = mediated.tool_events
    yield _with_trace_id({
        "type": "runtimeContextEvent",
        "runtimeContextEvent": mediated.runtime_event,
    }, trace_id)

    api_tool_events = list(_iter_api_tool_events(query, turn_plan=_turn_plan))

    # ── Desktop Tool Loop：让 LLM 通过 function calling 自主调用未被专用 builder 覆盖的技能 ──
    _all_selected = _selected_tools
    if _all_selected:
        enriched_messages, tool_loop_events = _run_desktop_tool_loop(
            enriched_messages, _all_selected, query,
        )
    else:
        tool_loop_events = []
    tool_loop_events = [*pre_model_tool_events, *tool_loop_events]
    for event in tool_loop_events:
        yield _with_trace_id(event, trace_id)

    # ── 预检工具事件（Shell / GitHub / Obsidian 搜索） ──
    for event in api_tool_events:
        yield _with_trace_id(event, trace_id)

    def resolve_obsidian_event_path(path: str) -> str:
        from skills.obsidian_write import _resolve_note_path
        return str(_resolve_note_path(path))

    tool_summary = summarize_api_tool_events(
        api_tool_events,
        resolve_obsidian_path=resolve_obsidian_event_path,
    )
    direct_obsidian_writes = tool_summary.direct_obsidian_writes
    tool_notes = tool_summary.tool_notes

    # ── 通用技能宣告：告诉 LLM 所有被 skill_router 选中但无专用 event builder 的技能 ──
    _AUTO_EXECUTED_SKILLS = {"web_search", "web_fetch"}
    selected_skills = _selected_tools
    for skill_name in sorted(selected_skills):
        if skill_name in _API_TOOL_EVENT_BUILDERS or skill_name in _AUTO_EXECUTED_SKILLS:
            continue  # 已有专用 builder 或已自动执行注入上下文
        # 加载技能的简短描述
        try:
            from skills.loader import load_skills
            all_skills = load_skills()
            mod = all_skills.get(skill_name)
            if mod is None:
                continue
            desc = getattr(mod, 'SKILL', {}).get('description', '') or getattr(mod, '__doc__', '') or ''
            desc = desc.split('\n')[0].strip()[:80]
            if desc:
                skill_label = skill_name.replace('_', ' ')
                tool_notes.append(f"{skill_name} 可用——{desc}")
            else:
                tool_notes.append(f"{skill_name} 可用")
        except Exception:
            pass

    yield {"type": "ready", "ready": True}
    if direct_obsidian_writes:
        if len(direct_obsidian_writes) == 1:
            yield {"type": "token", "text": f"已写入 Obsidian：{direct_obsidian_writes[0]}。"}
        else:
            joined = "、".join(direct_obsidian_writes)
            yield {"type": "token", "text": f"已写入 Obsidian：{joined}。"}
        yield {"type": "done", "done": True}
        return

    # ── 检测 Obsidian 写入意图（非预检，不在此阶段弹草稿卡） ──
    obsidian_write_intent = _tool_plan.obsidian_write
    obsidian_target_path = _parse_obsidian_write_request(query).path if obsidian_write_intent else None

    # ── 构建 AI 系统提示词 ──
    # 想法3：桌面端与终端共用完整灵魂分层（COVENANT/PRESENCE/SOUL/MEMORY/mode/对峙提醒），
    # 并按桌面渲染允许 Markdown。记忆检索结果仍由上方 enriched_messages 单独注入，
    # 因此这里 db_memories 留空，避免重复。
    try:
        from core.context import build_system_prompt
        from memory.narrative import confrontation_hook
        from memory.emotion import infer_turn_emotion_hint
        from core.thread import resolve_topic_thread
        try:
            hints = confrontation_hook(query, prior_history)
        except Exception:
            hints = None
        emotion_hint = infer_turn_emotion_hint(query, prior_history)
        thread_hint = resolve_topic_thread(query, prior_history)
        core_persona = build_system_prompt(
            _cfg,
            db_memories="",
            heavy=intent_info["needs_memory"],
            intent=intent,
            user_input=query,
            confrontation_hints=hints or None,
            mode_override=active_stance,
            emotion_hint=emotion_hint,
            thread_hint=thread_hint,
            memory_scope=memory_scope,
            task_plan_block=task_plan_block,
            mode_constraint_block=mode_constraint_block,
            matched_skills_block=matched_skills_block,
            expert_block=_expert_block,
            needs_project_context=(
                orchestration.needs_project_context if orchestration else None
            ),
            context_limits=context_limits,
        )
    except Exception:
        try:
            from core.context import build_desktop_core_prompt
            core_persona = build_desktop_core_prompt()
            if stance_prompt:
                core_persona = f"{core_persona}\n\n{stance_prompt}"
        except Exception:
            core_persona = "Archer 的核心身份是长期陪伴型 AI 灵魂伴生体。"

    obsidian_hint = ""
    if obsidian_write_intent:
        obsidian_hint = (
            "\n\n用户希望写入 Obsidian，你需要在回复中整理要点，"
            "并告知用户回复完成后客户端会自动生成写入草稿卡片，用户点击「写入」后才会真正执行。"
            f"当前识别到的目标路径：{obsidian_target_path or '（待确认）'}。"
        )
    model_messages = assemble_model_messages(
        enriched_messages,
        core_persona=core_persona,
        tool_notes=tool_notes,
        obsidian_hint=obsidian_hint,
    )

    ai_reply = yield from iter_chat_reply_events(
        model_messages,
        query=query,
        intent=intent,
        file_refs=file_refs,
        selected_tools=_selected_tools,
        memory_scope=memory_scope,
        trace_id=trace_id,
        had_tool_activity=bool(tool_loop_events or api_tool_events),
        runtime_context=runtime_context,
        dependencies=_chat_reply_dependencies(),
        heartbeat_seconds=MODEL_STREAM_HEARTBEAT_SECONDS,
        total_timeout_seconds=MODEL_STREAM_TOTAL_TIMEOUT_SECONDS,
    )
    if ai_reply is None:
        return

    hugo_blog_triggered = (
        not _wants_hugo_publish(query, file_refs)
        and any(
            isinstance(e, dict) and e.get("toolEvent", {}).get("name") == "hugo_blog"
            for e in api_tool_events
        )
    )
    yield from iter_post_reply_draft_events(
        query=query,
        messages=enriched_messages,
        ai_reply=ai_reply,
        obsidian_write_intent=obsidian_write_intent,
        obsidian_target_path=obsidian_target_path,
        hugo_blog_triggered=hugo_blog_triggered,
        dependencies=_post_reply_draft_dependencies(),
    )

    for event in _yield_memory_compaction_events():
        yield event

    yield {"type": "done", "done": True}
