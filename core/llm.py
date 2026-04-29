import os
import tomllib
from pathlib import Path
from openai import APIConnectionError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletionMessage
from typing import Generator

_cfg:    dict | None = None
_client: OpenAI | None = None
_client_key: tuple[str, str] | None = None

# 最近一次 API 调用的 token 用量
_last_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
# 本次会话累计
_session_tokens: int = 0

# 配置热加载
_CONFIG_PATH = Path(__file__).parent.parent / "archer.toml"
_ENV_PATH = Path(__file__).parent.parent / ".env"
_config_mtime: float = 0.0
_config_reloaded: bool = False


def _read_dotenv(path: Path = _ENV_PATH) -> dict[str, str]:
    """Read a tiny KEY=VALUE .env file without adding a runtime dependency."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _apply_env_overrides(cfg: dict) -> dict:
    env_file = _read_dotenv()
    api = cfg.setdefault("api", {})

    api_key = os.environ.get("ARCHER_API_KEY") or env_file.get("ARCHER_API_KEY")
    base_url = os.environ.get("ARCHER_BASE_URL") or env_file.get("ARCHER_BASE_URL")
    model = os.environ.get("ARCHER_MODEL") or env_file.get("ARCHER_MODEL")

    if api_key:
        api["api_key"] = api_key
    if base_url:
        api["base_url"] = base_url
    if model:
        api["model"] = model
    return cfg


def _api_timeout(cfg: dict) -> float:
    return float(cfg.get("api", {}).get("timeout_s", 45))


def _api_max_retries(cfg: dict) -> int:
    return int(cfg.get("api", {}).get("max_retries", 1))


def _load_config() -> dict:
    global _cfg, _config_mtime, _config_reloaded, _client, _client_key
    try:
        mtime = _CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        if _cfg is None:
            raise
        _config_reloaded = False
        return _cfg
    if _cfg is None or mtime > _config_mtime:
        with open(_CONFIG_PATH, "rb") as f:
            _cfg = _apply_env_overrides(tomllib.load(f))
        _config_reloaded = (_config_mtime > 0)  # 初次加载不算"重载"
        _config_mtime = mtime
        if _config_reloaded:
            _client = None
            _client_key = None
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
    global _client, _client_key
    cfg = _load_config()
    api_key = cfg["api"]["api_key"]
    base_url = cfg["api"]["base_url"]
    key = (api_key, base_url)
    if _client is None or _client_key != key:
        _client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=_api_timeout(cfg),
            max_retries=_api_max_retries(cfg),
        )
        _client_key = key
    return _client, cfg


def _connection_hint(base_url: str, err: Exception) -> RuntimeError:
    cause = getattr(err, "__cause__", None)
    cause_text = str(cause or err)
    return RuntimeError(
        "无法连接 LLM API。"
        f"base_url={base_url}；底层错误：{cause_text}。"
        "如果刚断开 VPN，优先检查系统 DNS；国内使用建议配置可直连的 OpenAI 兼容端点。"
    )


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
    base_url = cfg["api"]["base_url"]

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
    except (APIConnectionError, APITimeoutError) as e:
        raise _connection_hint(base_url, e) from e

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
    try:
        response = client.chat.completions.create(
            model=m,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=False,
        )
    except (APIConnectionError, APITimeoutError) as e:
        raise _connection_hint(cfg["api"]["base_url"], e) from e
    if getattr(response, "usage", None) and response.usage.total_tokens:
        _session_tokens += response.usage.total_tokens
    return response.choices[0].message


def load_config() -> dict:
    return _load_config()
