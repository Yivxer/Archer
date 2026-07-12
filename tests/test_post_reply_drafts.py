from types import SimpleNamespace

from terminal.api.post_reply_drafts import PostReplyDraftDependencies, iter_post_reply_draft_events


def _deps(*, generate_obsidian=lambda *args: "", generate_hugo=lambda *args: None, request=None):
    return PostReplyDraftDependencies(
        parse_obsidian=lambda query: SimpleNamespace(mode="append", path="note.md"),
        generate_obsidian=generate_obsidian,
        compute_preview=lambda payload: {"mtime": 1, "size": 2, "fingerprint": "fp", "before": "old", "after": "new", "exists": True},
        generate_hugo=generate_hugo,
        make_request=request or (lambda *args, **kwargs: {"requiresApproval": True}),
        event_from_request=lambda request, **kwargs: {"type": "request", "summary": kwargs["summary"]},
        set_draft=lambda event_id, request: None,
        execute_request=lambda request: {"executed": True, "output": "ok", "policy": {"risk": "low"}},
        tool_event=lambda *args, **kwargs: {"type": "tool", "status": args[2]},
        obsidian_work_intent=lambda path, mode, **kwargs: {"path": path, "mode": mode},
    )


def test_post_reply_drafts_emits_approval_request_for_obsidian_write():
    events = list(iter_post_reply_draft_events(
        query="write", messages=[], ai_reply="reply", obsidian_write_intent=True,
        obsidian_target_path="note.md", hugo_blog_triggered=False,
        dependencies=_deps(generate_obsidian=lambda *args: "draft"),
    ))

    assert events == [{"type": "request", "summary": "确认 Obsidian 写入：draft"}]


def test_post_reply_drafts_marks_empty_obsidian_generation_blocked():
    events = list(iter_post_reply_draft_events(
        query="write", messages=[], ai_reply="reply", obsidian_write_intent=True,
        obsidian_target_path="note.md", hugo_blog_triggered=False,
        dependencies=_deps(),
    ))

    assert events == [{"type": "tool", "status": "blocked"}]


def test_post_reply_drafts_direct_execution_uses_tool_result():
    events = list(iter_post_reply_draft_events(
        query="write", messages=[], ai_reply="reply", obsidian_write_intent=True,
        obsidian_target_path="note.md", hugo_blog_triggered=False,
        dependencies=_deps(
            generate_obsidian=lambda *args: "draft",
            request=lambda *args, **kwargs: {},
        ),
    ))

    assert events == [{"type": "tool", "status": "complete"}]


def test_post_reply_drafts_emits_hugo_approval_request():
    events = list(iter_post_reply_draft_events(
        query="blog", messages=[], ai_reply="reply", obsidian_write_intent=False,
        obsidian_target_path=None, hugo_blog_triggered=True,
        dependencies=_deps(generate_hugo=lambda reply: {"title": "Post", "category": "系统", "description": "d", "body": "body"}),
    ))

    assert events == [{"type": "request", "summary": "确认发布博客文章：Post"}]
