from __future__ import annotations

from dataclasses import replace

import pytest

from core.authority_migration import (
    AuthorityVerdict,
    MigrationMode,
    build_authority_comparison,
    list_authority_comparisons,
    record_authority_comparison,
)
from core.job_authority_cutover import (
    JobCutoverRequest,
    JobCutoverStatus,
    evaluate_job_authority_cutover,
    record_job_authority_cutover_decision,
)
from core.job_execution_adapter import JobCommand, JobCommandEnvelope
from core.run_store import get_run, list_events
from core.step_store import list_steps_for_run
from core.task_plan_job_shadow import (
    bind_task_plan_job,
    record_task_plan_job_observation,
)
from core.task_plan_observation import record_task_plan_observation
from core.task_plan_shadow import project_task_plan_shadow
from memory.migrations import run_migrations

NOW = "2026-07-31T18:00:00+08:00"


def _setup(tmp_path, *, job_kind: str = "vault_reflection"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-cutover",
        plan_event={
            "id": "plan-cutover",
            "title": "验证 Job authority cutover",
            "status": "proposed",
            "steps": [{
                "id": 1,
                "action": "执行旧 Job",
                "tool": "vault_reflection",
            }],
        },
        now=NOW,
    )
    record_task_plan_observation(
        db_path,
        run_id=projection.run_id,
        plan_id="plan-cutover",
        trace_id="trace-cutover",
        legacy_status="accepted",
        observed_at="2026-07-31T18:00:01+08:00",
    )
    bind_task_plan_job(
        db_path,
        run_id=projection.run_id,
        plan_id="plan-cutover",
        legacy_job_id="job-cutover-1",
        job_kind=job_kind,
        bound_at="2026-07-31T18:00:02+08:00",
    )
    return db_path, projection.run_id


def _shadow_receipt(db_path, run_id: str, legacy_id: str):
    return [
        item
        for item in list_authority_comparisons(
            db_path,
            domain="background_job",
            run_id=run_id,
        )
        if item.legacy_id == legacy_id
        and item.reason == "legacy_job_shadow_projection_aligned"
    ][-1]


def _observe(
    db_path,
    run_id: str,
    *,
    status: str,
    updated_at: str = "2026-07-31T18:00:03+08:00",
    attempt_id: str = "attempt-cutover-1",
):
    record_task_plan_job_observation(
        db_path,
        run_id=run_id,
        legacy_job_id="job-cutover-1",
        legacy_status=status,
        job_updated_at=updated_at,
        observed_at=updated_at,
        evidence_summary={"attemptId": attempt_id},
    )
    return _shadow_receipt(db_path, run_id, "job-cutover-1")


def _request(
    db_path,
    run_id: str,
    command: JobCommand,
    receipt_id: str,
    *,
    status: str | None,
    updated_at: str | None,
    attempt_id: str | None,
    job_kind: str = "vault_reflection",
) -> JobCutoverRequest:
    run = get_run(db_path, run_id)
    assert run is not None
    step = list_steps_for_run(db_path, run_id)[-1]
    return JobCutoverRequest(
        envelope=JobCommandEnvelope(
            command_id=f"command-{command.value}-1",
            run_id=run_id,
            step_id=step.id,
            command=command,
            requested_at=NOW,
            legacy_job_id=(
                None if command is JobCommand.CREATE else "job-cutover-1"
            ),
            expected_job_status=status,
            expected_job_updated_at=updated_at,
            attempt_id=attempt_id,
            approval_event_id=(
                "approval-event-1"
                if command in {JobCommand.APPROVE, JobCommand.DENY}
                else None
            ),
            approval_fingerprint=(
                "approval-fingerprint-1"
                if command in {JobCommand.APPROVE, JobCommand.DENY}
                else None
            ),
        ),
        job_kind=job_kind,
        expected_run_version=run.version,
        expected_run_state=run.state,
        expected_step_state=step.state,
        expected_attempt_id=attempt_id,
        comparison_receipt_id=receipt_id,
    )


def _create_request(db_path, run_id: str) -> JobCutoverRequest:
    run = get_run(db_path, run_id)
    assert run is not None
    step = list_steps_for_run(db_path, run_id)[-1]
    command_id = "command-create-1"
    receipt = record_authority_comparison(
        db_path,
        build_authority_comparison(
            run_id=run_id,
            domain="background_job",
            legacy_id=command_id,
            mode=MigrationMode.SHADOW,
            legacy_snapshot={"commandId": command_id, "jobExists": False},
            runtime_snapshot={"jobKind": "vault_reflection"},
            verdict=AuthorityVerdict.ALIGNED,
            reason="legacy_job_create_shadow_projection_aligned",
            recorded_at=NOW,
        ),
    )
    return JobCutoverRequest(
        envelope=JobCommandEnvelope(
            command_id=command_id,
            run_id=run_id,
            step_id=step.id,
            command=JobCommand.CREATE,
            requested_at=NOW,
        ),
        job_kind="vault_reflection",
        expected_run_version=run.version,
        expected_run_state=run.state,
        expected_step_state=step.state,
        expected_attempt_id=None,
        comparison_receipt_id=receipt.id,
    )


