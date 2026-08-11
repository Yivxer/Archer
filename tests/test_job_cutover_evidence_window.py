from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from core.authority_migration import (
    AuthorityVerdict,
    MigrationMode,
    build_authority_comparison,
    record_authority_comparison,
)
from core.job_cutover_evidence_window import (
    REQUIRED_COMMANDS,
    EvidenceWindowError,
    EvidenceWindowStatus,
    review_job_cutover_evidence_window,
)
from core.job_execution_adapter import JobCommand
from core.runtime_context import create_runtime_context
from core.task_plan_job_shadow import (
    bind_task_plan_job,
    record_task_plan_job_observation,
)
from core.task_plan_observation import record_task_plan_observation
from core.task_plan_shadow import project_task_plan_shadow
from memory.migrations import run_migrations
from terminal.api.fastapi_app import create_app


def _run(db_path, index: int, *, verified: bool = True) -> str:
    projection = project_task_plan_shadow(
        db_path,
        trace_id=f"trace-evidence-{index}",
        plan_event={
            "id": f"plan-evidence-{index}",
            "title": "审查真实 Job shadow evidence",
            "status": "proposed",
            "steps": [{
                "id": 1,
                "action": "观察旧 Job",
                "tool": "vault_reflection",
            }],
        },
        now=f"2026-07-31T21:{index:02d}:00+08:00",
    )
    run_id = projection.run_id
    observed_at = f"2026-07-31T21:{index:02d}:01+08:00"
    record_task_plan_observation(
        db_path,
        run_id=run_id,
        plan_id=f"plan-evidence-{index}",
        trace_id=f"trace-evidence-{index}",
        legacy_status="accepted",
        observed_at=observed_at,
    )
    bind_task_plan_job(
        db_path,
        run_id=run_id,
        plan_id=f"plan-evidence-{index}",
        legacy_job_id=f"job-evidence-{index}",
        job_kind="vault_reflection",
        bound_at=observed_at,
    )
    record_task_plan_job_observation(
        db_path,
        run_id=run_id,
        legacy_job_id=f"job-evidence-{index}",
        legacy_status="complete" if verified else "failed",
        job_updated_at=f"2026-07-31T21:{index:02d}:02+08:00",
        observed_at=f"2026-07-31T21:{index:02d}:03+08:00",
        evidence_summary={
            "attemptId": f"attempt-evidence-{index}",
            "artifactId": f"artifact-evidence-{index}",
            "contentFingerprint": "a" * 64,
            "verificationId": f"verification-evidence-{index}",
            "verificationArtifactId": f"artifact-evidence-{index}",
            "verificationExpectedFingerprint": "a" * 64,
            "verificationObservedFingerprint": "a" * 64,
            "verificationStatus": "verified" if verified else "failed",
            "verifier": "legacy_job.persisted_result.v1",
            "outcomeVerificationId": f"outcome-evidence-{index}",
            "outcomeStatus": "verified" if verified else "failed",
            "outcomeVerifier": "legacy_job.vault_reflection.record.v1",
        },
    )
    return run_id


def _observation_receipt(
    db_path,
    run_id: str,
    command: JobCommand,
    *,
    status: str = "candidate",
    job_kind: str = "vault_reflection",
    verdict: AuthorityVerdict = AuthorityVerdict.ALIGNED,
    recorded_at: str = "2026-07-31T22:00:00+08:00",
) -> None:
    record_authority_comparison(
        db_path,
        build_authority_comparison(
            run_id=run_id,
            domain="background_job",
            legacy_id=f"job-{run_id}-{command.value}",
            mode=MigrationMode.SHADOW,
            legacy_snapshot={
                "runId": run_id,
                "command": command.value,
                "status": status,
            },
            runtime_snapshot={
                "jobKind": job_kind,
                "command": command.value,
                "status": status,
            },
            verdict=verdict,
            reason=(
                "background_job_command_observation:"
                f"{job_kind}:{command.value}:{status}"
            ),
            recorded_at=recorded_at,
        ),
    )


