"""Model streaming stage with deterministic heartbeat and timeout events."""

from __future__ import annotations

import queue
import random
import re
import threading
import time
from collections.abc import Callable, Iterator
from urllib.parse import urlsplit

from core.llm_client import LLMClient

PRIMARY_ATTEMPTS = 3
RETRY_BASE_SECONDS = 0.5
RETRY_CAP_SECONDS = 2.0
DEFAULT_FALLBACK_PROFILE = "lite"

DSML_MARKER = "｜｜DSML｜｜"
FAKE_XML_RE = re.compile(
    r"<(读取文件|写入文件|搜索文件|文件查找|参数|tool_call|invoke|function_call|execute)[^>]{0,60}>",
    re.IGNORECASE,
)


def model_trace_metadata(config: dict, model: str) -> dict[str, str]:
    """Return model diagnostics without credentials, path, query, or API keys."""
    from core.model_profiles import active_api_config

    api = active_api_config(config)
    raw_url = str(api.get("base_url") or "").strip()
    base_url_summary = ""
    if raw_url:
        try:
            has_scheme = "://" in raw_url
            parsed = urlsplit(raw_url if has_scheme else f"//{raw_url}")
            host = parsed.hostname or ""
            if host:
                if ":" in host and not host.startswith("["):
                    host = f"[{host}]"
                port = f":{parsed.port}" if parsed.port else ""
                base_url_summary = f"{parsed.scheme}://{host}{port}" if has_scheme else f"{host}{port}"
        except (TypeError, ValueError):
            base_url_summary = ""
    return {
        "provider": str(api.get("provider") or api.get("active_profile") or "unknown"),
        "model": str(model or api.get("model") or "unknown"),
        "baseUrlSummary": base_url_summary,
    }


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


def stream_failure_events(exc: Exception, *, trace_id: str, hint_factory: Callable) -> list[dict]:
    detail = str(exc)[:300] or type(exc).__name__
    lowered = detail.lower()
    if "rate" in lowered or "limit" in lowered:
        text = "\n\n（请求太频繁，稍等几秒再试。）"
    elif "timeout" in lowered or "connect" in lowered:
        text = "\n\n（连接超时，请检查本地 API 是否正常运行。）"
    else:
        text = f"\n\n（回复生成中断：{detail}）"
    return [
        {"type": "token", "text": text},
        {"type": "failureHintEvent", "failureHintEvent": hint_factory(exc, stage="model_stream", trace_id=trace_id)},
        {"type": "error", "detail": detail},
        {"type": "done", "done": True},
    ]


def build_rescue_messages(model_messages: list[dict], invalid_reply: str) -> list[dict]:
    return [
        *model_messages,
        {"role": "assistant", "content": invalid_reply},
        {"role": "user", "content": (
            "你刚才输出了假标签（如 <读取文件>）或 DSML 标记，这些不会被执行。"
            "请直接用自然语言重新回答刚才的问题，不要输出任何 XML、伪标签或 function call 语法。"
        )},
    ]


def iter_rescue_stream(
    model_messages: list[dict], invalid_reply: str, *, model: str,
    heartbeat_seconds: float = 8.0, total_timeout_seconds: float = 180.0,
    stream: Callable | None = None, llm_client: LLMClient | None = None,
) -> Iterator[dict]:
    """Stream a natural-language retry and finish with its collected text."""
    parts: list[str] = []
    try:
        for event in iter_model_stream(
            build_rescue_messages(model_messages, invalid_reply),
            heartbeat_seconds=heartbeat_seconds,
            total_timeout_seconds=total_timeout_seconds,
            stream=stream,
            llm_client=llm_client,
            model=model,
        ):
            if event.get("type") == "heartbeat":
                yield {"type": "heartbeat"}
                continue
            text = str(event.get("text") or "")
            if text:
                parts.append(text)
                yield {"type": "chunk", "text": text}
    except Exception:
        parts.clear()
    yield {"type": "done", "text": "".join(parts)}


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


def is_retryable_model_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in (401, 403) or (status is not None and 400 <= int(status) < 500 and int(status) != 429):
        return False
    if status == 429 or (status is not None and int(status) >= 500):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    denied = ("auth", "api key", "鉴权", "无权限", "content policy", "invalid request")
    if any(marker in text for marker in denied):
        return False
    retryable = ("timeout", "connect", "connection", "429", "rate", "limit", "限流", "频率", "http 5")
    return isinstance(exc, (TimeoutError, ConnectionError)) or any(marker in text for marker in retryable)


def default_profile_fallback(config: dict, active_model: str) -> tuple[Callable | None, str, str]:
    from core.model_profiles import active_model_profile_id, model_profiles

    if active_model_profile_id(config) == DEFAULT_FALLBACK_PROFILE:
        return None, "", ""
    profile = model_profiles(config).get(DEFAULT_FALLBACK_PROFILE) or {}
    fallback_model = str(profile.get("model") or "")
    if not fallback_model or fallback_model == active_model or not profile.get("api_key"):
        return None, "", ""
    from core.llm import stream_chat_for_profile

    def fallback(messages: list[dict], **kwargs) -> Iterator[str]:
        kwargs.pop("llm_client", None)
        kwargs["model"] = fallback_model
        return stream_chat_for_profile(
            messages, profile_id=DEFAULT_FALLBACK_PROFILE, **kwargs,
        )

    return fallback, fallback_model, DEFAULT_FALLBACK_PROFILE


