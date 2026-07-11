import pytest

from terminal.api.tool_stage import ApprovalExecution, apply_approval_followup, build_approval_response, build_denied_response, execute_approved_draft, persist_approval_response, prepare_approval_draft, resolve_approval_draft, reuse_fingerprint_approval, parse_approval_decision, reuse_cached_approval, summarize_api_tool_events


def test_parse_approval_decision_accepts_only_explicit_choices():
    assert parse_approval_decision({"eventId": " event-1 ", "decision": "approved"}) == ("event-1", "approved")
    with pytest.raises(ValueError, match="approved or denied"):
        parse_approval_decision({"eventId": "event-1", "decision": "yes"})


def test_reuse_cached_approval_marks_result_without_execution():
    cached = {"ok": True, "executed": True}
    assert reuse_cached_approval("event-1", lambda event_id: cached) == {
        "ok": True,
        "executed": True,
        "reused": True,
    }
    assert reuse_cached_approval("missing", lambda event_id: None) is None


def test_denied_response_is_always_zero_side_effect():
    assert build_denied_response("e1") == {"ok": True, "eventId": "e1", "decision": "denied", "executed": False, "output": "", "message": "已取消，未执行。"}


def test_fingerprint_reuse_rebinds_event_without_execution():
    result = reuse_fingerprint_approval("new", "fp", {"ok": True, "executed": True}, permission_level="write")
    assert result["eventId"] == "new"
    assert result["reused"] is True
    assert result["idempotencyReason"] == "same_fingerprint"


def test_execute_approved_standard_tool_preserves_receipt():
    execution = execute_approved_draft(
        {"kind": "tool_request"},
        execute_tool_request=lambda _: {"executed": True, "output": "ok", "summary": "done", "workReceipt": {"id": "r1"}},
        append_obsidian=lambda _: "", execute_shell=lambda *_: {}, execute_github=lambda _: "",
    )
    assert execution == ApprovalExecution(True, "ok", "done", {"id": "r1"}, {"executed": True, "output": "ok", "summary": "done", "workReceipt": {"id": "r1"}})


def test_persist_fingerprint_only_after_success():
    fingerprints = []
    response = build_approval_response(event_id="e1", decision="approved", execution=ApprovalExecution(True, "ok", "done"), draft={"traceId": "t1"}, fingerprint="fp", permission_level="write")
    persist_approval_response(response, event_id="e1", decision="approved", draft={}, fingerprint="fp", record_audit=lambda **_: None, set_event_result=lambda *_: None, set_fingerprint_result=lambda *args: fingerprints.append(args))
    assert fingerprints == [("fp", response)]


def test_hugo_followup_uses_created_filename():
    calls = []
    result = apply_approval_followup(
        {"kind": "tool_request", "skillName": "hugo_blog", "args": {"action": "new", "title": "Post"}},
        ApprovalExecution(True, "created", "done", raw_result={"metadata": {"filename": "post.md"}}),
        deploy=lambda **kwargs: (calls.append(kwargs) or "部署成功", "验证：ok"),
    )
    assert calls == [{"title": "Post", "deploy_args": {"action": "deploy", "filename": "post.md"}}]
    assert "验证单页可访问" in result.message


def test_prepare_approval_reuses_idempotent_fingerprint():
    prepared = prepare_approval_draft(event_id="new", decision="approved", draft={"kind": "tool_request", "skillName": "write", "args": {"path": "a"}}, idempotent_skills={"write"}, fingerprint_for=lambda *_: "fp", get_fingerprint_result=lambda _: {"executed": True}, permission_for=lambda *_: "write")
    assert prepared.fingerprint == "fp"
    assert prepared.reused_response["eventId"] == "new"


def test_resolve_approval_draft_builds_hugo_fallback_only_for_deploy_event():
    draft = resolve_approval_draft("hugo-blog-deploy-1", None, get_draft=lambda _: None, build_fallback=lambda *_: None, build_hugo_deploy=lambda event_id: {"eventId": event_id})
    assert draft == {"eventId": "hugo-blog-deploy-1"}


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
