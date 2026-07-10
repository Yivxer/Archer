from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from terminal.api._tools import (
    _failure_hint_event,
    _runtime_context_event,
    _tool_event,
    _with_trace_id,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "client/desktop/src/agent/__fixtures__/desktopStreamV1.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.contract
def test_python_stream_builders_match_desktop_contract_fixture():
    fixture = _fixture()
    payload = fixture["payload"]
    trace_id = "trace-contract-1"

    runtime = _runtime_context_event(
        query="继续项目规划",
        intent_info={"intent": "project"},
        orchestration=SimpleNamespace(
            sub_intent="project_planning",
            matched_skills=["obsidian_read"],
        ),
        trace_id=trace_id,
    )
    expected_runtime = payload["runtimeContextEvent"]
    assert {key: value for key, value in runtime.items() if key != "id"} == {
        key: value for key, value in expected_runtime.items() if key != "id"
    }

    tool = _with_trace_id(
        _tool_event(
            "hugo-blog-contract-1",
            "hugo_blog",
            "waiting",
            "medium",
            "确认部署枫弋札记",
            "action: deploy",
            requires_approval=True,
            draft={
                "skillName": "hugo_blog",
                "displayName": "hugo_blog",
                "args": {"action": "deploy"},
                "permissionLevel": "deploy-remote",
                "blocked": False,
            },
        ),
        trace_id,
    )
    assert tool["toolEvent"] == payload["toolEvent"]

    failure = _failure_hint_event(
        TimeoutError("deploy timeout"),
        stage="deploy",
        trace_id=trace_id,
    )
    expected_failure = payload["failureHintEvent"]
    assert {key: value for key, value in failure.items() if key != "id"} == {
        key: value for key, value in expected_failure.items() if key != "id"
    }


@pytest.mark.contract
def test_contract_fixture_declares_stable_python_to_desktop_order():
    fixture = _fixture()

    assert fixture["fixtureVersion"] == 1
    assert fixture["expectedAgentEventTypes"] == [
        "runtime.context",
        "tool.request",
        "status.event",
        "failure.hint",
    ]
