from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.job_execution_adapter import (
    LEGACY_JOB_V0_CAPABILITIES,
    JobCommandCollisionError,
    JobCommandStaleSnapshotError,
    claim_legacy_job_retry,
    legacy_job_attempt_identity,
)
from terminal.api import _routes as routes, job_routes as jobs
from terminal.api.job_result_evidence import complete_legacy_job_result
from terminal.api.job_retry import retry_legacy_job_response

UPDATED_AT = "2026-07-26T18:00:00+08:00"


def _terminal_job(
    job_id: str = "job-retry-1",
    *,
    status: str = "failed",
) -> dict:
    return {
        "id": job_id,
        "title": "重试任务",
        "kind": "analysis",
        "prompt": "再次执行",
        "status": status,
        "result": "",
        "error": "boom",
        "createdAt": "2026-07-26T17:00:00+08:00",
        "updatedAt": UPDATED_AT,
        "startCommandId": f"start-{job_id}",
    }


def _retry_envelope(
    job: dict,
    *,
    command_id: str = "retry-command-1",
) -> dict[str, str]:
    prior_attempt_id, _ = legacy_job_attempt_identity(job)
    return {
        "commandId": command_id,
        "expectedStatus": str(job["status"]),
        "expectedUpdatedAt": str(job["updatedAt"]),
        "priorAttemptId": prior_attempt_id,
    }


def _reset_jobs(path) -> None:
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    jobs.BACKGROUND_JOBS_PATH = path


def test_retry_claim_is_persistable_and_replay_is_idempotent() -> None:
    job = _terminal_job()
    store = {job["id"]: job}
    envelope = _retry_envelope(job)

    first = claim_legacy_job_retry(
        store,
        job["id"],
        claimed_at="2026-07-26T18:01:00+08:00",
        command_id=envelope["commandId"],
        expected_status=envelope["expectedStatus"],
        expected_updated_at=envelope["expectedUpdatedAt"],
        prior_attempt_id=envelope["priorAttemptId"],
    )
    replay = claim_legacy_job_retry(
        store,
        job["id"],
        claimed_at="2099-01-01T00:00:00+08:00",
        command_id=envelope["commandId"],
        expected_status=envelope["expectedStatus"],
        expected_updated_at=envelope["expectedUpdatedAt"],
        prior_attempt_id=envelope["priorAttemptId"],
    )

    assert first.claimed is True
    assert replay.replayed is True
    assert replay.attempt_id == first.attempt_id
    assert store[job["id"]]["status"] == "queued"
    assert len(store[job["id"]]["retryClaims"]) == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("status", "complete"),
        ("updatedAt", "2026-07-26T18:00:01+08:00"),
        ("startCommandId", "different-prior-attempt"),
    ],
)
def test_retry_claim_rejects_stale_snapshot_without_mutation(
    field: str,
    replacement: str,
) -> None:
    job = _terminal_job()
    envelope = _retry_envelope(job)
    job[field] = replacement
    before = copy.deepcopy(job)

    with pytest.raises(JobCommandStaleSnapshotError):
        claim_legacy_job_retry(
            {job["id"]: job},
            job["id"],
            claimed_at="2026-07-26T18:01:00+08:00",
            command_id=envelope["commandId"],
            expected_status=envelope["expectedStatus"],
            expected_updated_at=envelope["expectedUpdatedAt"],
            prior_attempt_id=envelope["priorAttemptId"],
        )

    assert job == before


def test_retry_command_collision_does_not_create_an_attempt() -> None:
    first = _terminal_job("job-retry-1")
    second = _terminal_job("job-retry-2")
    store = {first["id"]: first, second["id"]: second}
    first_envelope = _retry_envelope(first)
    claim_legacy_job_retry(
        store,
        first["id"],
        claimed_at="2026-07-26T18:01:00+08:00",
        command_id=first_envelope["commandId"],
        expected_status=first_envelope["expectedStatus"],
        expected_updated_at=first_envelope["expectedUpdatedAt"],
        prior_attempt_id=first_envelope["priorAttemptId"],
    )
    second_before = copy.deepcopy(second)
    second_envelope = _retry_envelope(second)

    with pytest.raises(JobCommandCollisionError):
        claim_legacy_job_retry(
            store,
            second["id"],
            claimed_at="2026-07-26T18:02:00+08:00",
            command_id=second_envelope["commandId"],
            expected_status=second_envelope["expectedStatus"],
            expected_updated_at=second_envelope["expectedUpdatedAt"],
            prior_attempt_id=second_envelope["priorAttemptId"],
        )

    assert second == second_before


