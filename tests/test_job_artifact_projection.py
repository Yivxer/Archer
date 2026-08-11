from __future__ import annotations

from core.authority_migration import AuthorityVerdict, list_authority_comparisons
from core.job_adapter_shadow import audit_job_adapter_v1_shadow
from core.job_execution_adapter import JobCommand
from core.outcome_store import list_artifacts
from core.run_contract import RunState
from core.run_store import get_run, list_events
from core.step_store import list_steps_for_run
from core.task_plan_job_shadow import (
    bind_task_plan_job,
    record_task_plan_job_observation,
)
from core.task_plan_observation import record_task_plan_observation
from core.task_plan_shadow import project_task_plan_shadow
from memory.migrations import run_migrations

NOW = "2026-07-31T16:00:00+08:00"
FINGERPRINT = "a" * 64


def _setup(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-job-artifact",
        plan_event={
            "id": "plan-job-artifact",
            "title": "投影旧 Job 结果",
            "status": "proposed",
            "steps": [
                {"id": 1, "action": "分析材料"},
                {"id": 2, "action": "形成结论"},
            ],
        },
        now=NOW,
    )
    record_task_plan_observation(
        db_path,
        run_id=projection.run_id,
        plan_id="plan-job-artifact",
        trace_id="trace-job-artifact",
        legacy_status="accepted",
        observed_at="2026-07-31T16:00:01+08:00",
    )
    bind_task_plan_job(
        db_path,
        run_id=projection.run_id,
        plan_id="plan-job-artifact",
        legacy_job_id="job-artifact-1",
        job_kind="chat",
        bound_at="2026-07-31T16:00:02+08:00",
    )
    return db_path, projection.run_id


def _verified_evidence() -> dict[str, str]:
    return {
        "artifactId": "job-result-1",
        "contentFingerprint": FINGERPRINT,
        "attemptId": "start-command-1",
        "attemptIdentitySource": "start_command",
        "verificationId": "job-verification-1",
        "verificationArtifactId": "job-result-1",
        "verificationExpectedFingerprint": FINGERPRINT,
        "verificationObservedFingerprint": FINGERPRINT,
        "verificationStatus": "verified",
        "verifier": "legacy_job.persisted_result.v1",
        "verificationReason": "persisted_result_matches",
        "outcomeStatus": "uncertain",
    }


def _decision(audit, command: JobCommand):
    return next(item for item in audit.command_decisions if item.command is command)


def test_verified_result_projects_identity_without_body_or_state_change(tmp_path):
    db_path, run_id = _setup(tmp_path)
    steps = list_steps_for_run(db_path, run_id)
    before_run = get_run(db_path, run_id)
    before_events = len(list_events(db_path, run_id))

    arguments = {
        "run_id": run_id,
        "legacy_job_id": "job-artifact-1",
        "legacy_status": "complete",
        "job_updated_at": "2026-07-31T16:00:03+08:00",
        "observed_at": "2026-07-31T16:00:04+08:00",
        "evidence_summary": _verified_evidence(),
    }
    first = record_task_plan_job_observation(db_path, **arguments)
    replay = record_task_plan_job_observation(db_path, **arguments)

    artifacts = list_artifacts(db_path, steps[-1].id)
    assert replay == first
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.step_id == steps[-1].id
    assert artifact.uri_or_path == "runtime://jobs/job-artifact-1/result"
    assert artifact.fingerprint == FINGERPRINT
    assert artifact.metadata == {
        "attemptId": "start-command-1",
        "legacyArtifactId": "job-result-1",
        "legacyVerificationId": "job-verification-1",
        "jobKind": "chat",
    }
    assert set(artifact.metadata) == {
        "attemptId",
        "legacyArtifactId",
        "legacyVerificationId",
        "jobKind",
    }
    assert get_run(db_path, run_id) == before_run
    assert get_run(db_path, run_id).state is RunState.WAITING_USER
    assert len(list_events(db_path, run_id)) == before_events + 1


def test_missing_or_mismatched_verification_fails_closed(tmp_path):
    db_path, run_id = _setup(tmp_path)
    evidence = _verified_evidence()
    evidence["verificationObservedFingerprint"] = "b" * 64

    record_task_plan_job_observation(
        db_path,
        run_id=run_id,
        legacy_job_id="job-artifact-1",
        legacy_status="complete",
        job_updated_at="2026-07-31T16:00:03+08:00",
        observed_at="2026-07-31T16:00:04+08:00",
        evidence_summary=evidence,
    )

    steps = list_steps_for_run(db_path, run_id)
    assert list_artifacts(db_path, steps[-1].id) == []
    receipts = list_authority_comparisons(
        db_path,
        domain="background_job",
        run_id=run_id,
    )
    assert any(
        receipt.verdict is AuthorityVerdict.DRIFTED
        and receipt.reason == "verification_observed_fingerprint_mismatch"
        for receipt in receipts
    )


def test_current_runtime_artifact_unlocks_only_shadow_user_confirmation_path():
    blocked = audit_job_adapter_v1_shadow("chat")
    ready = audit_job_adapter_v1_shadow("chat", runtime_artifact_ready=True)

    assert _decision(blocked, JobCommand.CREATE).permitted is False
    assert _decision(ready, JobCommand.CREATE).permitted is True
    assert _decision(ready, JobCommand.START).permitted is True
    assert _decision(ready, JobCommand.CANCEL).permitted is False
    assert ready.authority_enabled is False
