from __future__ import annotations

import pytest

from core.run_contract import (
    RUN_CONTRACT_VERSION,
    RUN_STATE_TRANSITIONS,
    STEP_STATE_TRANSITIONS,
    ArtifactRecord,
    InvalidRunTransition,
    InvalidStepTransition,
    RunBudget,
    RunCheckpoint,
    RunEventRecord,
    RunEventType,
    RunRecord,
    RunState,
    StepRecord,
    StepState,
    StopReason,
    VerificationReceipt,
    VerificationStatus,
    require_run_transition,
    require_step_transition,
)


def test_run_state_values_are_stable() -> None:
    assert {state.value for state in RunState} == {
        "received",
        "understanding",
        "planning",
        "waiting_user",
        "waiting_approval",
        "executing",
        "verifying",
        "uncertain",
        "interrupted",
        "cancelling",
        "completed",
        "failed",
        "cancelled",
    }


def test_happy_path_run_transitions_are_legal() -> None:
    path = (
        RunState.RECEIVED,
        RunState.UNDERSTANDING,
        RunState.PLANNING,
        RunState.WAITING_APPROVAL,
        RunState.EXECUTING,
        RunState.VERIFYING,
        RunState.COMPLETED,
    )
    for current, target in zip(path, path[1:]):
        require_run_transition(current, target)


def test_terminal_run_states_cannot_transition() -> None:
    for state in (RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED):
        assert RUN_STATE_TRANSITIONS[state] == frozenset()
        with pytest.raises(InvalidRunTransition):
            require_run_transition(state, RunState.EXECUTING)


def test_run_cannot_skip_directly_from_received_to_completed() -> None:
    with pytest.raises(
        InvalidRunTransition,
        match="received -> completed",
    ):
        require_run_transition(RunState.RECEIVED, RunState.COMPLETED)


def test_step_requires_verification_before_completion() -> None:
    with pytest.raises(InvalidStepTransition, match="running -> completed"):
        require_step_transition(StepState.RUNNING, StepState.COMPLETED)

    require_step_transition(StepState.RUNNING, StepState.VERIFYING)
    require_step_transition(StepState.VERIFYING, StepState.COMPLETED)


def test_terminal_step_states_cannot_transition() -> None:
    for state in (
        StepState.COMPLETED,
        StepState.FAILED,
        StepState.SKIPPED,
        StepState.CANCELLED,
    ):
        assert STEP_STATE_TRANSITIONS[state] == frozenset()


def test_run_record_serialization_is_contract_safe() -> None:
    record = RunRecord(
        id="run-1",
        objective="把计划写入架构文档",
        source="chat",
        state=RunState.COMPLETED,
        stop_reason=StopReason.GOAL_SATISFIED,
        budget=RunBudget(token_budget=10_000),
    )

    payload = record.to_dict()

    assert payload["contract_version"] == RUN_CONTRACT_VERSION
    assert payload["state"] == "completed"
    assert payload["stop_reason"] == "goal_satisfied"
    assert payload["budget"]["token_budget"] == 10_000


def test_step_record_serializes_tuple_contracts_as_lists() -> None:
    record = StepRecord(
        id="step-1",
        run_id="run-1",
        ordinal=1,
        title="校验写入结果",
        kind="verification",
        state=StepState.VERIFYING,
        depends_on=("step-0",),
        success_criteria=("path_exists", "content_matches"),
    )

    payload = record.to_dict()

    assert payload["state"] == "verifying"
    assert payload["depends_on"] == ["step-0"]
    assert payload["success_criteria"] == ["path_exists", "content_matches"]


def test_artifact_and_verification_receipt_share_traceable_ids() -> None:
    artifact = ArtifactRecord(
        id="artifact-1",
        run_id="run-1",
        step_id="step-1",
        kind="markdown",
        uri_or_path="/tmp/architecture.md",
        fingerprint="sha256:abc",
        media_type="text/markdown",
        created_by="obsidian_write",
    )
    receipt = VerificationReceipt(
        id="verification-1",
        run_id="run-1",
        step_id="step-1",
        verifier="markdown_fingerprint",
        status=VerificationStatus.VERIFIED,
        criteria=("content_matches",),
        evidence_refs=(artifact.id,),
    )

    assert receipt.to_dict()["status"] == "verified"
    assert receipt.to_dict()["evidence_refs"] == [artifact.id]
    assert artifact.to_dict()["run_id"] == receipt.run_id


def test_run_event_serialization_is_stable() -> None:
    event = RunEventRecord(
        id="event-1",
        run_id="run-1",
        sequence=1,
        event_type=RunEventType.RUN_RECEIVED,
        created_at="2026-07-23T10:00:00+08:00",
        payload={"source": "chat"},
    )

    assert event.to_dict()["event_type"] == "run.received"
    assert event.to_dict()["payload"] == {"source": "chat"}


def test_checkpoint_serializes_resume_cursor() -> None:
    checkpoint = RunCheckpoint(
        id="checkpoint-1",
        run_id="run-1",
        step_id="step-1",
        resume_state=RunState.VERIFYING,
        cursor={"artifactId": "artifact-1", "attempt": 2},
        created_at="2026-07-24T18:00:00+08:00",
    )

    assert checkpoint.to_dict() == {
        "id": "checkpoint-1",
        "run_id": "run-1",
        "resume_state": "verifying",
        "cursor": {"artifactId": "artifact-1", "attempt": 2},
        "created_at": "2026-07-24T18:00:00+08:00",
        "step_id": "step-1",
        "cursor_version": 1,
    }
