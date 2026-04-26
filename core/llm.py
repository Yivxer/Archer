import tomllib
from pathlib import Path
from openai import OpenAI
from openai.types.chat import ChatCompletionMessage
from typing import Generator

_cfg:    dict | None = None
_client: OpenAI | None = None

# 最近一次 API 调用的 token 用量
_last_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
# 本次会话累计
_session_tokens: int = 0

# 配置热加载
_CONFIG_PATH = Path(__file__).parent.parent / "archer.toml"
_config_mtime: float = 0.0
_config_reloaded: bool = False


def _load_config() -> dict:
    global _cfg, _config_mtime, _config_reloaded
    try:
        mtime = _CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        if _cfg is None:
            raise
        _config_reloaded = False
        return _cfg
    if _cfg is None or mtime > _config_mtime:
        with open(_CONFIG_PATH, "rb") as f:
            _cfg = tomllib.load(f)
        _config_reloaded = (_config_mtime > 0)  # 初次加载不算"重载"
        _config_mtime = mtime
    else:
        _config_reloaded = False
    return _cfg


def pop_config_reloaded() -> bool:
    """返回配置是否被热加载（重启后首次加载不算），并重置标志。"""
    global _config_reloaded
    v = _config_reloaded
    _config_reloaded = False
    return v


def _get_client() -> tuple[OpenAI, dict]:
    global _client
    cfg = _load_config()
    if _client is None:
        _client = OpenAI(
            api_key=cfg["api"]["api_key"],
            base_url=cfg["api"]["base_url"],
        )
    return _client, cfg


def stream_chat(
    messages: list[dict],
    model: str = "",
    *,
    track_usage: bool = True,
) -> Generator[str, None, None]:
    """流式输出，无 function calling。同时捕获 token 用量到 _last_usage。"""
    global _last_usage, _session_tokens
    client, cfg = _get_client()
    m = model or cfg["api"]["model"]

    try:
        response = client.chat.completions.create(
            model=m,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
        )
    except TypeError:
        # 部分旧版 SDK 或 provider 不支持 stream_options
        response = client.chat.completions.create(
            model=m,
            messages=messages,
            stream=True,
        )

    call_usage: dict[str, int] | None = None

    for chunk in response:
        # usage 只在最后一个 chunk 里出现（OpenAI stream_options 规范）
        if hasattr(chunk, "usage") and chunk.usage and chunk.usage.total_tokens:
            call_usage = {
                "prompt_tokens":     chunk.usage.prompt_tokens or 0,
                "completion_tokens": chunk.usage.completion_tokens or 0,
                "total_tokens":      chunk.usage.total_tokens or 0,
            }

        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

    # generator 耗尽后才更新全局，避免多 chunk 重复累加
    if track_usage and call_usage:
        _last_usage = call_usage
        _session_tokens += call_usage["total_tokens"]


def get_last_usage() -> dict[str, int]:
    """返回最近一次调用的 token 用量（prompt / completion / total）。"""
    return _last_usage.copy()


def get_session_tokens() -> int:
    """返回本次会话累计 token 数。"""
    return _session_tokens


def call_with_tools(messages: list[dict], tools: list[dict], model: str = "") -> ChatCompletionMessage:
    """非流式调用，携带 tools，用于 function calling 第一步。"""
    global _session_tokens
    client, cfg = _get_client()
    m = model or cfg["api"]["model"]
    response = client.chat.completions.create(
        model=m,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        stream=False,
    )
    if getattr(response, "usage", None) and response.usage.total_tokens:
        _session_tokens += response.usage.total_tokens
    return response.choices[0].message


def load_config() -> dict:
    return _load_config()
