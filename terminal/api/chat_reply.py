"""Model reply delivery stage for Desktop chat turns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from uuid import uuid4


@dataclass(frozen=True)
class ChatReplyDependencies:
    select_model: Callable
    load_config: Callable
    iter_stream: Callable
    iter_rescue: Callable
    has_fake_markup: Callable
    split_safe_chunk: Callable
    failure_events: Callable
    empty_events: Callable
    model_trace: Callable
    fallback_factory: Callable | None = None
    token_context: Callable | None = None


def iter_chat_reply_events(
    model_messages: list[dict], *, query: str, intent: str, file_refs: list[dict] | None,
    selected_tools, memory_scope, trace_id: str, had_tool_activity: bool,
    runtime_context, dependencies: ChatReplyDependencies,
    heartbeat_seconds: float = 8.0, total_timeout_seconds: float = 180.0,
):
    config = dependencies.load_config()
    active_model = dependencies.select_model(
        config,
        query=query,
        intent=intent,
        needs_tools=bool(selected_tools),
        file_refs=file_refs,
    )
    yield {
        "type": "runtimeContextEvent",
        "runtimeContextEvent": {
            "id": f"model-context-{uuid4().hex[:8]}",
            "traceId": trace_id,
            "task": intent,
            "phase": "model_stream",
            "userIntent": intent,
            "lastResult": "model_selected",
            "expectedNext": "stream_model_reply",
            **dependencies.model_trace(config, active_model),
        },
    }
    llm_client = getattr(runtime_context, "llm_client", None)
    fallback_stream = None
    fallback_model = ""
    fallback_profile = ""
    if llm_client is None and dependencies.fallback_factory is not None:
        fallback_stream, fallback_model, fallback_profile = dependencies.fallback_factory(
            config, active_model,
        )
    if dependencies.token_context is not None:
        yield {
            "type": "_metric", "stage": "token_context", "traceId": trace_id,
            **dependencies.token_context(model_messages),
        }
    reply_parts: list[str] = []
    streamed_safe_text = ""
    fake_markup_detected = False
    try:
        for item in dependencies.iter_stream(
            model_messages,
            heartbeat_seconds=heartbeat_seconds,
            total_timeout_seconds=total_timeout_seconds,
            model=active_model,
            llm_client=llm_client,
            fallback_stream=fallback_stream,
            fallback_model=fallback_model,
            fallback_profile=fallback_profile,
        ):
            if item.get("type") == "heartbeat":
                yield {
                    "type": "statusEvent",
                    "statusEvent": {
                        "id": f"model-wait-{uuid4().hex[:8]}",
                        "intentType": intent,
                        "intentLabel": "模型响应中",
                        "matchedSkills": list(selected_tools.keys()),
                        "isBackground": False,
                        "memoryScope": memory_scope,
                        "traceId": trace_id,
                    },
                }
                continue
            if item.get("type") in {"retry", "fallback"}:
                is_fallback = item.get("type") == "fallback"
                yield {
                    "type": "statusEvent",
                    "statusEvent": {
                        "id": f"model-{'fallback' if is_fallback else 'retry'}-{uuid4().hex[:8]}",
                        "intentType": intent,
                        "intentLabel": "正在切换默认模型" if is_fallback else "模型连接不稳，正在重试",
                        "matchedSkills": list(selected_tools.keys()),
                        "isBackground": False,
                        "memoryScope": memory_scope,
                        "traceId": trace_id,
                        "phase": item.get("type"),
                        "attempt": item.get("attempt"),
                        "maxAttempts": item.get("maxAttempts"),
                        "fallbackProfile": item.get("fallbackProfile") or None,
                    },
                }
                continue
            if item.get("type") == "usage":
                yield {
                    "type": "_metric", "stage": "token_usage", "traceId": trace_id,
                    "tokenUsage": item.get("tokenUsage") or {},
                }
                continue
            chunk = str(item.get("text") or "")
            if not chunk:
                continue
            reply_parts.append(chunk)
            if fake_markup_detected:
                continue
            streamed_safe_text, safe_chunk, detected = dependencies.split_safe_chunk(
                streamed_safe_text, chunk,
            )
            if safe_chunk:
                yield {"type": "token", "text": safe_chunk}
            if detected:
                fake_markup_detected = True
    except Exception as exc:
        yield from dependencies.failure_events(exc, trace_id=trace_id)
        return None

    reply = "".join(reply_parts)
    if dependencies.has_fake_markup(reply):
        for item in dependencies.iter_rescue(
            model_messages,
            reply,
            model=active_model,
            heartbeat_seconds=heartbeat_seconds,
            total_timeout_seconds=total_timeout_seconds,
            llm_client=llm_client,
        ):
            if item.get("type") == "heartbeat":
                yield {
                    "type": "statusEvent",
                    "statusEvent": {
                        "id": f"model-rescue-wait-{uuid4().hex[:8]}",
                        "intentType": intent,
                        "intentLabel": "模型修正中",
                        "matchedSkills": list(selected_tools.keys()),
                        "isBackground": False,
                        "memoryScope": memory_scope,
                        "traceId": trace_id,
                    },
                }
            elif item.get("type") == "chunk":
                yield {"type": "token", "text": item["text"]}
            elif item.get("type") == "done" and item.get("text"):
                reply = str(item["text"])
    if not reply.strip():
        yield from dependencies.empty_events(
            had_tool_activity=had_tool_activity,
            trace_id=trace_id,
        )
    return reply
