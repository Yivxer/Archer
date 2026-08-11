from __future__ import annotations

import json

import pytest

from core.job_result_evidence import (
    JobResultArtifactCollisionError,
    verify_persisted_job_result,
)
from terminal.api import job_routes as jobs
from terminal.api.job_result_evidence import complete_legacy_job_result


def _reset_jobs(path) -> None:
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    jobs.BACKGROUND_JOBS_PATH = path


def _running_job(tmp_path) -> dict:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = jobs._create_job({
        "title": "结果证据",
        "prompt": "验证持久化结果",
        "autoStart": False,
    })["job"]
    with jobs.BACKGROUND_JOB_LOCK:
        jobs.BACKGROUND_JOBS[job["id"]]["status"] = "running"
        jobs._persist_jobs_locked()
    return job


def test_success_result_is_persisted_and_verified_from_disk(tmp_path) -> None:
    job = _running_job(tmp_path)

    completed = complete_legacy_job_result(job["id"], "真实持久化结果")

    assert completed["status"] == "complete"
    artifact = completed["resultArtifact"]
    receipt = completed["resultVerification"]
    assert artifact["jobId"] == job["id"]
    assert artifact["immutable"] is True
    assert artifact["contentLength"] == len("真实持久化结果")
    assert receipt["artifactId"] == artifact["id"]
    assert receipt["status"] == "verified"
    persisted = json.loads(jobs.BACKGROUND_JOBS_PATH.read_text(encoding="utf-8"))
    assert persisted["jobs"][0]["resultVerification"] == receipt


def test_verifier_detects_persisted_result_tampering(tmp_path) -> None:
    job = _running_job(tmp_path)
    completed = complete_legacy_job_result(job["id"], "原始结果")
    artifact = completed["resultArtifact"]
    payload = json.loads(jobs.BACKGROUND_JOBS_PATH.read_text(encoding="utf-8"))
    payload["jobs"][0]["result"] = "被修改的结果"
    jobs.BACKGROUND_JOBS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    receipt = verify_persisted_job_result(
        jobs.BACKGROUND_JOBS_PATH,
        job["id"],
        artifact["id"],
        verified_at="2026-07-26T12:00:00",
    )

    assert receipt["status"] == "failed"
    assert receipt["reason"] == "result_fingerprint_mismatch"


def test_empty_result_fails_verification_and_job_completion(tmp_path) -> None:
    job = _running_job(tmp_path)

    completed = complete_legacy_job_result(job["id"], "")

    assert completed["status"] == "failed"
    assert completed["resultVerification"]["status"] == "failed"
    assert completed["resultVerification"]["reason"] == "result_empty"
    assert completed["failureKeyword"] == "job_result_verification_failed"


def test_unreadable_persisted_store_is_uncertain(tmp_path) -> None:
    missing_path = tmp_path / "missing.json"

    receipt = verify_persisted_job_result(
        missing_path,
        "job-missing",
        "artifact-missing",
        verified_at="2026-07-26T12:00:00",
    )

    assert receipt["status"] == "uncertain"
    assert receipt["reason"] == "persisted_job_unreadable"


def test_repeated_verification_reuses_stable_receipt(tmp_path) -> None:
    job = _running_job(tmp_path)
    completed = complete_legacy_job_result(job["id"], "幂等结果")
    artifact = completed["resultArtifact"]
    first = completed["resultVerification"]

    second = verify_persisted_job_result(
        jobs.BACKGROUND_JOBS_PATH,
        job["id"],
        artifact["id"],
        verified_at="2099-01-01T00:00:00",
    )

    assert second == first


def test_result_artifact_cannot_be_overwritten(tmp_path) -> None:
    job = _running_job(tmp_path)
    completed = complete_legacy_job_result(job["id"], "第一份结果")

    with pytest.raises(JobResultArtifactCollisionError):
        complete_legacy_job_result(job["id"], "另一份结果")

    persisted = json.loads(jobs.BACKGROUND_JOBS_PATH.read_text(encoding="utf-8"))
    assert persisted["jobs"][0]["result"] == "第一份结果"
    assert persisted["jobs"][0]["resultArtifact"] == completed["resultArtifact"]


def test_result_evidence_survives_job_store_reload(tmp_path) -> None:
    job = _running_job(tmp_path)
    completed = complete_legacy_job_result(job["id"], "重载结果")

    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    loaded = jobs._job_detail(job["id"])

    assert loaded["resultArtifact"] == completed["resultArtifact"]
    assert loaded["resultVerification"] == completed["resultVerification"]
