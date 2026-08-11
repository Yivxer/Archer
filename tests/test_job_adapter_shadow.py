from __future__ import annotations

from core.authority_migration import list_authority_comparisons
from core.job_adapter_shadow import (
    LEGACY_JOB_V1_SHADOW_ADAPTER_ID,
    audit_job_adapter_v1_shadow,
    record_job_adapter_shadow_audit,
)
from core.job_execution_adapter import JobCommand
from core.run_contract import RunRecord
from core.run_store import create_run, get_run, list_events
from memory.migrations import run_migrations

NOW = "2026-07-31T13:00:00+08:00"


def _database(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(
        db_path,
        RunRecord(
            id="run-job-shadow-1",
            objective="audit legacy Job",
            source="shadow.task_plan",
            created_at=NOW,
            updated_at=NOW,
        ),
        event_id="event-run-job-shadow-created",
    )
    return db_path


def _decision(audit, command: JobCommand):
    return next(item for item in audit.command_decisions if item.command is command)


def test_vault_reflection_candidate_is_scoped_but_never_enabled() -> None:
    audit = audit_job_adapter_v1_shadow("vault_reflection")

    assert audit.adapter_id == LEGACY_JOB_V1_SHADOW_ADAPTER_ID
    assert audit.authority_enabled is False
    assert _decision(audit, JobCommand.CREATE).permitted is True
    assert _decision(audit, JobCommand.START).permitted is True
    assert _decision(audit, JobCommand.CANCEL).permitted is False
    assert "cooperative_cancellation" in {
        item.value for item in _decision(
            audit,
            JobCommand.CANCEL,
        ).missing_capabilities
    }


def test_generic_jobs_remain_blocked_by_missing_outcome_verification() -> None:
    for job_kind in ("analysis", "chat", "review"):
        audit = audit_job_adapter_v1_shadow(job_kind)
        for command in (
            JobCommand.CREATE,
            JobCommand.START,
            JobCommand.RETRY,
            JobCommand.APPROVE,
        ):
            decision = _decision(audit, command)
            assert decision.permitted is False
            assert "outcome_verification" in {
                item.value for item in decision.missing_capabilities
            }


def test_shadow_audit_records_no_body_idempotent_receipt_without_state_change(
    tmp_path,
) -> None:
    db_path = _database(tmp_path)
    before = get_run(db_path, "run-job-shadow-1")
    event_count = len(list_events(db_path, "run-job-shadow-1"))
    arguments = {
        "run_id": "run-job-shadow-1",
        "legacy_job_id": "job-1",
        "job_kind": "vault_reflection",
        "legacy_status": "complete",
        "job_updated_at": NOW,
        "evidence_summary": {
            "attemptId": "attempt-1",
            "verificationId": "verification-1",
            "verificationStatus": "verified",
            "outcomeVerificationId": "outcome-1",
            "outcomeStatus": "verified",
            "result": "must-not-be-stored",
        },
        "recorded_at": NOW,
    }

    first_audit, first_receipt = record_job_adapter_shadow_audit(
        db_path,
        **arguments,
    )
    replay_audit, replay_receipt = record_job_adapter_shadow_audit(
        db_path,
        **arguments,
    )

    assert replay_audit == first_audit
    assert replay_receipt == first_receipt
    assert get_run(db_path, "run-job-shadow-1") == before
    assert len(list_events(db_path, "run-job-shadow-1")) == event_count
    receipts = list_authority_comparisons(
        db_path,
        domain="background_job",
        run_id="run-job-shadow-1",
    )
    assert receipts == [first_receipt]
    assert "must-not-be-stored" not in str(first_receipt.to_dict())
