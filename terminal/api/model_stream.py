"""Model streaming stage with deterministic heartbeat and timeout events."""

from __future__ import annotations

import queue
import re
import threading
import time
from collections.abc import Callable, Iterator

DSML_MARKER = "｜｜DSML｜｜"
FAKE_XML_RE = re.compile(
    r"<(读取文件|写入文件|搜索文件|文件查找|参数|tool_call|invoke|function_call|execute)[^>]{0,60}>",
    re.IGNORECASE,
)


def has_fake_tool_markup(text: str) -> bool:
    return bool(FAKE_XML_RE.search(text)) or DSML_MARKER in text


def split_safe_model_chunk(buffer: str, chunk: str) -> tuple[str, str, bool]:
    combined = buffer + chunk
    if not has_fake_tool_markup(combined):
        return combined, chunk, False
    earliest = len(combined)
    marker_index = combined.find(DSML_MARKER)
    if marker_index >= 0:
        earliest = min(earliest, marker_index)
    match = FAKE_XML_RE.search(combined)
    if match:
        earliest = min(earliest, match.start())
    safe_combined = combined[:earliest]
    safe_text = safe_combined[len(buffer):] if len(safe_combined) > len(buffer) else ""
    return safe_combined, safe_text, True


def select_model_for_turn(
    config: dict, *, query: str, intent: str, needs_tools: bool,
    file_refs: list[dict] | None, resolver: Callable | None = None,
) -> str:
    if resolver is None:
        from core.model_select import resolve_active_model
        resolver = resolve_active_model
    has_images = bool(file_refs and any(ref.get("type") == "image" for ref in file_refs))
    model, _ = resolver(
        config, user_text=query, intent=intent,
        needs_tools=needs_tools, has_images=has_images,
    )
    return model


def iter_model_stream(
    messages: list[dict], *, heartbeat_seconds: float = 8.0,
    total_timeout_seconds: float = 180.0, stream: Callable | None = None, **kwargs,
) -> Iterator[dict]:
    output: queue.Queue[tuple[str, object]] = queue.Queue()

    def worker() -> None:
        try:
            if stream is None:
                from core.llm import stream_chat
                active_stream = stream_chat
            else:
                active_stream = stream
            for chunk in active_stream(messages, **kwargs):
                output.put(("chunk", chunk))
            output.put(("done", None))
        except Exception as exc:
            output.put(("error", exc))

    threading.Thread(target=worker, daemon=True).start()
    started = time.monotonic()
    while True:
        if time.monotonic() - started > total_timeout_seconds:
            raise TimeoutError("model stream total timeout")
        try:
            kind, value = output.get(timeout=heartbeat_seconds)
        except queue.Empty:
            yield {"type": "heartbeat"}
            continue
        if kind == "chunk":
            yield {"type": "chunk", "text": value}
        elif kind == "error":
            raise value
        else:
            break
