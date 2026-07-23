from terminal.api import hugo_workflow
from types import SimpleNamespace


def _action_kwargs(action: str) -> dict:
    return {
        "action": action,
        "title": "测试文章",
        "args": {"action": action, "title": "测试文章"},
        "source": "/tmp/test.md",
        "target_url": "https://iver.yivxer.com/posts/test/",
        "steps": ["部署"],
        "verify_plan": "验证 HTTP 200",
        "rollback_plan": "恢复源文件后重新部署",
    }


def test_explicit_hugo_publish_and_redeploy_execute_without_confirmation(monkeypatch):
    calls = []

    def fake_run(*, title, actions, summary_prefix=None):
        calls.append((title, actions, summary_prefix))
        return ([{"type": "tool_event", "toolEvent": {
            "id": "hugo-complete",
            "name": "hugo_blog",
            "status": "complete",
            "risk": "low",
            "summary": "部署枫弋札记",
            "detail": "HTTP 200",
            "requiresApproval": False,
        }}], "《测试文章》已发布。")

    monkeypatch.setattr(hugo_workflow, "_run_hugo_publish_workflow", fake_run)

    for action in ("publish", "deploy"):
        events, summary = hugo_workflow._hugo_confirmation_result(**_action_kwargs(action))
        event = events[0]["toolEvent"]
        assert event["status"] == "complete"
        assert event["requiresApproval"] is False
        assert "确认卡" not in summary

    assert [call[1][0][1]["action"] for call in calls] == ["publish", "deploy"]


def test_hugo_delete_keeps_confirmation_card():
    events, summary = hugo_workflow._hugo_confirmation_result(
        **_action_kwargs("delete_and_deploy")
    )

    event = events[0]["toolEvent"]
    assert event["status"] == "waiting"
    assert event["requiresApproval"] is True
    assert "确认卡" in summary


def test_hugo_agent_confirm_never_invokes_runtime(monkeypatch):
    from core.policy import Decision

    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="hugo_blog", arguments='{"action":"delete","filename":"test.md"}',
        ),
    )
    monkeypatch.setattr("skills.loader.load_skills", lambda: {"hugo_blog": object()})
    monkeypatch.setattr("skills.loader.get_tools", lambda skills: [{"type": "function"}])
    monkeypatch.setattr("core.llm.call_with_tools", lambda *args, **kwargs: SimpleNamespace(
        tool_calls=[tool_call], content="",
    ))
    monkeypatch.setattr("core.policy.check", lambda *args, **kwargs: SimpleNamespace(
        decision=Decision.CONFIRM, risk="high", reason="delete requires confirmation",
    ))
    monkeypatch.setattr("core.tool_runtime.invoke", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("CONFIRM must not invoke runtime"),
    ))
    monkeypatch.setattr(hugo_workflow, "_make_api_tool_request", lambda *args, **kwargs: {
        "eventId": kwargs["event_id"], "skillName": "hugo_blog", "status": "waiting",
        "risk": "high", "requiresApproval": True, "blocked": False,
        "policy": {"decision": "confirm", "risk": "high", "reason": "delete requires confirmation"},
        "draft": {"skillName": "hugo_blog", "args": {"action": "delete"}},
    })

    _, events, summary = hugo_workflow._run_hugo_agent_turn(
        [], "删除线上文章", authorized_action="delete",
    )

    assert events[0]["toolEvent"]["status"] == "waiting"
    assert events[0]["toolEvent"]["requiresApproval"] is True
    assert "等待你的确认" in summary
