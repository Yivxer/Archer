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
from terminal.api._routes import _tool_approval
from terminal.api import _config
from terminal.api.fastapi_app import _chat_stream_events
from terminal.api.contract import versioned_payload


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "client/desktop/src/agent/__fixtures__/desktopStreamV1.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.contract
def test_python_stream_builders_match_desktop_contract_fixture(monkeypatch, tmp_path):
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

    approval_fixture = fixture["approvalResponse"]
    event_id = approval_fixture["eventId"]
    monkeypatch.setattr(_config, "TOOL_DRAFTS_DIR", tmp_path / "tool-drafts")
    monkeypatch.setattr(
        _config,
        "TOOL_APPROVAL_AUDIT_LOG_PATH",
        tmp_path / "tool-approval-audit.jsonl",
    )
    _config.PENDING_TOOL_DRAFTS.clear()
    _config.PENDING_TOOL_RESULTS.clear()
    _config.PENDING_TOOL_FINGERPRINT_RESULTS.clear()
    _config.set_tool_draft(
        event_id,
        {
            "kind": "tool_request",
            "eventId": event_id,
            "skillName": "hugo_blog",
            "args": {"action": "deploy", "contractNonce": event_id},
            "traceId": trace_id,
        },
    )
    monkeypatch.setattr(
        "core.api_tool_service.execute_tool_request",
        lambda *_args, **_kwargs: {
            "executed": True,
            "output": "部署成功",
            "summary": "hugo deploy complete",
            "workReceipt": approval_fixture["workReceipt"],
        },
    )
    approval = _tool_approval({"eventId": event_id, "decision": "approved"})
    assert {
        key: approval.get(key)
        for key in approval_fixture
    } == approval_fixture
    assert isinstance(approval.get("fingerprint"), str)
    assert approval["fingerprint"]


@pytest.mark.contract
def test_contract_fixture_declares_stable_python_to_desktop_order():
    fixture = _fixture()

    assert fixture["fixtureVersion"] == 1
    assert fixture["payload"]["contractVersion"] == 1
    assert fixture["expectedAgentEventTypes"] == [
        "runtime.context",
        "tool.request",
        "status.event",
        "failure.hint",
        "approval.result",
    ]
    assert fixture["donePayload"] == {
        "contractVersion": 1,
        "type": "done",
        "done": True,
    }


@pytest.mark.contract
def test_fastapi_sse_frames_all_declare_contract_version(monkeypatch):
    monkeypatch.setattr(
        "terminal.api.fastapi_app._iter_chat_chunks",
        lambda *_args, **_kwargs: iter([
            {"type": "ready", "ready": True},
            {"type": "done", "done": True},
        ]),
    )
    frames = list(
        _chat_stream_events({"messages": [{"role": "user", "content": "hi"}]})
    )

    payloads = [json.loads(frame.removeprefix("data: ")) for frame in frames]
    assert [payload["contractVersion"] for payload in payloads] == [1, 1]


def test_list_rest_payload_uses_versioned_data_envelope():
    assert versioned_payload([{"id": "session-1"}]) == {
        "contractVersion": 1,
        "data": [{"id": "session-1"}],
    }