def token_context_snapshot(messages: list[dict]) -> dict[str, int | bool]:
    from core.compressor import DEFAULT_TOKEN_LIMIT, estimate_history_tokens, should_compress

    estimated = estimate_history_tokens(messages)
    return {
        "historyEstimatedTokens": estimated,
        "tokenLimit": DEFAULT_TOKEN_LIMIT,
        "compressionTriggered": should_compress(
            messages, prompt_tokens=estimated, token_limit=DEFAULT_TOKEN_LIMIT,
        ),
    }


def _token_usage_since(initial_call_count: int) -> dict[str, int] | None:
    from core.token_usage import get_last_call_usage, get_session_usage

    session = get_session_usage()
    cc_raw = session.get("call_count") or 0
    cc = sum(cc_raw.values()) if isinstance(cc_raw, dict) else int(cc_raw)
    if cc <= initial_call_count:
        return None
    usage = get_last_call_usage()
    return {
        "promptTokens": int(usage.get("prompt_tokens") or 0),
        "completionTokens": int(usage.get("completion_tokens") or 0),
        "totalTokens": int(usage.get("total_tokens") or 0),
    }


def _run_stream_attempt(
    active_stream: Callable, messages: list[dict], kwargs: dict,
    *, heartbeat_seconds: float, deadline: float,
) -> Iterator[dict]:
    output: queue.Queue[tuple[str, object]] = queue.Queue()

    def worker() -> None:
        try:
            for chunk in active_stream(messages, **kwargs):
                output.put(("chunk", chunk))
            output.put(("done", None))
        except Exception as exc:
            output.put(("error", exc))

    threading.Thread(target=worker, daemon=True).start()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("model stream total timeout")
        try:
            kind, value = output.get(timeout=min(heartbeat_seconds, remaining))
        except queue.Empty:
            yield {"type": "heartbeat"}
            continue
        if kind == "chunk":
            yield {"type": "chunk", "text": value}
        elif kind == "error":
            raise value
        else:
            return


def iter_model_stream(
    messages: list[dict], *, heartbeat_seconds: float = 8.0,
    total_timeout_seconds: float = 180.0, stream: Callable | None = None,
    llm_client: LLMClient | None = None, fallback_stream: Callable | None = None,
    fallback_model: str = "", fallback_profile: str = "",
    sleep: Callable[[float], None] = time.sleep,
    random_value: Callable[[], float] = random.random,
    **kwargs,
) -> Iterator[dict]:
    from core.token_usage import get_session_usage

    _cc_raw = get_session_usage().get("call_count") or 0
    initial_call_count = sum(_cc_raw.values()) if isinstance(_cc_raw, dict) else int(_cc_raw)
    if stream is None and llm_client is not None:
        primary_stream = llm_client.stream_chat
    elif stream is None:
        from core.llm import stream_chat
        primary_stream = stream_chat
    else:
        primary_stream = stream
    deadline = time.monotonic() + total_timeout_seconds
    emitted_chunk = False
    for attempt in range(1, PRIMARY_ATTEMPTS + 1):
        try:
            for event in _run_stream_attempt(
                primary_stream, messages, kwargs,
                heartbeat_seconds=heartbeat_seconds, deadline=deadline,
            ):
                if event.get("type") == "chunk":
                    emitted_chunk = True
                yield event
            usage = _token_usage_since(initial_call_count)
            if usage:
                yield {"type": "usage", "tokenUsage": usage}
            return
        except Exception as exc:
            if emitted_chunk or not is_retryable_model_error(exc):
                raise
            if attempt < PRIMARY_ATTEMPTS:
                delay = min(RETRY_CAP_SECONDS, RETRY_BASE_SECONDS * (2 ** (attempt - 1))) * random_value()
                if time.monotonic() + delay >= deadline:
                    raise TimeoutError("model stream total timeout") from exc
                yield {"type": "retry", "attempt": attempt + 1, "maxAttempts": PRIMARY_ATTEMPTS}
                sleep(delay)
                continue
            if fallback_stream is None:
                raise
            yield {
                "type": "fallback", "attempt": 1, "maxAttempts": 1,
                "fallbackProfile": fallback_profile, "model": fallback_model,
            }
            fallback_kwargs = dict(kwargs)
            if fallback_model:
                fallback_kwargs["model"] = fallback_model
            yield from _run_stream_attempt(
                fallback_stream, messages, fallback_kwargs,
                heartbeat_seconds=heartbeat_seconds, deadline=deadline,
            )
            usage = _token_usage_since(initial_call_count)
            if usage:
                yield {"type": "usage", "tokenUsage": usage}
            return
