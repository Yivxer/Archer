from __future__ import annotations

import pytest

from core.job_execution_adapter import (
    COMMAND_REQUIREMENTS,
    JOB_EXECUTION_ADAPTER_CONTRACT_VERSION,
    LEGACY_JOB_V0_ADAPTER_ID,
    JobCommand,
    JobCommandContractError,
    JobCommandEnvelope,
    JobExecutionCapability,
    audit_legacy_job_v0,
    evaluate_job_authority,
    job_command_id,
    legacy_job_attempt_identity,
    project_authoritative_job_state,
)
from core.run_contract import RunState, StepState


def test_legacy_job_v0_cannot_claim_any_runtime_command() -> None:
    decisions = audit_legacy_job_v0()

    assert JOB_EXECUTION_ADAPTER_CONTRACT_VERSION == 1
    assert {decision.command for decision in decisions} == set(JobCommand)
    assert all(decision.adapter_id == LEGACY_JOB_V0_ADAPTER_ID for decision in decisions)
    assert all(decision.permitted is False for decision in decisions)
    assert all(decision.missing_capabilities for decision in decisions)


def test_successful_job_commands_require_business_outcome_verification() -> None:
    for command in (
        JobCommand.CREATE,
        JobCommand.START,
        JobCommand.RETRY,
        JobCommand.APPROVE,
    ):
        assert (
            JobExecutionCapability.OUTCOME_VERIFICATION
            in COMMAND_REQUIREMENTS[command]
        )


@pytest.mark.parametrize("command", list(JobCommand))
def test_command_authority_requires_every_declared_capability(
    command: JobCommand,
) -> None:
    required = COMMAND_REQUIREMENTS[command]
    permitted = evaluate_job_authority("test.adapter", command, required)
    missing_one = evaluate_job_authority(
        "test.adapter",
        command,
        required - {next(iter(required))},
    )

    assert permitted.permitted is True
    assert permitted.missing_capabilities == ()
    assert missing_one.permitted is False
    assert len(missing_one.missing_capabilities) == 1


def test_mutating_commands_require_stable_command_identity() -> None:
    assert all(
        JobExecutionCapability.STABLE_COMMAND_ID in requirements
        for requirements in COMMAND_REQUIREMENTS.values()
    )
    assert JobExecutionCapability.CREATE_IDEMPOTENCY in (
        COMMAND_REQUIREMENTS[JobCommand.CREATE]
    )
    assert JobExecutionCapability.ATTEMPT_IDENTITY in (
        COMMAND_REQUIREMENTS[JobCommand.RETRY]
    )
    assert JobExecutionCapability.COOPERATIVE_CANCELLATION in (
        COMMAND_REQUIREMENTS[JobCommand.CANCEL]
    )
    assert JobExecutionCapability.APPROVAL_FINGERPRINT in (
        COMMAND_REQUIREMENTS[JobCommand.APPROVE]
    )


def test_command_id_is_stable_per_run_step_command_and_attempt() -> None:
    first = job_command_id("run-1", "step-1", JobCommand.RETRY, "attempt-2")
    replay = job_command_id("run-1", "step-1", JobCommand.RETRY, "attempt-2")
    next_attempt = job_command_id(
        "run-1", "step-1", JobCommand.RETRY, "attempt-3"
    )

    assert replay == first
    assert next_attempt != first


def test_existing_job_command_requires_expected_snapshot() -> None:
    envelope = JobCommandEnvelope(
        command_id="command-1",
        run_id="run-1",
        step_id="step-1",
        command=JobCommand.CANCEL,
        requested_at="2026-07-25T22:30:00+08:00",
        legacy_job_id="job-1",
    )

    with pytest.raises(JobCommandContractError, match="expected snapshot"):
        envelope.validate()


def test_retry_and_approval_commands_require_replay_guards() -> None:
    base = {
        "command_id": "command-1",
        "run_id": "run-1",
        "step_id": "step-1",
        "requested_at": "2026-07-25T22:30:00+08:00",
        "legacy_job_id": "job-1",
        "expected_job_status": "failed",
        "expected_job_updated_at": "2026-07-25T22:29:00+08:00",
    }
    retry = JobCommandEnvelope(command=JobCommand.RETRY, **base)
    approve = JobCommandEnvelope(command=JobCommand.APPROVE, **base)

    with pytest.raises(JobCommandContractError, match="attempt_id"):
        retry.validate()
    with pytest.raises(JobCommandContractError, match="fingerprint"):
        approve.validate()


def test_complete_job_requires_verification_before_runtime_completion() -> None:
    pending = project_authoritative_job_state("complete")
    outcome_pending = project_authoritative_job_state(
        "complete",
        result_verified=True,
    )
    verified = project_authoritative_job_state(
        "complete",
        result_verified=True,
        outcome_verified=True,
    )
    rejected = project_authoritative_job_state("complete", result_verified=False)

    assert pending.run_state is RunState.VERIFYING
    assert pending.step_state is StepState.VERIFYING
    assert pending.terminal is False
    assert pending.verification_required is True
    assert outcome_pending.run_state is RunState.VERIFYING
    assert outcome_pending.terminal is False
    assert verified.run_state is RunState.COMPLETED
    assert verified.step_state is StepState.COMPLETED
    assert rejected.run_state is RunState.FAILED
    assert rejected.step_state is StepState.FAILED


def test_legacy_attempt_identity_ignores_progress_timestamp() -> None:
    job = {
        "id": "job-legacy-progress",
        "createdAt": "2026-07-26T20:00:00+08:00",
        "updatedAt": "2026-07-26T20:01:00+08:00",
    }
    first, source = legacy_job_attempt_identity(job)

    job["updatedAt"] = "2026-07-26T20:02:00+08:00"
    second, second_source = legacy_job_attempt_identity(job)

    assert second == first
    assert source == second_source == "legacy_snapshot"


@pytest.mark.parametrize(
    ("legacy_status", "run_state", "step_state"),
    [
        ("queued", RunState.EXECUTING, StepState.READY),
        ("running", RunState.EXECUTING, StepState.RUNNING),
        (
            "waiting_approval",
            RunState.WAITING_APPROVAL,
            StepState.WAITING_APPROVAL,
        ),
        ("failed", RunState.FAILED, StepState.FAILED),
        ("cancelled", RunState.CANCELLED, StepState.CANCELLED),
    ],
)
def test_authoritative_status_projection_is_explicit(
    legacy_status: str,
    run_state: RunState,
    step_state: StepState,
) -> None:
    projection = project_authoritative_job_state(legacy_status)

    assert projection.run_state is run_state
    assert projection.step_state is step_state


def test_unknown_legacy_status_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported legacy Job status"):
        project_authoritative_job_state("unknown")
