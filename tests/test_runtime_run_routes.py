from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.checkpoint_store import latest_checkpoint, record_checkpoint
from core.obsidian_runtime import (
    begin_approved_write,
    complete_write,
    stage_obsidian_write,
)
from core.run_contract import RunCheckpoint, RunRecord, RunState
from core.run_store import create_run, get_run
from core.runtime_context import create_runtime_context
from core.task_plan_shadow import project_task_plan_shadow
from memory.migrations import run_migrations
from terminal.api.fastapi_app import create_app


def _runtime_run() -> RunRecord:
    return RunRecord(
        id="run-api-1",
        objective="验证只读 Run 查询",
        source="api-test",
        created_at="2026-07-23T12:00:00+08:00",
        updated_at="2026-07-23T12:00:00+08:00",
    )


def _app_with_run(tmp_path: Path) -> FastAPI:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _runtime_run(), event_id="event-api-1")
    context = create_runtime_context(
        db_path=db_path,
        clock=lambda: datetime(2026, 7, 23, 12, 0, 0),
    )
    return create_app("test-token", runtime_context=context)


def _app_with_uncertain_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[FastAPI, str, Path]:
    import core.obsidian_runtime as obsidian_runtime

    db_path = tmp_path / "archer.db"
    target = tmp_path / "note.md"
    target.write_text("verified body", encoding="utf-8")
    run_migrations(db_path)
    binding = stage_obsidian_write(
        db_path,
        objective="写入测试笔记",
        approval_fingerprint="approval-1",
        now="2026-07-23T12:00:00+08:00",
    )
    begin_approved_write(
        db_path,
        binding,
        actual_fingerprint="approval-1",
        now="2026-07-23T12:00:01+08:00",
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            obsidian_runtime,
            "_content_matches",
            lambda *_args: (_ for _ in ()).throw(OSError("reader unavailable")),
        )
        complete_write(
            db_path,
            binding,
            args={"content": "verified body", "mode": "overwrite"},
            target_path=str(target),
            approval_fingerprint="approval-1",
            tool_call_id="tool-1",
            now="2026-07-23T12:00:02+08:00",
        )
    context = create_runtime_context(
        db_path=db_path,
        clock=lambda: datetime(2026, 7, 23, 12, 1, 0),
    )
    return create_app("test-token", runtime_context=context), binding.run_id, target


def _disable_startup_auto_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.runtime_recovery as runtime_recovery

    def classify_only(
        db_path: str | Path,
        *,
        now: str,
    ) -> runtime_recovery.StartupRecoveryReport:
        snapshots = tuple(runtime_recovery.list_non_terminal_runs(db_path))
        return runtime_recovery.StartupRecoveryReport(
            scanned_runs=snapshots,
            items=tuple(
                runtime_recovery.classify_startup_run(db_path, snapshot)
                for snapshot in snapshots
            ),
        )

    monkeypatch.setattr(
        runtime_recovery,
        "coordinate_startup_recovery",
        classify_only,
    )


def test_startup_scans_non_terminal_runtime_runs(tmp_path: Path) -> None:
    app = _app_with_run(tmp_path)

    with TestClient(app):
        recovered = app.state.runtime_recovery_runs

    assert recovered == [_runtime_run()]


def test_runtime_run_routes_are_authenticated_and_read_only(tmp_path: Path) -> None:
    app = _app_with_run(tmp_path)
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(app) as client:
        unauthorized = client.get("/runtime/runs")
        listing = client.get("/runtime/runs", headers=headers)
        detail = client.get("/runtime/runs/run-api-1", headers=headers)
        missing = client.get("/runtime/runs/missing", headers=headers)

    assert unauthorized.status_code == 401
    assert listing.status_code == 200
    assert listing.json()["scope"] == "non_terminal"
    assert [run["id"] for run in listing.json()["runs"]] == ["run-api-1"]
    assert listing.json()["recovery"]["items"][0]["classification"] == "manual"
    assert detail.status_code == 200
    assert detail.json()["run"]["objective"] == "验证只读 Run 查询"
    assert detail.json()["steps"] == []
    assert detail.json()["latestCheckpoint"] is None
    assert missing.status_code == 404


