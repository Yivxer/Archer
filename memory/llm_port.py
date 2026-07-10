"""Injected LLM port used by memory-domain analysis helpers."""
from __future__ import annotations

from typing import Any


_client: Any | None = None


def configure_llm_client(client: Any) -> None:
    global _client
    if client is None:
        raise ValueError("llm client is required")
    if not callable(client) and not callable(getattr(client, "stream_chat", None)):
        raise TypeError("llm client must be callable or expose stream_chat")
    _client = client


def stream_chat(*args, **kwargs):
    client = _client
    if client is None:
        raise RuntimeError("memory LLM port is not configured")
    method = getattr(client, "stream_chat", None)
    if callable(method):
        return method(*args, **kwargs)
    return client(*args, **kwargs)


def load_config() -> dict:
    client = _client
    method = getattr(client, "load_config", None) if client is not None else None
    if not callable(method):
        return {}
    value = method()
    return value if isinstance(value, dict) else {}
