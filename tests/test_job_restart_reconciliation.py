from __future__ import annotations

import json

import pytest

from core.job_execution_adapter import _start_command_fingerprint
from terminal.api import job_routes as jobs


def _reset_jobs(path) -> None:
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    jobs.BACKGROUND_JOBS_PATH = path


def _write_job(path, **overrides: object) -> dict:
    job = {
        "id": "job-restart",
        "title": "重启协调",
        "kind": "analysis",
        "prompt": "验证 restart reconciliation",
        "status": "running",
        "result": "",
        "createdAt": "2026-07-26T10:00:00",
        "updatedAt": "2026-07-26T10:01:00",
        "timeoutSeconds": 300,
    }
    job.update(overrides)
    path.write_text(
        json.dumps({"jobs": [job]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return job


def _complete_claim(job: dict) -> dict:
    command_id = "start-command-restart"
    expected_status = "queued"
    expected_updated_at = "2026-07-26T10:00:30"
    return {
        "startCommandId": command_id,
        "startCommandFingerprint": _start_command_fingerprint(
            job["id"],
            expected_status,
            expected_updated_at,
        ),
        "startExpectedStatus": expected_status,
        "startExpectedUpdatedAt": expected_updated_at,
        "startClaimedAt": job["updatedAt"],
    }


def test_claimed_running_job_records_fail_closed_reconciliation(tmp_path) -> None:
    path = tmp_path / "background_jobs.json"
    raw = _write_job(path)
    raw.update(_complete_claim(raw))
    _write_job(path, **raw)
    _reset_jobs(path)

    loaded = jobs._job_detail(raw["id"])

    assert loaded["status"] == "failed"
    assert loaded["failureKeyword"] == "job_restart_interrupted"
    assert loaded["startCommandId"] == "start-command-restart"
    receipt = loaded["restartReconciliation"]
    assert receipt["previousStatus"] == "running"
    assert receipt["previousUpdatedAt"] == raw["updatedAt"]
    assert receipt["disposition"] == "failed_closed"
    assert receipt["claimIntegrity"] == "valid"
    assert receipt["startCommandId"] == "start-command-restart"


def test_restart_reconciliation_is_idempotent_across_reloads(tmp_path) -> None:
    path = tmp_path / "background_jobs.json"
    raw = _write_job(path)
    raw.update(_complete_claim(raw))
    _write_job(path, **raw)
    _reset_jobs(path)
    first = jobs._job_detail(raw["id"])["restartReconciliation"]
    first_updated_at = jobs.BACKGROUND_JOBS[raw["id"]]["updatedAt"]

    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    second_job = jobs._job_detail(raw["id"])

    assert second_job["restartReconciliation"] == first
    assert second_job["updatedAt"] == first_updated_at


@pytest.mark.parametrize("status", ["running", "waiting_approval"])
def test_unclaimed_legacy_job_keeps_fail_closed_compatibility(
    tmp_path,
    status,
) -> None:
    path = tmp_path / f"{status}.json"
    raw = _write_job(path, status=status)
    _reset_jobs(path)

    loaded = jobs._job_detail(raw["id"])

    assert loaded["status"] == "failed"
    assert loaded["error"] == "job interrupted by API restart"
    receipt = loaded["restartReconciliation"]
    assert receipt["claimIntegrity"] == "legacy_unclaimed"
    assert receipt["startCommandId"] is None
    expected = "manual" if status == "waiting_approval" else "failed_closed"
    assert receipt["disposition"] == expected


@pytest.mark.parametrize(
    "claim_fields",
    [
        {"startCommandId": "partial-command"},
        {
            "startCommandId": "corrupt-command",
            "startCommandFingerprint": "not-the-real-fingerprint",
            "startExpectedStatus": "queued",
            "startExpectedUpdatedAt": "2026-07-26T10:00:30",
            "startClaimedAt": "2026-07-26T10:01:00",
        },
    ],
)
def test_incomplete_or_corrupt_start_claim_degrades_to_manual(
    tmp_path,
    claim_fields,
) -> None:
    path = tmp_path / "corrupt.json"
    raw = _write_job(path, **claim_fields)
    _reset_jobs(path)

    loaded = jobs._job_detail(raw["id"])

    assert loaded["status"] == "failed"
    receipt = loaded["restartReconciliation"]
    assert receipt["claimIntegrity"] == "invalid"
    assert receipt["disposition"] == "manual"
    assert receipt["reason"] == "claim_invalid"