def test_concurrent_retry_replay_starts_only_one_worker(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _terminal_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    envelope = _retry_envelope(job)
    starts: list[str] = []
    monkeypatch.setattr(jobs, "_start_job", lambda job_id: starts.append(job_id))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _: retry_legacy_job_response(job["id"], envelope),
            range(2),
        ))

    assert [status for status, _ in results] == [200, 200]
    assert sorted(body["claimed"] for _, body in results) == [False, True]
    assert len(starts) == 1


def test_retry_claim_and_attempt_survive_store_reload(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _terminal_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    with jobs.BACKGROUND_JOB_LOCK:
        jobs._persist_jobs_locked()
    monkeypatch.setattr(jobs, "_start_job", lambda _job_id: None)

    status, response = retry_legacy_job_response(
        job["id"], _retry_envelope(job)
    )
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    loaded = jobs._job_detail(job["id"])

    assert status == 200
    assert loaded["attemptId"] == response["attemptId"]
    assert loaded["retryClaims"][0]["commandId"] == "retry-command-1"


def test_retry_archives_old_evidence_without_result_body(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _terminal_job(status="complete")
    job["result"] = "第一轮结果正文"
    job["resultArtifact"] = {
        "id": "artifact-before-retry",
        "attemptId": "attempt-before-retry",
        "attemptIdentitySource": "start_command",
        "contentFingerprint": "old-fingerprint",
    }
    job["resultVerification"] = {
        "id": "verification-before-retry",
        "artifactId": "artifact-before-retry",
        "status": "verified",
    }
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    monkeypatch.setattr(jobs, "_start_job", lambda _job_id: None)

    status, response = retry_legacy_job_response(
        job["id"], _retry_envelope(job)
    )
    completed = complete_legacy_job_result(job["id"], "第二轮结果")

    assert status == 200
    assert completed["resultArtifact"]["attemptId"] == response["attemptId"]
    assert completed["resultArtifact"]["id"] != "artifact-before-retry"
    history = completed["resultEvidenceHistory"]
    assert history[0]["artifact"]["id"] == "artifact-before-retry"
    assert history[0]["verification"]["status"] == "verified"
    assert "第一轮结果正文" not in json.dumps(history, ensure_ascii=False)


def test_retry_api_maps_contract_stale_collision_and_not_found(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _terminal_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    monkeypatch.setattr(jobs, "_start_job", lambda _job_id: None)

    invalid_status, invalid = retry_legacy_job_response(
        job["id"], {"commandId": "partial"}
    )
    stale_status, stale = retry_legacy_job_response(
        job["id"],
        {
            **_retry_envelope(job, command_id="retry-stale"),
            "expectedUpdatedAt": "stale",
        },
    )
    ok_status, _ = routes.payload_post(
        f"/jobs/{job['id']}/retry",
        _retry_envelope(job),
    )
    collision_status, collision = retry_legacy_job_response(
        job["id"],
        {
            **_retry_envelope(_terminal_job(), command_id="retry-command-1"),
            "expectedUpdatedAt": "different",
        },
    )
    missing_status, missing = retry_legacy_job_response("missing", {})

    assert (invalid_status, invalid["error"]) == (
        400, "invalid_job_retry_command"
    )
    assert (stale_status, stale["error"]) == (409, "job_snapshot_stale")
    assert ok_status == 200
    assert (collision_status, collision["error"]) == (
        409, "job_command_collision"
    )
    assert (missing_status, missing["reason"]) == (404, "job_not_found")


def test_legacy_empty_retry_payload_remains_compatible(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _terminal_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    starts: list[str] = []
    monkeypatch.setattr(jobs, "_start_job", lambda job_id: starts.append(job_id))

    status, response = retry_legacy_job_response(job["id"], {})

    assert status == 200
    assert response["claimed"] is True
    assert response["attemptId"].startswith("job-attempt-")
    assert starts == [job["id"]]
    assert LEGACY_JOB_V0_CAPABILITIES == frozenset()
