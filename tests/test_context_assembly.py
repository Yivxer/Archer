from __future__ import annotations

from types import SimpleNamespace

from terminal.api.context_assembly import assemble_memory_context


def _event_factory(event_id, name, status, risk, summary, detail, *args, **kwargs):
    return {
        "type": "toolEvent",
        "toolEvent": {
            "id": event_id,
            "name": name,
            "status": status,
            "risk": risk,
            "summary": summary,
            "detail": detail,
        },
    }


def test_memory_context_conservative_mode_skips_retrieval_when_not_needed():
    result = assemble_memory_context(
        [{"role": "user", "content": "hello"}],
        query="hello",
        prior_history=[],
        intent="chat",
        needs_memory=False,
        memory_mode="conservative",
        retrieve_limit=6,
        expert={},
        event_factory=_event_factory,
    )

    assert result.messages == [{"role": "user", "content": "hello"}]
    assert [event["toolEvent"]["status"] for event in result.events] == ["complete"]
    assert "未触发记忆检索" in result.events[0]["toolEvent"]["summary"]


def test_memory_context_injects_formatted_retrieval_before_messages():
    calls = []

    def retrieve(query, **kwargs):
        calls.append((query, kwargs))
        return [SimpleNamespace(id="core")], [SimpleNamespace(id="related")]

    result = assemble_memory_context(
        [{"role": "user", "content": "continue"}],
        query="continue",
        prior_history=[{"role": "user", "content": "earlier"}],
        intent="task",
        needs_memory=True,
        memory_mode="full",
        retrieve_limit=4,
        expert={"memory_tags": ["project"]},
        event_factory=_event_factory,
        augment_query=lambda query, history: f"{query}:{len(history)}",
        retrieve=retrieve,
        format_retrieval=lambda core, related: "remembered context",
        expert_tags=lambda expert: expert["memory_tags"],
    )

    assert calls == [
        (
            "continue:1",
            {"limit": 4, "intent": "task", "tag_hints": ["project"]},
        )
    ]
    assert result.messages[0]["role"] == "system"
    assert "remembered context" in result.messages[0]["content"]
    assert [event["toolEvent"]["status"] for event in result.events] == [
        "running",
        "complete",
    ]
