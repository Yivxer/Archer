"""Terminal events emitted after a model turn finishes."""

from __future__ import annotations

from uuid import uuid4
import threading


class MemoryExtractionScheduler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def schedule(self, history: list[dict], target) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._thread = threading.Thread(
                target=target, args=(list(history),), daemon=True,
            )
            self._thread.start()
            return True


def empty_reply_events(*, had_tool_activity: bool, trace_id: str) -> list[dict]:
    return [
        {"type": "token", "text": (
            "已执行操作，详见上方卡片。" if had_tool_activity
            else "模型没有返回内容，请打开诊断查看原因。"
        )},
        {"type": "failureHintEvent", "failureHintEvent": {
            "id": f"failure-hint-{uuid4().hex[:8]}",
            "traceId": trace_id,
            "keyword": "tool_executed_no_summary" if had_tool_activity else "model_empty_response",
            "stage": "model_stream",
            "recoverable": True,
            "detail": (
                "工具事件已产生，但模型没有返回总结文本。" if had_tool_activity
                else "模型请求结束但没有返回可显示文本。"
            ),
        }},
    ]


def memory_compaction_events(*, compact, event_factory, warn=lambda message: None) -> list[dict]:
    try:
        result = compact()
        if not result or result.get("archivedCount", 0) <= 0:
            return []
        return [event_factory(
            f"memory-compact-{uuid4().hex[:8]}", "memory.compact", "complete", "low",
            "已整理记忆",
            f"archived: {result['archivedCount']}, summary_id: {result.get('summaryId')}, reason: {result.get('reason', '')}",
        )]
    except Exception as exc:
        warn(str(exc))
        return []