def test_runtime_run_detail_exposes_task_plan_shadow_steps(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-route-plan-1",
        plan_event={
            "id": "plan-route-1",
            "title": "查询影子计划",
            "status": "proposed",
            "steps": [
                {
                    "id": 1,
                    "action": "inspect_context",
                    "tool": "project_context",
                    "requiresApproval": False,
                }
            ],
        },
        now="2026-07-25T10:00:00+08:00",
    )
    app = create_app(
        "test-token",
        runtime_context=create_runtime_context(db_path=db_path),
    )

    with TestClient(app) as client:
        listing = client.get(
            "/runtime/runs",
            headers={"Authorization": "Bearer test-token"},
        )
        response = client.get(
            f"/runtime/runs/{projection.run_id}",
            headers={"Authorization": "Bearer test-token"},
        )

    assert listing.status_code == 200
    assert listing.json()["runs"] == []
    assert listing.json()["shadowRunCount"] == 1
    assert response.status_code == 200
    assert response.json()["run"]["source"] == "shadow.task_plan"
    assert response.json()["steps"][0]["title"] == "inspect_context"


def test_task_plan_shadow_observation_routes_preserve_legacy_authority(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-route-observation",
        plan_event={
            "id": "plan-route-observation",
            "title": "观察 accepted 状态",
            "status": "proposed",
            "steps": [
                {
                    "id": 1,
                    "action": "inspect_context",
                    "tool": "project_context",
                    "requiresApproval": False,
                }
            ],
        },
        now="2026-07-25T11:00:00+08:00",
    )
    app = create_app(
        "test-token",
        runtime_context=create_runtime_context(db_path=db_path),
    )
    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "planId": "plan-route-observation",
        "traceId": "trace-route-observation",
        "status": "accepted",
        "observedAt": "2026-07-25T11:01:00+08:00",
    }

    with TestClient(app) as client:
        observed = client.post(
            f"/runtime/task-plan-shadows/{projection.run_id}/observe",
            headers=headers,
            json=payload,
        )
        replayed = client.post(
            f"/runtime/task-plan-shadows/{projection.run_id}/observe",
            headers=headers,
            json=payload,
        )
        bound = client.post(
            f"/runtime/task-plan-shadows/{projection.run_id}/jobs/bind",
            headers=headers,
            json={
                "planId": "plan-route-observation",
                "jobId": "job-route-1",
                "jobKind": "chat",
                "boundAt": "2026-07-25T11:01:01+08:00",
            },
        )
        observed_job = client.post(
            (
                f"/runtime/task-plan-shadows/{projection.run_id}"
                "/jobs/job-route-1/observe"
            ),
            headers=headers,
            json={
                "status": "running",
                "jobUpdatedAt": "2026-07-25T11:01:02+08:00",
                "observedAt": "2026-07-25T11:01:03+08:00",
            },
        )
        replayed_job = client.post(
            (
                f"/runtime/task-plan-shadows/{projection.run_id}"
                "/jobs/job-route-1/observe"
            ),
            headers=headers,
            json={
                "status": "running",
                "jobUpdatedAt": "2026-07-25T11:01:02+08:00",
                "observedAt": "2026-07-25T11:01:04+08:00",
            },
        )
        completed_job = client.post(
            (
                f"/runtime/task-plan-shadows/{projection.run_id}"
                "/jobs/job-route-1/observe"
            ),
            headers=headers,
            json={
                "status": "complete",
                "jobUpdatedAt": "2026-07-25T11:01:05+08:00",
                "observedAt": "2026-07-25T11:01:06+08:00",
                "evidenceSummary": {
                    "artifactId": "job-result-route-1",
                    "contentFingerprint": "sha256-route-result",
                    "attemptId": "start-command-route-1",
                    "attemptIdentitySource": "start_command",
                    "verificationId": "job-verification-route-1",
                    "verificationStatus": "failed",
                    "verifier": "legacy_job.persisted_result.v1",
                    "verificationReason": "result_fingerprint_mismatch",
                    "result": "must-not-enter-runtime-shadow",
                },
            },
        )
        valid_completed_job = client.post(
            (
                f"/runtime/task-plan-shadows/{projection.run_id}"
                "/jobs/job-route-1/observe"
            ),
            headers=headers,
            json={
                "status": "complete",
                "jobUpdatedAt": "2026-07-25T11:01:07+08:00",
                "observedAt": "2026-07-25T11:01:08+08:00",
                "evidenceSummary": {
                    "artifactId": "job-result-route-2",
                    "contentFingerprint": "a" * 64,
                    "attemptId": "start-command-route-1",
                    "attemptIdentitySource": "start_command",
                    "verificationId": "job-verification-route-2",
                    "verificationArtifactId": "job-result-route-2",
                    "verificationExpectedFingerprint": "a" * 64,
                    "verificationObservedFingerprint": "a" * 64,
                    "verificationStatus": "verified",
                    "verifier": "legacy_job.persisted_result.v1",
                    "verificationReason": "persisted_result_matches",
                },
            },
        )
        conflicting = client.post(
            f"/runtime/task-plan-shadows/{projection.run_id}/observe",
            headers=headers,
            json={**payload, "status": "dismissed"},
        )
        detail = client.get(
            f"/runtime/task-plan-shadows/{projection.run_id}",
            headers=headers,
        )

    assert observed.status_code == 200
    assert replayed.status_code == 200
    assert bound.status_code == 200
    assert observed_job.status_code == 200
    assert replayed_job.status_code == 200
    assert completed_job.status_code == 200
    assert valid_completed_job.status_code == 200
    assert conflicting.status_code == 409
    assert observed.json()["observation"]["id"] == replayed.json()["observation"]["id"]
    assert observed.json()["run"]["state"] == "waiting_user"
    assert observed.json()["observation"]["handoff"] == "legacy_job_unmigrated"
    assert observed.json()["observation"]["runtime_execution_claimed"] is False
    assert bound.json()["binding"]["legacy_job_id"] == "job-route-1"
    assert bound.json()["binding"]["runtime_execution_claimed"] is False
    assert (
        observed_job.json()["observation"]["id"]
        == replayed_job.json()["observation"]["id"]
    )
    assert observed_job.json()["observation"]["runtime_state_changed"] is False
    assert (
        completed_job.json()["observation"]["verification_receipt_id"]
        == "job-verification-route-1"
    )
    assert (
        completed_job.json()["observation"]["evidence_summary"]
        ["verificationStatus"]
        == "failed"
    )
    assert (
        "result"
        not in completed_job.json()["observation"]["evidence_summary"]
    )
    assert len(detail.json()["observations"]) == 1
    assert len(detail.json()["jobBindings"]) == 1
    assert len(detail.json()["jobObservations"]) == 3
    assert (
        detail.json()["jobObservations"][-2]["evidence_summary"]
        ["verificationReason"]
        == "result_fingerprint_mismatch"
    )
    assert len(detail.json()["artifacts"]) == 1
    assert detail.json()["artifacts"][0]["uri_or_path"] == (
        "runtime://jobs/job-route-1/result"
    )
    assert detail.json()["run"]["state"] == "waiting_user"


