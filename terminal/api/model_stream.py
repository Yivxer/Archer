"""Model streaming stage with deterministic heartbeat and timeout events."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Iterator


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
