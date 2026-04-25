import tomllib
from pathlib import Path
from openai import OpenAI
from openai.types.chat import ChatCompletionMessage
from typing import Generator

def _config() -> dict:
    p = Path(__file__).parent.parent / "archer.toml"
    with open(p, "rb") as f:
        return tomllib.load(f)

def _client() -> tuple[OpenAI, str]:
    cfg = _config()
    client = OpenAI(
        api_key=cfg["api"]["api_key"],
        base_url=cfg["api"]["base_url"],
    )
    return client, cfg["api"]["model"]

def stream_chat(messages: list[dict]) -> Generator[str, None, None]:
    """流式输出，无 function calling。"""
    client, model = _client()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
    )
    for chunk in response:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta

def call_with_tools(messages: list[dict], tools: list[dict]) -> ChatCompletionMessage:
    """非流式调用，携带 tools，用于 function calling 第一步。"""
    client, model = _client()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        stream=False,
    )
    return response.choices[0].message
