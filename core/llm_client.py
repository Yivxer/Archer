"""Injectable LLM client contract and the legacy core.llm adapter."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol


class LLMClient(Protocol):
    def chat(self, messages: list[dict], **kwargs) -> str: ...

    def stream_chat(self, messages: list[dict], **kwargs) -> Iterator[str]: ...


class DefaultLLMClient:
    """Resolve core.llm lazily so construction has no network side effects."""

    def stream_chat(self, messages: list[dict], **kwargs) -> Iterator[str]:
        from core.llm import stream_chat

        return stream_chat(messages, **kwargs)

    def chat(self, messages: list[dict], **kwargs) -> str:
        return "".join(self.stream_chat(messages, **kwargs))

    def load_config(self) -> dict:
        from core.llm import load_config

        return load_config()