@pytest.mark.parametrize(
    ("command", "status"),
    [
        (JobCommand.START, "queued"),
        (JobCommand.RETRY, "failed"),
    ],
)
def test_vault_reflection_commands_form_shadow_candidates(
    tmp_path,
    command: JobCommand,
    status: str,
) -> None:
    db_path, run_id = _setup(tmp_path)
    updated_at = "2026-07-31T18:00:03+08:00"
    receipt = _observe(db_path, run_id, status=status, updated_at=updated_at)
    request = _request(
        db_path,
        run_id,
        command,
        receipt.id,
        status=status,
        updated_at=updated_at,
        attempt_id="attempt-cutover-1",
    )

    decision = evaluate_job_authority_cutover(db_path, {}, request)

    assert decision.status is JobCutoverStatus.CANDIDATE
    assert decision.authority_enabled is False
    assert decision.comparison_receipt_id == receipt.id


@pytest.mark.parametrize("command", [JobCommand.APPROVE, JobCommand.DENY])
def test_unreachable_vault_reflection_approval_commands_are_forbidden(
    tmp_path,
    command: JobCommand,
) -> None:
    db_path, run_id = _setup(tmp_path)
    updated_at = "2026-07-31T18:00:03+08:00"
    receipt = _observe(
        db_path,
        run_id,
        status="waiting_approval",
        updated_at=updated_at,
    )
    request = _request(
        db_path,
        run_id,
        command,
        receipt.id,
        status="waiting_approval",
        updated_at=updated_at,
        attempt_id="attempt-cutover-1",
    )

    decision = evaluate_job_authority_cutover(db_path, {}, request)

    assert decision.status is JobCutoverStatus.FORBIDDEN
    assert decision.reason == "command_not_reachable_for_job_kind"
    assert decision.authority_enabled is False


def test_create_uses_prospective_identity_and_requires_precreate_evidence(
    tmp_path,
) -> None:
    db_path, run_id = _setup(tmp_path)
    request = _create_request(db_path, run_id)

    candidate = evaluate_job_authority_cutover(db_path, {}, request)
    missing = evaluate_job_authority_cutover(
        db_path,
        {},
        replace(
            request,
            envelope=replace(request.envelope, command_id="command-create-2"),
        ),
    )

    assert candidate.status is JobCutoverStatus.CANDIDATE
    assert candidate.legacy_identity == request.envelope.command_id
    assert missing.status is JobCutoverStatus.FORBIDDEN
    assert missing.reason == "shadow_comparison_missing"


def test_cancel_and_generic_jobs_fail_closed(tmp_path) -> None:
    db_path, run_id = _setup(tmp_path)
    updated_at = "2026-07-31T18:00:03+08:00"
    receipt = _observe(db_path, run_id, status="running", updated_at=updated_at)
    cancel = _request(
        db_path,
        run_id,
        JobCommand.CANCEL,
        receipt.id,
        status="running",
        updated_at=updated_at,
        attempt_id="attempt-cutover-1",
    )
    cancel_decision = evaluate_job_authority_cutover(db_path, {}, cancel)

    assert cancel_decision.status is JobCutoverStatus.FORBIDDEN
    assert "cooperative_cancellation" in {
        item.value for item in cancel_decision.missing_capabilities
    }

    generic_db, generic_run = _setup(tmp_path / "generic", job_kind="analysis")
    generic_receipt = _observe(
        generic_db,
        generic_run,
        status="queued",
    )
    generic = _request(
        generic_db,
        generic_run,
        JobCommand.START,
        generic_receipt.id,
        status="queued",
        updated_at="2026-07-31T18:00:03+08:00",
        attempt_id="attempt-cutover-1",
        job_kind="analysis",
    )
    generic_decision = evaluate_job_authority_cutover(generic_db, {}, generic)

    assert generic_decision.status is JobCutoverStatus.FORBIDDEN
    assert "outcome_verification" in {
        item.value for item in generic_decision.missing_capabilities
    }


