from __future__ import annotations

import copy

import pytest

from core.job_execution_adapter import (
    LEGACY_JOB_V0_CAPABILITIES,
    legacy_job_attempt_identity,
)
from core.job_result_evidence import build_legacy_job_result_artifact
from core.job_terminal_finalize import (
    JobTerminalFinalizeStaleError,
    assess_legacy_child_rollup,
    legacy_job_result_is_verified,
)
from terminal.api import job_result_evidence, job_routes as jobs
from terminal.api.job_cancellation import (
    request_legacy_job_cancellation_response,
)
from terminal.api.job_result_evidence import complete_legacy_job_result
from terminal.api.job_terminal_finalize import finalize_legacy_job_failure


def _reset_jobs(path) -> None:
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    jobs.BACKGROUND_JOBS_PATH = path


def _running_job(job_id: str = "job-finalize-1") -> dict:
    return {
        "id": job_id,
        "title": "终态任务",
        "kind": "analysis",
        "prompt": "验证终态写入",
        "status": "running",
        "result": "",
        "createdAt": "2026-07-26T20:00:00+08:00",
        "updatedAt": "2026-07-26T21:00:00+08:00",
        "startCommandId": f"start-{job_id}",
    }


def _install_job(tmp_path, job: dict | None = None) -> dict:
    _reset_jobs(tmp_path / "background_jobs.json")
    installed = job or _running_job()
    jobs.BACKGROUND_JOBS[installed["id"]] = installed
    jobs.BACKGROUND_JOBS_LOADED = True
    with jobs.BACKGROUND_JOB_LOCK:
        jobs._persist_jobs_locked()
    return installed


def _verified_child(job_id: str = "child-verified") -> dict:
    child = {
        "id": job_id,
        "title": "[子] 已验证",
        "kind": "analysis",
        "prompt": "child",
        "status": "complete",
        "result": "真实子任务结果",
        "createdAt": "2026-07-26T20:00:00+08:00",
        "updatedAt": "2026-07-26T21:00:00+08:00",
        "startCommandId": f"start-{job_id}",
    }
    artifact = build_legacy_job_result_artifact(
        child,
        str(child["result"]),
        created_at=str(child["updatedAt"]),
    )
    child["resultArtifact"] = artifact
    child["resultVerification"] = {
        "id": f"verification-{job_id}",
        "artifactId": artifact["id"],
        "status": "verified",
    }
    return child


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("expected_attempt_id", "stale-attempt"),
        ("expected_updated_at", "stale-updated-at"),
    ],
)
def test_complete_rejects_stale_finalize_without_mutation(
    tmp_path,
    field: str,
    replacement: str,
) -> None:
    job = _install_job(tmp_path)
    attempt_id, _ = legacy_job_attempt_identity(job)
    kwargs = {
        "expected_attempt_id": attempt_id,
        "expected_updated_at": job["updatedAt"],
    }
    kwargs[field] = replacement
    before = copy.deepcopy(job)

    with pytest.raises(JobTerminalFinalizeStaleError):
        complete_legacy_job_result(
            job["id"],
            "迟到结果",
            source="test",
            **kwargs,
        )

    assert jobs.BACKGROUND_JOBS[job["id"]] == before


def test_complete_records_one_verified_terminal_receipt_and_reloads(
    tmp_path,
) -> None:
    job = _install_job(tmp_path)

    first = complete_legacy_job_result(
        job["id"],
        "已验证结果",
        source="worker_result",
    )
    second = complete_legacy_job_result(
        job["id"],
        "已验证结果",
        source="worker_result",
    )
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    loaded = jobs._job_detail(job["id"])

    assert first is not None
    assert second is not None
    assert first["status"] == "complete"
    assert len(second["terminalFinalizations"]) == 1
    assert loaded["terminalFinalizations"] == second["terminalFinalizations"]
    assert loaded["activeTerminalFinalizationId"] == (
        second["terminalFinalizations"][0]["id"]
    )


