"""Behavior-preserving background memory extraction stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import threading

from core.event_bus import ArcherEvent, TURN_RECEIPT_READY
from core.runtime_context import RuntimeContext
from terminal.api.turn_receipt import MemoryExtractionScheduler


logger = logging.getLogger(__name__)
_memory_extraction_scheduler = MemoryExtractionScheduler()


@dataclass
class MemoryExtractionPorts:
    extract: Callable
    save: Callable
    add_pending: Callable
    is_duplicate: Callable[[str], bool]
    is_low_quality: Callable[[str, str], bool]


@dataclass(frozen=True)
class MemoryExtractionResult:
    saved: int = 0
    staged: int = 0
    skipped_duplicate: int = 0
    skipped_low_quality: int = 0
    skip_reason: str = ""


class MemoryExtractionSubscriber:
    def __init__(self, runtime_context: RuntimeContext, *, schedule: Callable) -> None:
        self._runtime_context = runtime_context
        self._schedule = schedule
        self._seen_receipts: set[str] = set()
        self._lock = threading.Lock()
        self._subscribed = False

    def subscribe(self) -> None:
        if self._subscribed:
            return
        self._runtime_context.event_bus.subscribe(TURN_RECEIPT_READY, self)
        self._subscribed = True

    def __call__(self, event: ArcherEvent) -> None:
        receipt_id = str(event.payload.get("receiptId", "") or "")
        if not receipt_id:
            return
        with self._lock:
            if receipt_id in self._seen_receipts:
                return
            self._seen_receipts.add(receipt_id)
        try:
            history = list(event.payload.get("history") or [])
            self._schedule(history, self._runtime_context)
        except Exception as exc:
            logger.warning("[memory] receipt subscriber failed: %s", exc)


def publish_memory_extraction_receipt(
    runtime_context: RuntimeContext,
    history: list[dict],
    *,
    receipt_id: str,
    trace_id: str = "",
    receipt: dict | None = None,
) -> ArcherEvent:
    return runtime_context.event_bus.publish(ArcherEvent(
        type=TURN_RECEIPT_READY,
        source="terminal.api.chat_stream",
        payload={
            "receiptId": receipt_id,
            "traceId": trace_id,
            "history": list(history),
            "receipt": dict(receipt or {}),
        },
    ))


def build_runtime_memory_extraction_ports(
    runtime_context: RuntimeContext,
) -> MemoryExtractionPorts:
    from memory.extract import extract
    from memory.store import add_pending, is_duplicate_pending, is_low_quality_memory, save

    return MemoryExtractionPorts(
        extract=lambda history, **kwargs: extract(
            history,
            llm_client=runtime_context.llm_client,
            **kwargs,
        ),
        save=lambda **kwargs: save(**kwargs, db_path=runtime_context.db_path),
        add_pending=lambda **kwargs: add_pending(
            **kwargs,
            db_path=runtime_context.db_path,
        ),
        is_duplicate=lambda content: is_duplicate_pending(
            content,
            db_path=runtime_context.db_path,
        ),
        is_low_quality=is_low_quality_memory,
    )


def should_auto_save_memory(memory: dict, sensitive: bool) -> bool:
    """Implicit extraction never bypasses the user's review queue."""
    return False


def _latest_user_text(history: list[dict]) -> str:
    for message in reversed(history):
        if message.get("role") == "user":
            return str(message.get("content", "") or "").strip()
    return ""


def _session_summary(history: list[dict]) -> str:
    for message in history:
        if message.get("role") == "user":
            content = str(message.get("content", "") or "").strip()
            if content:
                return content[:80]
    return ""


def extract_memories(
    history: list[dict], *, ports: MemoryExtractionPorts,
    orchestrate: Callable, build_policy: Callable, format_reason: Callable,
) -> MemoryExtractionResult:
    if len(history) < 2:
        return MemoryExtractionResult(skip_reason="history_too_short")

    latest_user = _latest_user_text(history)
    policy = None
    suggest_reason = ""
    if latest_user:
        policy = build_policy(orchestrate(latest_user, history=history[:-1]))
        if not policy.should_extract:
            return MemoryExtractionResult(skip_reason="candidate_policy")
        suggest_reason = format_reason(policy, latest_user)

    extract_kwargs = {}
    if policy:
        extract_kwargs = {
            "candidate_types": policy.candidate_types,
            "sensitive": policy.sensitive,
        }
    memories, _ = ports.extract(history, **extract_kwargs)
    saved = staged = skipped_duplicate = skipped_low_quality = 0
    session_summary = _session_summary(history)

    for memory in memories:
        content = memory.get("content", "")
        memory_type = memory.get("type", "insight")
        if ports.is_low_quality(content, memory_type):
            skipped_low_quality += 1
            continue
        if ports.is_duplicate(content):
            skipped_duplicate += 1
            continue

        common = {
            "content": content,
            "tags": memory.get("tags", ""),
            "type": memory_type,
            "importance": memory.get("importance", 3),
            "source": "desktop",
            "confidence": memory.get("confidence", 0.7),
            "depth": memory.get("depth", 3),
            "block_type": memory.get("block_type"),
            "label": memory.get("label"),
        }
        if should_auto_save_memory(memory, policy.sensitive if policy else False):
            ports.save(**common)
            saved += 1
        else:
            ports.add_pending(
                **common,
                suggest_reason=suggest_reason,
                session_summary=session_summary,
            )
            staged += 1

    return MemoryExtractionResult(
        saved=saved,
        staged=staged,
        skipped_duplicate=skipped_duplicate,
        skipped_low_quality=skipped_low_quality,
    )


def _do_extract_api(history: list[dict], *, runtime_context=None) -> None:
    try:
        from core.orchestrator import (
            build_memory_candidate_policy,
            format_memory_candidate_reason,
            orchestrate_user_input,
        )
        if runtime_context is not None:
            ports = build_runtime_memory_extraction_ports(runtime_context)
        else:
            from memory.extract import extract
            from memory.store import add_pending, is_duplicate_pending, is_low_quality_memory, save
            ports = MemoryExtractionPorts(
                extract=extract,
                save=save,
                add_pending=add_pending,
                is_duplicate=is_duplicate_pending,
                is_low_quality=is_low_quality_memory,
            )
        result = extract_memories(
            history,
            ports=ports,
            orchestrate=orchestrate_user_input,
            build_policy=build_memory_candidate_policy,
            format_reason=format_memory_candidate_reason,
        )
        if result.skip_reason == "candidate_policy":
            logger.info("[memory] desktop extract skipped: no candidate policy")
            return
        logger.info(
            "[memory] desktop extract: saved %d, staged %d, skipped %d dup, %d low-quality",
            result.saved,
            result.staged,
            result.skipped_duplicate,
            result.skipped_low_quality,
        )
    except Exception as exc:
        logger.warning("[memory] desktop extract failed: %s", exc)


def _bg_extract_api(history: list[dict], *, runtime_context=None) -> None:
    target = _do_extract_api
    if runtime_context is not None:
        target = lambda active_history: _do_extract_api(
            active_history,
            runtime_context=runtime_context,
        )
    _memory_extraction_scheduler.schedule(history, target)