def test_latest_drifted_shadow_comparison_is_forbidden(tmp_path) -> None:
    db_path, run_id = _setup(tmp_path)
    updated_at = "2026-07-31T18:00:03+08:00"
    _observe(db_path, run_id, status="queued", updated_at=updated_at)
    drifted = record_authority_comparison(
        db_path,
        build_authority_comparison(
            run_id=run_id,
            domain="background_job",
            legacy_id="job-cutover-1",
            mode=MigrationMode.SHADOW,
            legacy_snapshot={
                "jobId": "job-cutover-1",
                "jobKind": "vault_reflection",
                "status": "queued",
                "updatedAt": updated_at,
                "attemptId": "attempt-cutover-1",
                "verificationId": None,
                "outcomeVerificationId": None,
            },
            runtime_snapshot={"drift": True},
            verdict=AuthorityVerdict.DRIFTED,
            reason="legacy_job_shadow_projection_aligned",
            recorded_at="2026-07-31T19:00:00+08:00",
        ),
    )
    request = _request(
        db_path,
        run_id,
        JobCommand.START,
        drifted.id,
        status="queued",
        updated_at=updated_at,
        attempt_id="attempt-cutover-1",
    )

    decision = evaluate_job_authority_cutover(db_path, {}, request)

    assert decision.status is JobCutoverStatus.FORBIDDEN
    assert decision.reason == "shadow_comparison_drifted"


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("expected_run_version", "run_version_stale"),
        ("expected_run_state", "run_state_stale"),
        ("expected_step_state", "step_state_stale"),
        ("expected_attempt_id", "command_attempt_stale"),
        ("comparison_receipt_id", "comparison_receipt_stale"),
    ],
)
def test_stale_runtime_and_evidence_snapshots_conflict(
    tmp_path,
    field: str,
    reason: str,
) -> None:
    db_path, run_id = _setup(tmp_path)
    updated_at = "2026-07-31T18:00:03+08:00"
    receipt = _observe(db_path, run_id, status="queued", updated_at=updated_at)
    request = _request(
        db_path,
        run_id,
        JobCommand.START,
        receipt.id,
        status="queued",
        updated_at=updated_at,
        attempt_id="attempt-cutover-1",
    )
    changes = {
        "expected_run_version": request.expected_run_version + 1,
        "expected_run_state": type(request.expected_run_state).EXECUTING,
        "expected_step_state": type(request.expected_step_state).RUNNING,
        "expected_attempt_id": "attempt-stale",
        "comparison_receipt_id": "comparison-stale",
    }

    decision = evaluate_job_authority_cutover(
        db_path,
        {},
        replace(request, **{field: changes[field]}),
    )

    assert decision.status is JobCutoverStatus.CONFLICT
    assert decision.reason == reason


def test_legacy_snapshot_supersedes_old_decision_and_replay_is_idempotent(
    tmp_path,
) -> None:
    db_path, run_id = _setup(tmp_path)
    first_updated_at = "2026-07-31T18:00:03+08:00"
    receipt = _observe(
        db_path,
        run_id,
        status="queued",
        updated_at=first_updated_at,
    )
    request = _request(
        db_path,
        run_id,
        JobCommand.START,
        receipt.id,
        status="queued",
        updated_at=first_updated_at,
        attempt_id="attempt-cutover-1",
    )
    before_events = len(list_events(db_path, run_id))

    first, first_receipt = record_job_authority_cutover_decision(
        db_path,
        {},
        request,
        recorded_at=NOW,
    )
    replay, replay_receipt = record_job_authority_cutover_decision(
        db_path,
        {},
        request,
        recorded_at="2026-07-31T18:00:04+08:00",
    )

    assert first.status is JobCutoverStatus.CANDIDATE
    assert replay == first
    assert replay_receipt == first_receipt
    assert len(list_events(db_path, run_id)) == before_events

    _observe(
        db_path,
        run_id,
        status="running",
        updated_at="2026-07-31T18:00:05+08:00",
    )
    stale = evaluate_job_authority_cutover(db_path, {}, request)
    assert stale.status is JobCutoverStatus.CONFLICT
    assert stale.reason == "legacy_job_snapshot_stale"


def test_authoritative_requires_domain_and_explicit_command_scope(tmp_path) -> None:
    db_path, run_id = _setup(tmp_path)
    request = _create_request(db_path, run_id)

    domain_only = evaluate_job_authority_cutover(
        db_path,
        {"runtime": {"migration_modes": {"background_job": "authoritative"}}},
        request,
    )
    scoped = evaluate_job_authority_cutover(
        db_path,
        {
            "runtime": {
                "migration_modes": {"background_job": "authoritative"},
                "command_migration_modes": {
                    "background_job": {
                        "vault_reflection": {"create": "authoritative"},
                    },
                },
            },
        },
        request,
    )

    assert domain_only.status is JobCutoverStatus.CANDIDATE
    assert domain_only.authority_enabled is False
    assert scoped.status is JobCutoverStatus.AUTHORITATIVE
    assert scoped.authority_enabled is True
