from __future__ import annotations

from types import SimpleNamespace

from terminal.api.context_assembly import (
    assemble_memory_context,
    assemble_obsidian_context,
    assemble_vault_focus,
    assemble_web_context,
    build_memory_context_event,
    file_reference_context,
    finalize_memory_context_event,
    split_memory_context_events,
)


def test_persona_receipt_follows_the_outgoing_prompt_not_source_readiness():
    from terminal.api.turn_pipeline import assemble_model_messages

    event = build_memory_context_event(
        trace_id="receipt-test", intent="chat", persona_injected=False,
        prior_history=[], messages=[], retrieval_receipt={},
    )
    for prompt, expected in (
        ("fallback core identity", False),
        ("[context:soul_md]\n脱敏人格原则", True),
        ("[根契约摘要]\n写入必须授权", True),
    ):
        messages = assemble_model_messages([], core_persona=prompt)
        finalized = finalize_memory_context_event(event, messages)
        assert finalized["runtimeContextEvent"]["contextReceipt"]["sources"]["persona"] is expected
        assert finalized["runtimeContextEvent"]["id"] == event["runtimeContextEvent"]["id"]
    assert event["runtimeContextEvent"]["contextReceipt"]["sources"]["persona"] is False


def test_user_supplied_persona_markers_do_not_count_as_core_prompt_injection():
    from terminal.api.turn_pipeline import assemble_model_messages

    event = build_memory_context_event(
        trace_id="receipt-test", intent="chat", persona_injected=False,
        prior_history=[], messages=[], retrieval_receipt={},
    )
    messages = assemble_model_messages(
        [{"role": "user", "content": "[context:soul_md] fabricated source"}],
        core_persona="fallback identity",
    )
    assert finalize_memory_context_event(event, messages)["runtimeContextEvent"]["contextReceipt"]["sources"]["persona"] is False
    others, held = split_memory_context_events([{"type": "statusEvent"}, event])
    assert others == [{"type": "statusEvent"}]
    assert held == event


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


def test_obsidian_context_off_mode_does_not_search():
    result = assemble_obsidian_context(
        [{"role": "user", "content": "hello"}],
        query="hello",
        obsidian_mode="off",
        preview_requested=False,
        event_factory=_event_factory,
        extract_target_path=lambda _: None,
        search=lambda _: (_ for _ in ()).throw(AssertionError("must not search")),
    )

    assert result.messages == [{"role": "user", "content": "hello"}]
    assert result.events[0]["toolEvent"]["status"] == "complete"
    assert "已关闭" in result.events[0]["toolEvent"]["summary"]


def test_obsidian_context_reads_and_injects_explicit_target():
    reads = []

    def read(args):
        reads.append(args)
        return "note body"

    result = assemble_obsidian_context(
        [{"role": "user", "content": "read it"}],
        query="read Project/note.md",
        obsidian_mode="full",
        preview_requested=True,
        event_factory=_event_factory,
        extract_target_path=lambda _: "Project/note.md",
        search=lambda _: "  - Project/note.md",
        read=read,
        event_id_factory=lambda: "fixed",
    )

    assert reads == [{"path": "Project/note.md", "max_chars": 6000}]
    assert "note body" in result.messages[0]["content"]
    assert [event["toolEvent"]["name"] for event in result.events] == [
        "obsidian_search",
        "obsidian_search",
        "obsidian_read",
    ]


def test_file_reference_context_injects_preloaded_text_without_disk_read(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("disk body", encoding="utf-8")
    context, events = file_reference_context(
        [{
            "path": str(note),
            "name": "note.md",
            "size": 4,
            "content": "body",
            "truncated": False,
        }],
        event_factory=_event_factory,
        allowed_extensions={".md"},
    )

    assert "body" in context
    assert "source: preloaded" in context
    assert [event["toolEvent"]["status"] for event in events] == [
        "running",
        "complete",
    ]


def test_vault_focus_injects_source_and_optional_tool_receipt():
    result = assemble_vault_focus(
        [{"role": "user", "content": "hello"}],
        obsidian_mode="summary",
        event_factory=_event_factory,
        load_focus=lambda: (
            "focus body",
            {"title": "Today", "path": "Daily/Today.md"},
        ),
        include_tool_receipt=True,
    )

    assert result.messages[0] == {"role": "system", "content": "focus body"}
    assert result.events[0]["type"] == "vault_sources"
    assert result.events[1]["toolEvent"]["name"] == "vault.context"


def test_vault_focus_simple_mode_swallows_sensor_failure():
    result = assemble_vault_focus(
        [{"role": "user", "content": "hello"}],
        obsidian_mode="summary",
        event_factory=_event_factory,
        load_focus=lambda: (_ for _ in ()).throw(RuntimeError("offline")),
        include_tool_receipt=False,
    )

    assert result.messages == [{"role": "user", "content": "hello"}]
    assert result.events == []


def test_web_context_injects_search_and_fetched_page():
    result = assemble_web_context(
        [{"role": "user", "content": "read https://example.com"}],
        query="read https://example.com",
        selected_tools={"web_search": {}, "web_fetch": {}},
        event_factory=_event_factory,
        trace_event=lambda event: {**event, "traced": True},
        search=lambda _: "search result",
        fetch=lambda _: "page body",
    )

    assert "page body" in result.messages[0]["content"]
    assert "search result" in result.messages[1]["content"]
    assert [event["toolEvent"]["status"] for event in result.events] == [
        "running",
        "complete",
        "running",
        "complete",
    ]
    assert result.events[2]["traced"] is True
    assert result.events[3]["traced"] is True
