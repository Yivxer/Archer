from __future__ import annotations

import copy
import json

from core.job_execution_adapter import (
    LEGACY_JOB_V0_CAPABILITIES,
    claim_legacy_job_retry,
    legacy_job_attempt_identity,
)
from core.job_outcome_verification import verify_legacy_job_outcome
from core.job_result_evidence import build_legacy_job_result_artifact
from terminal.api import (
    job_outcome_verification,
    job_routes as jobs,
)
from terminal.api.job_result_evidence import complete_legacy_job_result


def _evidenced_job(
    *,
    job_id: str = "job-outcome-1",
    kind: str = "analysis",
    result: str = "普通结果",
) -> dict:
    job = {
        "id": job_id,
        "title": "Outcome 验证",
        "kind": kind,
        "prompt": "验证业务结果",
        "status": "complete",
        "result": result,
        "createdAt": "2026-07-26T20:00:00+08:00",
        "updatedAt": "2026-07-26T21:00:00+08:00",
        "startCommandId": f"start-{job_id}",
    }
    artifact = build_legacy_job_result_artifact(
        job,
        result,
        created_at=str(job["updatedAt"]),
    )
    job["resultArtifact"] = artifact
    job["resultVerification"] = {
        "id": f"result-verification-{job_id}",
        "artifactId": artifact["id"],
        "status": "verified",
    }
    return job


def _reflection_record(
    *,
    note_path: str = "阅读/测试.md",
    pending_ids: list[int] | None = None,
) -> dict:
    return {
        "id": 7,
        "note_path": note_path,
        "note_title": "测试",
        "reflected_at": "2026-07-26T20:30:00+08:00",
        "pending_ids": pending_ids or [11, 12],
        "soul_proposal_id": None,
        "confidence": 0.8,
        "summary": "独立落盘记录",
    }


def _facts(*records: dict) -> dict[str, object]:
    return {
        "resolverStatus": "available",
        "reflectionRecords": list(records),
    }


def _reset_jobs(path) -> None:
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    jobs.BACKGROUND_JOBS_PATH = path


def test_generic_job_defaults_to_uncertain_without_string_heuristics() -> None:
    job = _evidenced_job(result="任务已经完美完成")

    first = verify_legacy_job_outcome(
        job,
        {"resolverStatus": "not_required"},
        verified_at="2026-07-26T21:01:00+08:00",
    )
    replay = verify_legacy_job_outcome(
        job,
        {"resolverStatus": "not_required"},
        verified_at="2099-01-01T00:00:00+08:00",
    )

    assert first["status"] == "uncertain"
    assert first["reason"] == "no_deterministic_verifier_for_kind"
    assert replay["id"] == first["id"]
    assert "任务已经完美完成" not in json.dumps(first, ensure_ascii=False)


def test_unverified_persisted_result_cannot_pass_outcome() -> None:
    job = _evidenced_job()
    job["resultVerification"]["status"] = "failed"

    receipt = verify_legacy_job_outcome(
        job,
        {},
        verified_at="2026-07-26T21:01:00+08:00",
    )

    assert receipt["status"] == "failed"
    assert receipt["reason"] == "persisted_result_not_verified"


def test_single_vault_reflection_matches_independent_record() -> None:
    result = json.dumps({
        "ok": True,
        "note_path": "阅读/测试.md",
        "pending_ids": [11, 12],
        "soul_proposal_id": None,
    })
    job = _evidenced_job(kind="vault_reflection", result=result)
    job["vaultArgs"] = {"note_path": "阅读/测试.md"}

    receipt = verify_legacy_job_outcome(
        job,
        _facts(_reflection_record()),
        verified_at="2026-07-26T21:01:00+08:00",
    )

    assert receipt["status"] == "verified"
    assert receipt["reason"] == "reflection_record_matches"
    assert receipt["verifier"].endswith("vault_reflection.record.v1")


