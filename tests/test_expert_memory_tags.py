"""Memory retrieval tag hint tests."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.retrieve import _matches_tag_hints, for_context


def test_matches_tag_hints_is_case_insensitive():
    assert _matches_tag_hints("expert:parent-educator,parenting", ["expert:parent-educator"])
    assert not _matches_tag_hints("writing", ["expert:developer"])


def test_for_context_prefers_tagged_memories(monkeypatch):
    memories = [
        {"id": 1, "content": "通用记忆", "tags": "general", "type": "insight", "importance": 3, "created_at": "2026-06-20T10:00:00"},
        {"id": 2, "content": "育儿记忆", "tags": "expert:parent-educator,parenting", "type": "insight", "importance": 4, "created_at": "2026-06-20T10:00:00"},
    ]

    monkeypatch.setattr("memory.retrieve._should_skip_memory", lambda _text: False)
    monkeypatch.setattr("memory.retrieve._hybrid_search", lambda _q, limit=5, **kwargs: memories[:limit])
    monkeypatch.setattr("memory.retrieve.select_context_memories", lambda items, **kwargs: items[: kwargs.get("limit", 5)])
    monkeypatch.setattr("memory.retrieve.update_last_used", lambda _mid: None)

    core, related = for_context("今晚怎么和孩子沟通", limit=2, tag_hints=["expert:parent-educator"])
    selected = core + related
    assert any("育儿记忆" in m["content"] for m in selected)
    assert all("expert:parent-educator" in m.get("tags", "") for m in selected)