def test_task_plan_dismissed_observation_cancels_only_the_shadow(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-route-dismissed",
        plan_event={
            "id": "plan-route-dismissed",
            "title": "忽略旧计划",
            "status": "proposed",
            "steps": [],
        },
        now="2026-07-25T11:00:00+08:00",
    )
    app = create_app(
        "test-token",
        runtime_context=create_runtime_context(db_path=db_path),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/runtime/task-plan-shadows/{projection.run_id}/observe",
            headers={"Authorization": "Bearer test-token"},
            json={
                "planId": "plan-route-dismissed",
                "traceId": "trace-route-dismissed",
                "status": "dismissed",
                "observedAt": "2026-07-25T11:01:00+08:00",
            },
        )

    assert response.status_code == 200
    assert response.json()["run"]["state"] == "cancelled"
    assert response.json()["run"]["stop_reason"] == "user_cancelled"
    assert response.json()["observation"]["handoff"] == "none"


def test_runtime_run_detail_reports_snapshot_mismatch(tmp_path: Path) -> None:
    app = _app_with_run(tmp_path)
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(app) as client:
        conn = sqlite3.connect(tmp_path / "archer.db")
        try:
            conn.execute(
                "UPDATE runtime_runs SET objective = 'tampered' "
                "WHERE id = 'run-api-1'"
            )
            conn.commit()
        finally:
            conn.close()
        response = client.get("/runtime/runs/run-api-1", headers=headers)
        listing = client.get("/runtime/runs", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "run_snapshot_mismatch"
    assert listing.status_code == 200
    assert listing.json()["runs"][0]["id"] == "run-api-1"
    assert listing.json()["recovery"]["items"][0]["classification"] == "invalid"


def test_runtime_run_detail_includes_latest_checkpoint(tmp_path: Path) -> None:
    app = _app_with_run(tmp_path)
    checkpoint = RunCheckpoint(
        id="checkpoint-api-1",
        run_id="run-api-1",
        resume_state=RunState.PLANNING,
        cursor={"planIndex": 1},
        created_at="2026-07-23T12:00:01+08:00",
    )
    record_checkpoint(
        tmp_path / "archer.db",
        checkpoint,
        expected_run_version=1,
        event_id="event-checkpoint-api-1",
    )

    with TestClient(app) as client:
        response = client.get(
            "/runtime/runs/run-api-1",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json()["latestCheckpoint"]["id"] == checkpoint.id
    assert response.json()["latestCheckpoint"]["resume_state"] == "planning"
    assert response.json()["latestCheckpoint"]["cursor"] == {"planIndex": 1}


def test_runtime_verification_retry_rechecks_existing_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, run_id, target = _app_with_uncertain_write(tmp_path, monkeypatch)
    _disable_startup_auto_recovery(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            f"/runtime/runs/{run_id}/retry-verification",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )

    assert response.status_code == 200
    assert response.json()["run"]["state"] == "completed"
    assert response.json()["verificationReceipt"]["status"] == "verified"
    assert target.read_text(encoding="utf-8") == "verified body"


def test_runtime_resume_dispatches_to_checkpoint_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skills import obsidian_write

    app, run_id, target = _app_with_uncertain_write(tmp_path, monkeypatch)
    _disable_startup_auto_recovery(monkeypatch)
    monkeypatch.setattr(
        obsidian_write,
        "run_structured",
        lambda payload: (_ for _ in ()).throw(AssertionError("must not rewrite")),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/runtime/runs/{run_id}/resume",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )

    assert response.status_code == 200
    assert response.json()["run"]["state"] == "completed"
    assert response.json()["verificationReceipt"]["status"] == "verified"
    assert response.json()["resumeAdapter"] == "obsidian_verification"
    assert response.json()["checkpointId"].startswith("checkpoint-")
    assert target.read_text(encoding="utf-8") == "verified body"


def test_runtime_resume_rejects_run_without_adapter(tmp_path: Path) -> None:
    app = _app_with_run(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/runtime/runs/run-api-1/resume",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "runtime_resume_unavailable"


def test_runtime_resume_rejects_unsupported_cursor_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, run_id, _target = _app_with_uncertain_write(tmp_path, monkeypatch)
    _disable_startup_auto_recovery(monkeypatch)
    run = get_run(tmp_path / "archer.db", run_id)
    checkpoint = latest_checkpoint(tmp_path / "archer.db", run_id)
    assert run is not None
    assert checkpoint is not None
    record_checkpoint(
        tmp_path / "archer.db",
        RunCheckpoint(
            id="checkpoint-api-unsupported",
            run_id=run.id,
            step_id=run.current_step_id,
            resume_state=RunState.VERIFYING,
            cursor=checkpoint.cursor,
            cursor_version=2,
            created_at="2026-07-23T12:00:03+08:00",
        ),
        expected_run_version=run.version,
        event_id="event-checkpoint-api-unsupported",
    )

    with TestClient(app) as client:
        response = client.post(
            f"/runtime/runs/{run_id}/resume",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["message"] == "cursor_version_unsupported"


def test_runtime_cancel_closes_waiting_obsidian_run(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding = stage_obsidian_write(
        db_path,
        objective="等待批准的写入",
        approval_fingerprint="approval-cancel",
        now="2026-07-23T12:00:00+08:00",
    )
    context = create_runtime_context(
        db_path=db_path,
        clock=lambda: datetime(2026, 7, 23, 12, 1, 0),
    )
    app = create_app("test-token", runtime_context=context)

    with TestClient(app) as client:
        response = client.post(
            f"/runtime/runs/{binding.run_id}/cancel",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )

    assert response.status_code == 200
    assert response.json()["cancellationRequested"] is True
    assert response.json()["run"]["state"] == "cancelled"


def test_runtime_cancel_rejects_run_without_adapter(tmp_path: Path) -> None:
    app = _app_with_run(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/runtime/runs/run-api-1/cancel",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "runtime_cancellation_unavailable"


def test_runtime_verification_retry_rejects_non_uncertain_run(tmp_path: Path) -> None:
    app = _app_with_run(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/runtime/runs/run-api-1/retry-verification",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "verification_retry_unavailable"
