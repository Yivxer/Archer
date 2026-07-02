import os
import tomllib
from pathlib import Path
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletionMessage
from typing import Generator

from core.model_profiles import cfg_with_active_api
from core.observability import trace_span
from core.token_usage import get_last_call_usage, get_session_usage, record_call_usage, reset_session_usage

_cfg: dict | None = None
_client: OpenAI | None = None
_client_key: tuple[str, str] | None = None

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
            _cfg = cfg_with_active_api(_apply_env_overrides(tomllib.load(f)))
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
    # 配置缺失时抛明确错误，避免 OpenAI SDK 报模糊的 api_key required
    if not api_key:
        profile_id = cfg["api"].get("active_profile", "unknown")
        raise ValueError(
            f"模型配置 '{profile_id}' 缺少 api_key，请在设置页填写 API Key 后重试"
        )
    if not cfg["api"].get("model"):
        profile_id = cfg["api"].get("active_profile", "unknown")
        raise ValueError(
            f"模型配置 '{profile_id}' 缺少 model，请在设置页选择模型后重试"
        )
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


def _status_hint(base_url: str, err: APIStatusError) -> RuntimeError:
    status_code = getattr(err, "status_code", None)
    if status_code in (401, 403):
        return RuntimeError(
            "模型 API 鉴权失败：当前模型档位的 API key 缺失、无效或无权限。"
            f"base_url={base_url}。请到设置页更新该档位的 API key，并点击模型连通测试。"
        )
    if status_code == 429:
        return RuntimeError(
            "模型 API 额度或频率受限：当前请求被服务商限流。"
            f"base_url={base_url}。请稍后重试，或切换其他可用模型档位。"
        )
    return RuntimeError(f"模型 API 请求失败：HTTP {status_code or 'unknown'}；base_url={base_url}。")


def stream_chat(
    messages: list[dict],
    model: str = "",
    *,
    track_usage: bool = True,
) -> Generator[str, None, None]:
    """流式输出，无 function calling。同时捕获 token 用量到 session state。"""
    client, cfg = _get_client()
    m = model or cfg["api"]["model"]
    base_url = cfg["api"]["base_url"]

    # DeepSeek reasoner 模型不支持 stream_options，且对部分参数有限制
    # 检测 reasoner 模型时跳过 stream_options，避免 API 返回 400
    _is_reasoner = "reasoner" in m.lower()

    with trace_span("llm.stream_chat", model=m, op="stream") as span:
        try:
            kwargs: dict = {"model": m, "messages": messages, "stream": True}
            if not _is_reasoner:
                kwargs["stream_options"] = {"include_usage": True}
            response = client.chat.completions.create(**kwargs)
        except TypeError:
            # 部分旧版 SDK 或 provider 不支持 stream_options
            response = client.chat.completions.create(
                model=m,
                messages=messages,
                stream=True,
            )
        except (APIConnectionError, APITimeoutError) as e:
            raise _connection_hint(base_url, e) from e
        except APIStatusError as e:
            raise _status_hint(base_url, e) from e

        call_usage: dict[str, int] | None = None

        try:
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
        finally:
            # generator 耗尽或被提前关闭（GeneratorExit/close）都记录 usage
            # 避免客户端断开时 usage 丢失
            if track_usage and call_usage:
                record_call_usage(**call_usage)
                span.update(call_usage)


def get_last_usage() -> dict[str, int]:
    """返回最近一次调用的 token 用量（prompt / completion / total）。"""
    return get_last_call_usage()


def get_session_tokens() -> int:
    """返回本次会话累计 token 数。"""
    usage = get_session_usage()
    return int(usage["total_tokens"])


def reset_session_tokens() -> None:
    """新 CLI 会话启动时重置 token 计数。"""
    reset_session_usage()


def call_with_tools(messages: list[dict], tools: list[dict], model: str = "") -> ChatCompletionMessage:
    """非流式调用，携带 tools，用于 function calling 第一步。"""
    client, cfg = _get_client()
    m = model or cfg["api"]["model"]
    with trace_span("llm.call_with_tools", model=m, tool_count=len(tools)) as span:
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
            usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
                "total_tokens": response.usage.total_tokens or 0,
            }
            record_call_usage(**usage)
            span.update(usage)
        return response.choices[0].message


def load_config() -> dict:
    return _load_config()
