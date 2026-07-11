from __future__ import annotations

import pytest

from terminal.api.turn_context import TurnContext


def test_turn_context_normalizes_chat_request_payload():
    context = TurnContext.from_payload(
        {
            "messages": [
                {"role": "assistant", "content": " earlier "},
                {"role": "user", "content": " continue "},
            ],
            "threadContext": {"title": "Project", "summary": "Previous work"},
            "memoryMode": "full",
            "obsidianMode": "off",
            "fileRefs": [
                {"path": "/tmp/a.md", "name": "", "size": "12", "content": "body"}
            ],
        }
    )

    assert context.messages[0] == {
        "role": "system",
        "content": "[当前话题上下文]\n话题：Project\n话题记忆：Previous work",
    }
    assert context.messages[-1] == {"role": "user", "content": "continue"}
    assert context.memory_mode == "full"
    assert context.obsidian_mode == "off"
    assert context.file_refs == [
        {
            "path": "/tmp/a.md",
            "name": "a.md",
            "size": 12,
            "content": "body",
            "contentChars": 4,
            "truncated": False,
        }
    ]


def test_turn_context_uses_safe_mode_defaults():
    context = TurnContext.from_payload(
        {"messages": [{"role": "user", "content": "hello"}]}
    )

    assert context.memory_mode == "conservative"
    assert context.obsidian_mode == "summary"
    assert context.file_refs == []


def test_turn_context_rejects_invalid_file_refs():
    with pytest.raises(ValueError, match="fileRefs must be a list"):
        TurnContext.from_payload(
            {
                "messages": [{"role": "user", "content": "hello"}],
                "fileRefs": "not-a-list",
            }
        )
