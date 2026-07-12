from core.llm_client import DefaultLLMClient
from memory.llm_port import configure_llm_client, stream_chat


def test_default_llm_client_delegates_without_creating_client_at_import(monkeypatch):
    calls = []
    monkeypatch.setattr("core.llm.stream_chat", lambda messages, **kwargs: iter(["a", "b"]))

    client = DefaultLLMClient()
    assert list(client.stream_chat([{"role": "user", "content": "hi"}])) == ["a", "b"]
    assert client.chat([{"role": "user", "content": "hi"}]) == "ab"
    assert calls == []


def test_memory_llm_port_accepts_protocol_client():
    class FakeClient:
        def stream_chat(self, messages, **kwargs):
            return iter(["memory"])

        def chat(self, messages, **kwargs):
            return "memory"

    configure_llm_client(FakeClient())

    assert list(stream_chat([{"role": "user", "content": "hi"}])) == ["memory"]