def test_single_vault_reflection_matches_absolute_request_to_vault_relative_result() -> None:
    result = json.dumps({
        "ok": True,
        "note_path": "月度复盘/月度复盘写作方法.md",
        "pending_ids": [11, 12],
        "soul_proposal_id": None,
    })
    job = _evidenced_job(kind="vault_reflection", result=result)
    job["vaultArgs"] = {
        "note_path": "/Users/example/Vault/月度复盘/月度复盘写作方法.md"
    }

    receipt = verify_legacy_job_outcome(
        job,
        _facts(_reflection_record(
            note_path="月度复盘/月度复盘写作方法.md",
        )),
        verified_at="2026-07-26T21:01:00+08:00",
    )

    assert receipt["status"] == "verified"
    assert receipt["reason"] == "reflection_record_matches"


def test_single_vault_reflection_rejects_different_vault_relative_result() -> None:
    result = json.dumps({
        "ok": True,
        "note_path": "月度复盘/另一篇.md",
        "pending_ids": [11, 12],
    })
    job = _evidenced_job(kind="vault_reflection", result=result)
    job["vaultArgs"] = {
        "note_path": "/Users/example/Vault/月度复盘/原文.md"
    }

    receipt = verify_legacy_job_outcome(
        job,
        _facts(_reflection_record(note_path="月度复盘/另一篇.md")),
        verified_at="2026-07-26T21:01:00+08:00",
    )

    assert receipt["status"] == "failed"
    assert receipt["reason"] == "reflection_note_path_mismatch"


def test_vault_reflection_missing_record_fails_closed() -> None:
    result = json.dumps({
        "ok": True,
        "note_path": "阅读/测试.md",
        "pending_ids": [11, 12],
    })
    job = _evidenced_job(kind="vault_reflection", result=result)
    job["vaultArgs"] = {"note_path": "阅读/测试.md"}

    missing = verify_legacy_job_outcome(
        job,
        _facts(),
        verified_at="2026-07-26T21:01:00+08:00",
    )
    unavailable = verify_legacy_job_outcome(
        job,
        {"resolverStatus": "unavailable"},
        verified_at="2026-07-26T21:01:00+08:00",
    )

    assert (missing["status"], missing["reason"]) == (
        "failed",
        "reflection_record_missing",
    )
    assert (unavailable["status"], unavailable["reason"]) == (
        "uncertain",
        "reflection_evidence_unavailable",
    )


def test_vault_reflection_batch_requires_every_record() -> None:
    result = json.dumps({
        "ok": True,
        "reflected": [
            {
                "note_path": "阅读/一.md",
                "pending_ids": [1],
                "soul_proposal_id": None,
            },
            {
                "note_path": "阅读/二.md",
                "pending_ids": [2],
                "soul_proposal_id": None,
            },
        ],
        "skipped": [],
        "total": 2,
        "batch_total": 2,
    })
    job = _evidenced_job(kind="vault_reflection", result=result)

    verified = verify_legacy_job_outcome(
        job,
        _facts(
            _reflection_record(note_path="阅读/一.md", pending_ids=[1]),
            _reflection_record(note_path="阅读/二.md", pending_ids=[2]),
        ),
        verified_at="2026-07-26T21:01:00+08:00",
    )
    failed = verify_legacy_job_outcome(
        job,
        _facts(_reflection_record(note_path="阅读/一.md", pending_ids=[1])),
        verified_at="2026-07-26T21:01:00+08:00",
    )

    assert verified["status"] == "verified"
    assert failed["status"] == "failed"
    assert failed["reason"] == "reflection_record_missing"


def test_empty_reflection_batch_is_uncertain() -> None:
    job = _evidenced_job(
        kind="vault_reflection",
        result=json.dumps({
            "ok": True,
            "reflected": [],
            "skipped": [],
            "total": 0,
            "batch_total": 0,
        }),
    )

    receipt = verify_legacy_job_outcome(
        job,
        _facts(),
        verified_at="2026-07-26T21:01:00+08:00",
    )

    assert receipt["status"] == "uncertain"
    assert receipt["reason"] == "no_reflection_records_to_verify"


