from terminal.api.tool_stage import summarize_api_tool_events


def test_tool_event_summary_distinguishes_execution_from_approval():
    result = summarize_api_tool_events(
        [
            {
                "toolEvent": {
                    "name": "obsidian_write",
                    "status": "complete",
                    "draft": {"path": "Notes/done.md"},
                }
            },
            {
                "toolEvent": {
                    "name": "shell",
                    "status": "waiting",
                    "requiresApproval": True,
                    "draft": {"command": "pwd"},
                }
            },
        ],
        resolve_obsidian_path=lambda path: f"/vault/{path}",
    )

    assert result.direct_obsidian_writes == ["/vault/Notes/done.md"]
    assert result.tool_notes == [
        "已直接写入 Obsidian；目标路径：/vault/Notes/done.md。",
        "已生成 shell 工具草稿，正在等待用户确认。",
    ]


def test_obsidian_approval_summary_uses_nested_draft_path():
    result = summarize_api_tool_events(
        [{
            "toolEvent": {
                "name": "obsidian_write",
                "status": "waiting",
                "requiresApproval": True,
                "draft": {"args": {"path": "Inbox/note.md"}},
            }
        }],
    )

    assert "Inbox/note.md" in result.tool_notes[0]
    assert result.direct_obsidian_writes == []
