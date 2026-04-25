import tomllib
from pathlib import Path
from openai import OpenAI
from openai.types.chat import ChatCompletionMessage
from typing import Generator

_cfg:    dict | None = None
_client: OpenAI | None = None

def _load_config() -> dict:
    global _cfg
    if _cfg is None:
        p = Path(__file__).parent.parent / "archer.toml"
        with open(p, "rb") as f:
            _cfg = tomllib.load(f)
    return _cfg

def _get_client() -> tuple[OpenAI, dict]:
    global _client
    cfg = _load_config()
    if _client is None:
        _client = OpenAI(
            api_key=cfg["api"]["api_key"],
            base_url=cfg["api"]["base_url"],
        )
    return _client, cfg

def stream_chat(messages: list[dict], model: str = "") -> Generator[str, None, None]:
    """流式输出，无 function calling。model 为空时使用配置默认值。"""
    client, cfg = _get_client()
    m = model or cfg["api"]["model"]
    response = client.chat.completions.create(
        model=m,
        messages=messages,
        stream=True,
    )
    for chunk in response:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta

def call_with_tools(messages: list[dict], tools: list[dict], model: str = "") -> ChatCompletionMessage:
    """非流式调用，携带 tools，用于 function calling 第一步。"""
    client, cfg = _get_client()
    m = model or cfg["api"]["model"]
    response = client.chat.completions.create(
        model=m,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        stream=False,
    )
    return response.choices[0].message

def load_config() -> dict:
    return _load_config()
