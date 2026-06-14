"""P5.10 — Session token usage tracking."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class CallTokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class SessionTokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    last_call: CallTokenUsage = field(default_factory=CallTokenUsage)


_session = SessionTokenUsage()
_last_call = CallTokenUsage()


def record_call_usage(
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int | None = None,
) -> None:
    """Accumulate one LLM call into the active session counters."""
    global _session, _last_call
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    total = max(0, int(total_tokens if total_tokens is not None else prompt + completion))

    _last_call = CallTokenUsage(prompt, completion, total)
    _session.prompt_tokens += prompt
    _session.completion_tokens += completion
    _session.total_tokens += total
    _session.call_count += 1
    _session.last_call = CallTokenUsage(prompt, completion, total)


def reset_session_usage() -> None:
    global _session, _last_call
    _session = SessionTokenUsage()
    _last_call = CallTokenUsage()


def get_last_call_usage() -> dict[str, int]:
    return asdict(_last_call)


def get_session_usage() -> dict[str, int | dict[str, int]]:
    return {
        "prompt_tokens": _session.prompt_tokens,
        "completion_tokens": _session.completion_tokens,
        "total_tokens": _session.total_tokens,
        "call_count": _session.call_count,
        "last_call": asdict(_session.last_call),
    }


def session_usage_for_file() -> dict[str, int]:
    return {
        "promptTokens": _session.prompt_tokens,
        "completionTokens": _session.completion_tokens,
        "totalTokens": _session.total_tokens,
        "callCount": _session.call_count,
    }


def status_payload(*, token_limit: int) -> dict[str, int | float]:
    total = _session.total_tokens
    limit = max(1, int(token_limit or 1))
    return {
        "sessionTotal": total,
        "sessionPrompt": _session.prompt_tokens,
        "sessionCompletion": _session.completion_tokens,
        "callCount": _session.call_count,
        "lastCallTotal": _session.last_call.total_tokens,
        "lastCallPrompt": _session.last_call.prompt_tokens,
        "lastCallCompletion": _session.last_call.completion_tokens,
        "limit": limit,
        "percentUsed": round(total / limit, 4),
    }
