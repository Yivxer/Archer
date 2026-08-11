from __future__ import annotations

import sqlite3

import pytest

from core.run_contract import RunState
from core.run_store import get_run, list_events
from core.task_plan_job_shadow import (
    TaskPlanJobShadowConflict,
    TaskPlanJobShadowUnavailable,
    bind_task_plan_job,
    list_task_plan_job_bindings,
    list_task_plan_job_observations,
    record_task_plan_job_observation,
)
from core.task_plan_observation import record_task_plan_observation
from core.task_plan_shadow import project_task_plan_shadow
from memory.migrations import LATEST_SCHEMA_VERSION, MIGRATIONS, run_migrations

NOW = "2026-07-25T12:00:00+08:00"


def _accepted_shadow(db_path) -> str:
    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-job-shadow",
        plan_event={
            "id": "plan-job-shadow",
            "title": "关联旧 Job",
            "status": "proposed",
            "steps": [],
        },
        now=NOW,
    )
    record_task_plan_observation(
        db_path,
        run_id=projection.run_id,
        plan_id="plan-job-shadow",
        trace_id="trace-job-shadow",
        legacy_status="accepted",
        observed_at="2026-07-25T12:00:01+08:00",
    )
    return projection.run_id


def test_binding_is_idempotent_and_preserves_shadow_authority(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run_id = _accepted_shadow(db_path)
    event_count = len(list_events(db_path, run_id))

    first, first_run = bind_task_plan_job(
        db_path,
        run_id=run_id,
        plan_id="plan-job-shadow",
        legacy_job_id="job-1",
        job_kind="chat",
        bound_at="2026-07-25T12:00:02+08:00",
    )
    second, second_run = bind_task_plan_job(
        db_path,
        run_id=run_id,
        plan_id="plan-job-shadow",
        legacy_job_id="job-1",
        job_kind="chat",
        bound_at="2026-07-25T12:00:03+08:00",
    )

    assert second == first
    assert first.runtime_execution_claimed is False
    assert first_run.state is second_run.state is RunState.WAITING_USER
    assert get_run(db_path, run_id).state is RunState.WAITING_USER
    assert len(list_events(db_path, run_id)) == event_count
    assert len(list_task_plan_job_bindings(db_path, run_id)) == 1


def test_binding_requires_accepted_plan_and_rejects_collision(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-unaccepted",
        plan_event={
            "id": "plan-unaccepted",
            "title": "未接受计划",
            "status": "proposed",
            "steps": [],
        },
        now=NOW,
    )

    with pytest.raises(TaskPlanJobShadowUnavailable):
        bind_task_plan_job(
            db_path,
            run_id=projection.run_id,
            plan_id="plan-unaccepted",
            legacy_job_id="job-unaccepted",
            job_kind="chat",
            bound_at=NOW,
        )

    run_id = _accepted_shadow(db_path)
    bind_task_plan_job(
        db_path,
        run_id=run_id,
        plan_id="plan-job-shadow",
        legacy_job_id="job-1",
        job_kind="chat",
        bound_at=NOW,
    )
    with pytest.raises(TaskPlanJobShadowConflict):
        bind_task_plan_job(
            db_path,
            run_id=run_id,
            plan_id="plan-job-shadow",
            legacy_job_id="job-2",
            job_kind="chat",
            bound_at=NOW,
        )


def test_status_observations_are_append_only_and_do_not_transition_run(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run_id = _accepted_shadow(db_path)
    binding, _ = bind_task_plan_job(
        db_path,
        run_id=run_id,
        plan_id="plan-job-shadow",
        legacy_job_id="job-1",
        job_kind="chat",
        bound_at=NOW,
    )
    event_count = len(list_events(db_path, run_id))
    result_evidence = {
        "artifactId": "job-result-1",
        "contentFingerprint": "sha256-result",
        "attemptId": "start-command-1",
        "attemptIdentitySource": "start_command",
        "verificationId": "job-verification-1",
        "verificationStatus": "verified",
        "verifier": "legacy_job.persisted_result.v1",
        "verificationReason": "persisted_result_matches",
        "outcomeVerificationId": "job-outcome-1",
        "outcomeStatus": "uncertain",
        "outcomeVerifier": "legacy_job.outcome.v1",
        "outcomeReason": "no_deterministic_verifier_for_kind",
        "result": "must-not-enter-shadow",
    }

    for index, status in enumerate(
        ("queued", "running", "waiting_approval", "complete"),
        start=1,
    ):
        first = record_task_plan_job_observation(
            db_path,
            run_id=run_id,
            legacy_job_id="job-1",
            legacy_status=status,
            job_updated_at=f"2026-07-25T12:00:0{index}+08:00",
            observed_at=f"2026-07-25T12:01:0{index}+08:00",
            evidence_summary=result_evidence if status == "complete" else None,
        )
        replay = record_task_plan_job_observation(
            db_path,
            run_id=run_id,
            legacy_job_id="job-1",
            legacy_status=status,
            job_updated_at=f"2026-07-25T12:00:0{index}+08:00",
            observed_at=f"2026-07-25T12:02:0{index}+08:00",
            evidence_summary=result_evidence if status == "complete" else None,
        )
        assert replay == first
        assert first.binding_id == binding.id
        assert first.runtime_state_changed is False

    revised_receipt = record_task_plan_job_observation(
        db_path,
        run_id=run_id,
        legacy_job_id="job-1",
        legacy_status="complete",
        job_updated_at="2026-07-25T12:00:04+08:00",
        observed_at="2026-07-25T12:03:04+08:00",
        evidence_summary={
            **result_evidence,
            "verificationId": "job-verification-2",
            "verificationStatus": "uncertain",
            "verificationReason": "persisted_job_unreadable",
        },
    )

    observations = list_task_plan_job_observations(db_path, run_id)
    assert [item.legacy_status for item in observations] == [
        "queued", "running", "waiting_approval", "complete", "complete"
    ]
    terminal = observations[-2]
    assert terminal.verification_receipt_id == "job-verification-1"
    assert terminal.evidence_summary["verificationStatus"] == "verified"
    assert terminal.evidence_summary["outcomeStatus"] == "uncertain"
    assert terminal.evidence_summary["outcomeVerificationId"] == (
        "job-outcome-1"
    )
    assert "result" not in terminal.to_dict()["evidence_summary"]
    assert revised_receipt.id != terminal.id
    assert revised_receipt.evidence_summary["verificationStatus"] == "uncertain"

    assert get_run(db_path, run_id).state is RunState.WAITING_USER
    assert len(list_events(db_path, run_id)) == event_count

    with pytest.raises(
        TaskPlanJobShadowUnavailable,
        match="unsupported Job outcome status",
    ):
        record_task_plan_job_observation(
            db_path,
            run_id=run_id,
            legacy_job_id="job-1",
            legacy_status="complete",
            job_updated_at="2026-07-25T12:00:05+08:00",
            observed_at="2026-07-25T12:03:05+08:00",
            evidence_summary={"outcomeStatus": "claimed_complete"},
        )

    conn = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE runtime_task_plan_job_bindings SET job_kind = 'plan'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM runtime_task_plan_job_observations")
    conn.close()


def test_v9_migration_preserves_v8_job_observations(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path, migrations=MIGRATIONS[:8])
    run_id = _accepted_shadow(db_path)
    binding, _ = bind_task_plan_job(
        db_path,
        run_id=run_id,
        plan_id="plan-job-shadow",
        legacy_job_id="job-v8",
        job_kind="chat",
        bound_at=NOW,
    )
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO runtime_task_plan_job_observations(
            id, binding_id, run_id, legacy_job_id, legacy_status,
            job_updated_at, observed_at, runtime_state_changed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            "observation-v8",
            binding.id,
            run_id,
            "job-v8",
            "complete",
            "2026-07-25T12:04:00+08:00",
            "2026-07-25T12:04:01+08:00",
        ),
    )
    conn.commit()
    conn.close()

    result = run_migrations(db_path)

    assert result.applied == list(range(9, LATEST_SCHEMA_VERSION + 1))
    observation = list_task_plan_job_observations(db_path, run_id)[0]
    assert observation.id == "observation-v8"
    assert observation.verification_receipt_id == ""
    assert observation.evidence_summary == {}