def test_state_change_between_artifact_and_verification_blocks_complete(
    tmp_path,
    monkeypatch,
) -> None:
    job = _install_job(tmp_path)
    verifier = job_result_evidence.verify_persisted_job_result

    def change_state_before_finalize(*args, **kwargs):
        receipt = verifier(*args, **kwargs)
        with jobs.BACKGROUND_JOB_LOCK:
            current = jobs.BACKGROUND_JOBS[job["id"]]
            current["status"] = "waiting_approval"
            current["updatedAt"] = "2026-07-26T21:02:00+08:00"
            jobs._persist_jobs_locked()
        return receipt

    monkeypatch.setattr(
        job_result_evidence,
        "verify_persisted_job_result",
        change_state_before_finalize,
    )

    with pytest.raises(JobTerminalFinalizeStaleError):
        complete_legacy_job_result(job["id"], "待验证结果")

    current = jobs.BACKGROUND_JOBS[job["id"]]
    assert current["status"] == "waiting_approval"
    assert "resultVerification" not in current
    assert "terminalFinalizations" not in current


def test_generic_job_update_cannot_write_terminal_state(tmp_path) -> None:
    job = _install_job(tmp_path)
    before = copy.deepcopy(job)

    with pytest.raises(ValueError, match="terminal finalize authority"):
        jobs._update_job(job["id"], status="complete", result="绕过结果")

    assert jobs.BACKGROUND_JOBS[job["id"]] == before


def test_failure_finalize_checks_attempt_and_records_receipt(tmp_path) -> None:
    job = _install_job(tmp_path)
    before = copy.deepcopy(job)

    with pytest.raises(JobTerminalFinalizeStaleError):
        finalize_legacy_job_failure(
            job["id"],
            error="late error",
            failure_keyword="late_error",
            source="test_failure",
            expected_attempt_id="stale-attempt",
        )
    assert jobs.BACKGROUND_JOBS[job["id"]] == before

    failed = finalize_legacy_job_failure(
        job["id"],
        error="worker failed",
        failure_keyword="worker_failed",
        source="test_failure",
    )

    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["terminalFinalizations"][0]["status"] == "failed"
    assert failed["terminalFinalizations"][0]["source"] == "test_failure"


def test_cancellation_wins_over_late_success_finalize(tmp_path) -> None:
    job = _install_job(tmp_path)
    attempt_id, _ = legacy_job_attempt_identity(job)
    status, _ = request_legacy_job_cancellation_response(
        job["id"],
        {
            "commandId": "cancel-before-finalize",
            "expectedStatus": "running",
            "expectedUpdatedAt": job["updatedAt"],
            "attemptId": attempt_id,
        },
    )

    completed = complete_legacy_job_result(
        job["id"],
        "不应成为成功的结果",
        source="late_worker",
    )
    current = jobs.BACKGROUND_JOBS[job["id"]]

    assert status == 200
    assert completed is None
    assert current["status"] == "failed"
    assert current["cancellationDisposition"] == "manual_uncertain"
    assert current["result"] == ""
    assert "resultArtifact" not in current


def test_child_rollup_requires_current_verified_attempt() -> None:
    verified = _verified_child()
    assert legacy_job_result_is_verified(verified) is True
    assert assess_legacy_child_rollup([verified]).ready is True

    stale = copy.deepcopy(verified)
    stale["attemptId"] = "new-attempt"
    assessment = assess_legacy_child_rollup([stale])

    assert legacy_job_result_is_verified(stale) is False
    assert assessment.ready is False
    assert assessment.reason == "child_result_unverified"


@pytest.mark.parametrize("worker_succeeds", [True, False])
def test_late_worker_cannot_finalize_a_new_attempt(
    tmp_path,
    monkeypatch,
    worker_succeeds: bool,
) -> None:
    job = _install_job(tmp_path)

    def execute(_prompt: str, job_id: str) -> dict:
        with jobs.BACKGROUND_JOB_LOCK:
            current = jobs.BACKGROUND_JOBS[job_id]
            current["attemptId"] = "replacement-attempt"
            current["attemptIdentitySource"] = "retry_command"
            current["updatedAt"] = "2026-07-26T21:01:00+08:00"
            jobs._persist_jobs_locked()
        if not worker_succeeds:
            raise RuntimeError("old attempt failed late")
        return {"role": "assistant", "text": "old attempt result"}

    monkeypatch.setattr(jobs, "_run_job_chat_with_tools", execute)
    jobs._run_job(job["id"])
    current = jobs.BACKGROUND_JOBS[job["id"]]

    assert current["attemptId"] == "replacement-attempt"
    assert current["status"] == "running"
    assert current["result"] == ""
    assert "resultArtifact" not in current
    assert "terminalFinalizations" not in current


def test_runtime_capability_remains_empty() -> None:
    assert LEGACY_JOB_V0_CAPABILITIES == frozenset()
