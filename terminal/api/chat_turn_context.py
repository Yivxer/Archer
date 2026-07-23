"""Full Desktop chat-turn context preparation stage."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable


@dataclass(frozen=True)
class FullTurnDependencies:
    classify: Callable
    orchestrate: Callable
    soul_insight: Callable
    resolve_limits: Callable
    load_config: Callable
    active_expert: Callable
    active_expert_id: Callable
    expert_allowlist: Callable
    format_expert: Callable
    scoped_skills: Callable
    select_tools: Callable
    decide: Callable
    shadow_events: Callable
    file_context: Callable
    vault: Callable
    memory: Callable
    obsidian: Callable
    web: Callable
    event_factory: Callable
    trace_event: Callable
    runtime_event: Callable
    extract_obsidian_path: Callable


@dataclass(frozen=True)
class PreparedFullTurn:
    query: str
    trace_id: str
    intent_info: dict
    prior_history: list[dict]
    orchestration: object | None
    memory_scope: object | None
    context_limits: object
    config: dict
    expert: dict
    expert_block: str
    task_plan_block: str
    mode_constraint_block: str
    matched_skills_block: str
    turn_plan: object
    selected_tools: object
    tool_plan: object
    turn_decision: object
    enriched_messages: list[dict]
    events: list[dict]


def prepare_full_turn(
    messages: list[dict], *, memory_mode: str, obsidian_mode: str,
    file_refs: list[dict] | None, runtime_context, trace_id: str,
    dependencies: FullTurnDependencies, classified_turn=None,
) -> PreparedFullTurn:
    classified = classified_turn or dependencies.classify(messages)
    query = classified.query
    prior_history = classified.prior_history
    intent_info = classified.intent_info
    orchestrated = dependencies.orchestrate(
        query, prior_history, dependencies.soul_insight(),
    )
    orchestration = orchestrated.orchestration
    memory_scope = orchestrated.memory_scope
    intent = intent_info["intent"]
    classifier_needs_tools = bool(intent_info.get("needs_tools"))
    needs_tools = (
        bool(orchestration.needs_tools)
        if orchestration is not None
        else classifier_needs_tools
    )
    context_limits = dependencies.resolve_limits(
        memory_scope,
        needs_memory=bool(intent_info["needs_memory"]),
        memory_mode=memory_mode,
    )
    config = dependencies.load_config()
    expert = dependencies.active_expert(config)
    scoped_skills = dependencies.scoped_skills(config)
    selected = dependencies.select_tools(
        query,
        scoped_skills,
        intent=intent,
        needs_tools=needs_tools,
    )
    events = list(dependencies.shadow_events(runtime_context))
    enriched_messages = list(messages)

    file_context, file_events = dependencies.file_context(file_refs or [])
    events.extend(file_events)
    if file_context:
        enriched_messages = [{"role": "system", "content": file_context}, *enriched_messages]
    candidate_skills = list(getattr(selected.turn_plan, "raw_selected", {}) or {})
    if file_context or "hugo_blog" in candidate_skills:
        turn_decision = dependencies.decide(
            query, file_context=file_context, candidate_capabilities=candidate_skills,
        )
    else:
        from core.turn_decision import default_conversation_decision
        turn_decision = default_conversation_decision(query)
    selected_tools = dict(selected.selected_tools)
    if getattr(turn_decision, "handling", "") != "execute_action":
        selected_tools.pop("hugo_blog", None)
    elif any(getattr(action, "capability", "") == "hugo_blog" for action in turn_decision.action_requests):
        raw_selected = getattr(selected.turn_plan, "raw_selected", {}) or {}
        if "hugo_blog" in raw_selected:
            selected_tools["hugo_blog"] = raw_selected["hugo_blog"]
    if orchestration is not None:
        try:
            orchestration = replace(orchestration, turn_decision=turn_decision)
        except TypeError:
            pass

    vault_result = dependencies.vault(
        enriched_messages,
        obsidian_mode=obsidian_mode,
        event_factory=dependencies.event_factory,
        include_tool_receipt=True,
    )
    enriched_messages = vault_result.messages
    events.extend(
        dependencies.trace_event(event, trace_id) if event.get("toolEvent") else event
        for event in vault_result.events
    )
    if orchestrated.orchestration_event:
        events.append(dependencies.trace_event({
            "type": "orchestrationEvent",
            "orchestrationEvent": orchestrated.orchestration_event,
        }, trace_id))
    if orchestrated.plan_event:
        events.append(dependencies.trace_event({
            "type": "planEvent", "planEvent": orchestrated.plan_event,
        }, trace_id))
    if orchestration is not None:
        events.append(dependencies.trace_event({
            "type": "runtimeContextEvent",
            "runtimeContextEvent": dependencies.runtime_event(
                query=query,
                intent_info=intent_info,
                orchestration=orchestration,
                file_refs=file_refs,
                trace_id=trace_id,
                turn_decision=turn_decision,
            ),
        }, trace_id))
        matched_skills = list(orchestration.matched_skills)
        allowlist = dependencies.expert_allowlist(expert)
        if allowlist:
            matched_skills = [name for name in matched_skills if name in allowlist]
        events.append(dependencies.trace_event({
            "type": "statusEvent",
            "statusEvent": {
                "intentType": intent,
                "intentLabel": intent_info.get("intent_label", intent),
                "matchedSkills": matched_skills,
                "isBackground": orchestration.needs_job,
                "memoryScope": list(orchestration.memory_scope),
                "expertId": dependencies.active_expert_id(config),
                "expertLabel": str(expert.get("label", "")),
            },
        }, trace_id))

    memory_result = dependencies.memory(
        enriched_messages,
        query=query,
        prior_history=prior_history,
        intent=intent,
        needs_memory=bool(intent_info["needs_memory"]),
        memory_mode=memory_mode,
        retrieve_limit=context_limits.retrieve_total,
        expert=expert,
        event_factory=dependencies.event_factory,
    )
    enriched_messages = memory_result.messages
    events.extend(memory_result.events)
    from core.persona_sources import persona_source_status
    from terminal.api.context_assembly import build_memory_context_event

    events.append(dependencies.trace_event(build_memory_context_event(
        trace_id=trace_id,
        intent=intent,
        persona_injected=persona_source_status(config)["injected"],
        prior_history=prior_history,
        messages=messages,
        retrieval_receipt=getattr(memory_result, "receipt", {}) or {},
    ), trace_id))
    obsidian_result = dependencies.obsidian(
        enriched_messages,
        query=query,
        obsidian_mode=obsidian_mode,
        preview_requested=bool(selected.tool_plan.obsidian_preview),
        event_factory=dependencies.event_factory,
        extract_target_path=dependencies.extract_obsidian_path,
    )
    enriched_messages = obsidian_result.messages
    events.extend(obsidian_result.events)
    web_result = dependencies.web(
        enriched_messages,
        query=query,
        selected_tools=selected.selected_tools,
        event_factory=dependencies.event_factory,
        trace_event=lambda event: dependencies.trace_event(event, trace_id),
    )
    enriched_messages = web_result.messages
    events.extend(web_result.events)
    return PreparedFullTurn(
        query=query,
        trace_id=trace_id,
        intent_info=intent_info,
        prior_history=prior_history,
        orchestration=orchestration,
        memory_scope=memory_scope,
        context_limits=context_limits,
        config=config,
        expert=expert,
        expert_block=dependencies.format_expert(expert),
        task_plan_block=orchestrated.task_plan_block,
        mode_constraint_block=orchestrated.mode_constraint_block,
        matched_skills_block=orchestrated.matched_skills_block,
        turn_plan=selected.turn_plan,
        selected_tools=selected_tools,
        tool_plan=selected.tool_plan,
        turn_decision=turn_decision,
        enriched_messages=enriched_messages,
        events=events,
    )