def test_complete_result_persists_uncertain_outcome_and_reloads(
    tmp_path,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _evidenced_job()
    job.pop("resultArtifact")
    job.pop("resultVerification")
    job["status"] = "running"
    job["result"] = ""
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    with jobs.BACKGROUND_JOB_LOCK:
        jobs._persist_jobs_locked()

    completed = complete_legacy_job_result(job["id"], "普通结果")
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    loaded = jobs._job_detail(job["id"])

    assert completed["status"] == "complete"
    assert completed["resultVerification"]["status"] == "verified"
    assert completed["outcomeVerification"]["status"] == "uncertain"
    assert loaded["outcomeVerification"] == completed["outcomeVerification"]


def test_vault_outcome_receipt_is_persisted_from_resolved_facts(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    result = json.dumps({
        "ok": True,
        "note_path": "阅读/测试.md",
        "pending_ids": [11, 12],
        "soul_proposal_id": None,
    })
    job = _evidenced_job(kind="vault_reflection", result=result)
    job.pop("resultArtifact")
    job.pop("resultVerification")
    job["status"] = "running"
    job["result"] = ""
    job["vaultArgs"] = {"note_path": "阅读/测试.md"}
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    with jobs.BACKGROUND_JOB_LOCK:
        jobs._persist_jobs_locked()
    monkeypatch.setattr(
        job_outcome_verification,
        "_observed_outcome_facts",
        lambda _job: _facts(_reflection_record()),
    )

    completed = complete_legacy_job_result(job["id"], result)

    assert completed["outcomeVerification"]["status"] == "verified"
    assert completed["outcomeVerification"]["artifactId"] == (
        completed["resultArtifact"]["id"]
    )


def test_outcome_receipt_binding_drift_is_zero_mutation(tmp_path) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _evidenced_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    binding = job_outcome_verification._outcome_binding(job)
    receipt = verify_legacy_job_outcome(
        job,
        {},
        verified_at="2026-07-26T21:01:00+08:00",
    )
    job["attemptId"] = "replacement-attempt"
    job.pop("resultArtifact")
    job.pop("resultVerification")
    before = copy.deepcopy(job)

    persisted = job_outcome_verification._persist_outcome_receipt(
        job["id"],
        binding,
        receipt,
    )

    assert persisted is None
    assert job == before


def test_new_outcome_evidence_archives_prior_receipt(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    result = json.dumps({
        "ok": True,
        "note_path": "阅读/测试.md",
        "pending_ids": [11, 12],
        "soul_proposal_id": None,
    })
    job = _evidenced_job(kind="vault_reflection", result=result)
    job["vaultArgs"] = {"note_path": "阅读/测试.md"}
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    facts = iter((
        {"resolverStatus": "unavailable"},
        _facts(_reflection_record()),
    ))
    monkeypatch.setattr(
        job_outcome_verification,
        "_observed_outcome_facts",
        lambda _job: next(facts),
    )

    first = job_outcome_verification.verify_and_persist_legacy_job_outcome(
        job["id"]
    )
    first_updated_at = jobs.BACKGROUND_JOBS[job["id"]]["updatedAt"]
    second = job_outcome_verification.verify_and_persist_legacy_job_outcome(
        job["id"]
    )

    assert first["status"] == "uncertain"
    assert second["status"] == "verified"
    assert jobs.BACKGROUND_JOBS[job["id"]]["updatedAt"] != first_updated_at
    assert jobs.BACKGROUND_JOBS[job["id"]][
        "outcomeVerificationHistory"
    ] == [first]


def test_retry_archives_outcome_receipt_without_result_body() -> None:
    job = _evidenced_job()
    job["outcomeVerification"] = verify_legacy_job_outcome(
        job,
        {},
        verified_at="2026-07-26T21:01:00+08:00",
    )
    prior_attempt, _ = legacy_job_attempt_identity(job)

    claim_legacy_job_retry(
        {job["id"]: job},
        job["id"],
        claimed_at="2026-07-26T21:02:00+08:00",
        command_id="retry-outcome",
        expected_status="complete",
        expected_updated_at=job["updatedAt"],
        prior_attempt_id=prior_attempt,
    )

    archived = job["resultEvidenceHistory"][0]
    assert archived["outcomeVerification"]["id"].startswith("job-outcome-")
    assert "result" not in archived
    assert "outcomeVerification" not in job
    assert LEGACY_JOB_V0_CAPABILITIES == frozenset()