def _database(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    return db_path


def test_empty_shadow_window_is_ready_for_authentic_collection(tmp_path) -> None:
    db_path = _database(tmp_path)

    report = review_job_cutover_evidence_window(db_path, {})

    assert report.status is EvidenceWindowStatus.NOT_STARTED
    assert report.migration_mode == "shadow"
    assert report.authority_enabled is False
    assert report.route_receipt_count == 0
    assert all(not item.meets_threshold for item in report.command_reviews)
    assert report.blockers == ()
    assert report.collection_path_ready is True
    assert "accepted_task_plan" in report.collection_path_evidence
    assert report.to_dict()["excludedUnobservableCommands"] == [
        "approve", "deny"
    ]
    assert report.to_dict()["syntheticEvidenceAccepted"] is False


def test_one_real_run_keeps_window_collecting(tmp_path) -> None:
    db_path = _database(tmp_path)
    run_id = _run(db_path, 1)
    for command in REQUIRED_COMMANDS:
        _observation_receipt(db_path, run_id, command)

    report = review_job_cutover_evidence_window(db_path, {})

    assert report.status is EvidenceWindowStatus.COLLECTING
    assert report.route_receipt_count == 3
    assert report.distinct_run_count == 1
    assert all(
        item.candidate_count == 1
        for item in report.command_reviews
        if item.observable_in_current_workflow
    )
    assert all(
        item.verified_candidate_count == 1
        for item in report.command_reviews
        if item.observable_in_current_workflow
    )
    assert all(
        item.distinct_candidate_runs == 1
        for item in report.command_reviews
        if item.observable_in_current_workflow
    )


def test_three_clean_distinct_runs_make_window_reviewable_not_authoritative(
    tmp_path,
) -> None:
    db_path = _database(tmp_path)
    for index in range(1, 4):
        run_id = _run(db_path, index)
        for command in REQUIRED_COMMANDS:
            _observation_receipt(
                db_path,
                run_id,
                command,
                recorded_at=f"2026-07-31T22:{index:02d}:00+08:00",
            )

    report = review_job_cutover_evidence_window(db_path, {})

    assert report.status is EvidenceWindowStatus.REVIEWABLE
    assert report.authority_enabled is False
    assert report.blockers == ()
    assert all(
        item.meets_threshold
        for item in report.command_reviews
        if item.observable_in_current_workflow
    )


def test_terminal_unverified_run_blocks_and_never_counts_candidate(tmp_path) -> None:
    db_path = _database(tmp_path)
    run_id = _run(db_path, 1, verified=False)
    _observation_receipt(db_path, run_id, JobCommand.CREATE)

    report = review_job_cutover_evidence_window(db_path, {})

    review = report.command_reviews[0]
    assert report.status is EvidenceWindowStatus.BLOCKED
    assert review.candidate_count == 1
    assert review.verified_candidate_count == 0
    assert review.unverified_candidate_count == 1
    assert f"candidate_run_terminal_unverified:{run_id}" in report.blockers


@pytest.mark.parametrize(
    ("command", "status", "job_kind", "verdict", "blocker"),
    [
        (JobCommand.RETRY, "conflict", "vault_reflection",
         AuthorityVerdict.DRIFTED, "conflict:retry"),
        (JobCommand.APPROVE, "forbidden", "vault_reflection",
         AuthorityVerdict.DRIFTED, "forbidden:approve"),
        (JobCommand.CANCEL, "candidate", "vault_reflection",
         AuthorityVerdict.ALIGNED, "cancel_not_fail_closed"),
        (JobCommand.CREATE, "candidate", "chat",
         AuthorityVerdict.ALIGNED, "generic_candidate:chat:create"),
    ],
)
def test_unsafe_observation_blocks_window(
    tmp_path,
    command: JobCommand,
    status: str,
    job_kind: str,
    verdict: AuthorityVerdict,
    blocker: str,
) -> None:
    db_path = _database(tmp_path)
    run_id = _run(db_path, 1)
    _observation_receipt(
        db_path,
        run_id,
        command,
        status=status,
        job_kind=job_kind,
        verdict=verdict,
    )

    report = review_job_cutover_evidence_window(db_path, {})

    assert report.status is EvidenceWindowStatus.BLOCKED
    assert blocker in report.blockers
    assert report.authority_enabled is False


def test_authoritative_configuration_blocks_evidence_collection(tmp_path) -> None:
    db_path = _database(tmp_path)

    report = review_job_cutover_evidence_window(
        db_path,
        {"runtime": {"migration_modes": {"background_job": "authoritative"}}},
    )

    assert report.status is EvidenceWindowStatus.BLOCKED
    assert "background_job_migration_mode_not_shadow" in report.blockers
    assert report.authority_enabled is False


def test_explicit_window_boundary_filters_older_receipts(tmp_path) -> None:
    db_path = _database(tmp_path)
    run_id = _run(db_path, 1)
    _observation_receipt(
        db_path,
        run_id,
        JobCommand.CREATE,
        recorded_at="2026-07-31T21:00:00+08:00",
    )

    report = review_job_cutover_evidence_window(
        db_path,
        {},
        started_at="2026-07-31T22:00:00+08:00",
    )

    assert report.status is EvidenceWindowStatus.NOT_STARTED
    assert report.route_receipt_count == 0
    with pytest.raises(EvidenceWindowError):
        review_job_cutover_evidence_window(
            db_path,
            {},
            started_at="2026-07-31T22:00:00",
        )


def test_evidence_window_api_is_authenticated_and_read_only(tmp_path) -> None:
    db_path = _database(tmp_path)
    context = create_runtime_context(
        db_path=db_path,
        clock=lambda: datetime.fromisoformat("2026-07-31T22:00:00+08:00"),
    )
    app = create_app("test-token", runtime_context=context)
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(app) as client:
        unauthorized = client.get(
            "/runtime/authority/background-job/evidence-window"
        )
        response = client.get(
            "/runtime/authority/background-job/evidence-window",
            headers=headers,
        )
        invalid = client.get(
            "/runtime/authority/background-job/evidence-window",
            params={"startedAt": "invalid"},
            headers=headers,
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json()["evidenceWindow"]["status"] == "not_started"
    assert response.json()["evidenceWindow"]["collectionPathReady"] is True
    assert response.json()["evidenceWindow"]["authorityEnabled"] is False
    assert invalid.status_code == 400
