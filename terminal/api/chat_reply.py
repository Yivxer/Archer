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


def iter_chat_reply_events(
    model_messages: list[dict], *, query: str, intent: str, file_refs: list[dict] | None,
    selected_tools, memory_scope, trace_id: str, had_tool_activity: bool,
    runtime_context, dependencies: ChatReplyDependencies,
    heartbeat_seconds: float = 8.0, total_timeout_seconds: float = 180.0,
):
    active_model = dependencies.select_model(
        dependencies.load_config(),
        query=query,
        intent=intent,
        needs_tools=bool(selected_tools),
        file_refs=file_refs,
    )
    llm_client = getattr(runtime_context, "llm_client", None)
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
