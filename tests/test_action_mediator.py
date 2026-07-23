import pytest

from core.action_mediator import ActionDisposition, mediate_turn
from core.turn_decision import ActionRequest, TurnDecision


def _decision(handling="execute_action", action="publish", evidence="帮我发布到枫弋札记"):
    return TurnDecision(
        user_goal="处理文章", handling=handling,
        action_requests=(ActionRequest(
            capability="hugo_blog", action=action, target="/Users/test/a.md",
            evidence=evidence,
        ),), confidence=0.9, summary="test",
    )


def test_explicit_publish_is_authorized_once_per_current_turn_contract():
    result = mediate_turn(_decision(), "帮我发布到枫弋札记 /Users/test/a.md")
    assert result.disposition == ActionDisposition.AUTO_EXECUTE
    assert result.authorization_source == "current_turn"
    assert result.fingerprint


@pytest.mark.parametrize("query,decision,expected", [
    ("是不是该重新发布", _decision("propose_action", "redeploy", "是不是该重新发布"), ActionDisposition.PROPOSE_ONLY),
    ("不要发布，先分析", TurnDecision("分析", "analyze"), ActionDisposition.DENY),
    ("删除线上文章", _decision("execute_action", "delete", "删除线上文章"), ActionDisposition.REQUEST_CONFIRMATION),
    ("帮我发布", _decision(evidence="模型虚构证据"), ActionDisposition.REQUEST_CONFIRMATION),
])
def test_action_boundaries(query, decision, expected):
    assert mediate_turn(decision, query).disposition == expected


def test_parameter_scope_expansion_requires_confirmation():
    base = _decision()
    action = base.action_requests[0]
    expanded = TurnDecision(
        user_goal=base.user_goal, handling="execute_action",
        action_requests=(ActionRequest(
            capability=action.capability, action=action.action, target=action.target,
            parameters={"sourcePath": "/Users/test/other.md"}, evidence=action.evidence,
        ),),
    )
    assert mediate_turn(expanded, "帮我发布到枫弋札记").disposition == ActionDisposition.REQUEST_CONFIRMATION


def test_non_candidate_capability_is_denied():
    result = mediate_turn(
        _decision(), "帮我发布到枫弋札记", candidate_capabilities=set(),
    )
    assert result.disposition == ActionDisposition.DENY
    assert result.reason == "capability_not_candidate"
