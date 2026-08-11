from __future__ import annotations

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.job_cancellation import (
    acknowledge_legacy_job_cancellation,
    claim_legacy_job_cancellation,
)
from core.job_execution_adapter import (
    LEGACY_JOB_V0_CAPABILITIES,
    JobCommandCollisionError,
    JobCommandStaleSnapshotError,
    legacy_job_attempt_identity,
)
from terminal.api import _routes as routes, job_routes as jobs
from terminal.api.job_cancellation import (
    request_legacy_job_cancellation_response,
)
from terminal.api.job_result_evidence import complete_legacy_job_result

UPDATED_AT = "2026-07-26T19:00:00+08:00"


def _active_job(
    job_id: str = "job-cancel-1",
    *,
    status: str = "running",
) -> dict:
    return {
        "id": job_id,
        "title": "取消任务",
        "kind": "analysis",
        "prompt": "执行后取消",
        "status": status,
        "result": "",
        "createdAt": "2026-07-26T18:00:00+08:00",
        "updatedAt": UPDATED_AT,
        "startCommandId": f"start-{job_id}",
    }


def _cancel_envelope(
    job: dict,
    *,
    command_id: str = "cancel-command-1",
) -> dict[str, str]:
    attempt_id, _ = legacy_job_attempt_identity(job)
    return {
        "commandId": command_id,
        "expectedStatus": str(job["status"]),
        "expectedUpdatedAt": str(job["updatedAt"]),
        "attemptId": attempt_id,
    }


def _reset_jobs(path) -> None:
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    jobs.BACKGROUND_JOBS_PATH = path


def test_queued_cancel_claim_is_terminal_and_replay_is_idempotent() -> None:
    job = _active_job(status="queued")
    store = {job["id"]: job}
    envelope = _cancel_envelope(job)

    first = claim_legacy_job_cancellation(
        store,
        job["id"],
        requested_at="2026-07-26T19:01:00+08:00",
        command_id=envelope["commandId"],
        expected_status=envelope["expectedStatus"],
        expected_updated_at=envelope["expectedUpdatedAt"],
        attempt_id=envelope["attemptId"],
    )
    replay = claim_legacy_job_cancellation(
        store,
        job["id"],
        requested_at="2099-01-01T00:00:00+08:00",
        command_id=envelope["commandId"],
        expected_status=envelope["expectedStatus"],
        expected_updated_at=envelope["expectedUpdatedAt"],
        attempt_id=envelope["attemptId"],
    )

    assert first.accepted is True
    assert first.disposition == "cancelled_before_start"
    assert replay.replayed is True
    assert replay.request_id == first.request_id
    assert job["status"] == "cancelled"
    assert len(job["cancellationRequests"]) == 1


def test_running_cancel_stays_pending_until_worker_acknowledges() -> None:
    job = _active_job()
    envelope = _cancel_envelope(job)
    claim = claim_legacy_job_cancellation(
        {job["id"]: job},
        job["id"],
        requested_at="2026-07-26T19:01:00+08:00",
        command_id=envelope["commandId"],
        expected_status=envelope["expectedStatus"],
        expected_updated_at=envelope["expectedUpdatedAt"],
        attempt_id=envelope["attemptId"],
    )

    acknowledged = acknowledge_legacy_job_cancellation(
        job,
        acknowledged_at="2026-07-26T19:01:01+08:00",
        stage="before_model",
        side_effect_started=False,
    )

    assert claim.disposition == "cooperative_pending"
    assert claim.job["status"] == "running"
    assert acknowledged is True
    assert job["status"] == "cancelled"
    assert job["cancellationDisposition"] == "cancelled_cooperatively"


def test_post_side_effect_cancellation_is_manual_uncertain() -> None:
    job = _active_job()
    envelope = _cancel_envelope(job)
    claim_legacy_job_cancellation(
        {job["id"]: job},
        job["id"],
        requested_at="2026-07-26T19:01:00+08:00",
        command_id=envelope["commandId"],
        expected_status=envelope["expectedStatus"],
        expected_updated_at=envelope["expectedUpdatedAt"],
        attempt_id=envelope["attemptId"],
    )

    acknowledge_legacy_job_cancellation(
        job,
        acknowledged_at="2026-07-26T19:01:01+08:00",
        stage="after_tool",
        side_effect_started=True,
    )

    assert job["status"] == "failed"
    assert job["cancellationDisposition"] == "manual_uncertain"
    assert job["failureKeyword"] == "job_cancellation_uncertain"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("status", "queued"),
        ("updatedAt", "2026-07-26T19:00:01+08:00"),
        ("startCommandId", "different-attempt"),
    ],
)
def test_cancel_rejects_stale_snapshot_without_mutation(
    field: str,
    replacement: str,
) -> None:
    job = _active_job()
    envelope = _cancel_envelope(job)
    job[field] = replacement
    before = copy.deepcopy(job)

    with pytest.raises(JobCommandStaleSnapshotError):
        claim_legacy_job_cancellation(
            {job["id"]: job},
            job["id"],
            requested_at="2026-07-26T19:01:00+08:00",
            command_id=envelope["commandId"],
            expected_status=envelope["expectedStatus"],
            expected_updated_at=envelope["expectedUpdatedAt"],
            attempt_id=envelope["attemptId"],
        )

    assert job == before


def test_cancel_command_collision_does_not_touch_second_job() -> None:
    first = _active_job("job-cancel-1")
    second = _active_job("job-cancel-2")
    store = {first["id"]: first, second["id"]: second}
    first_envelope = _cancel_envelope(first)
    claim_legacy_job_cancellation(
        store,
        first["id"],
        requested_at="2026-07-26T19:01:00+08:00",
        command_id=first_envelope["commandId"],
        expected_status=first_envelope["expectedStatus"],
        expected_updated_at=first_envelope["expectedUpdatedAt"],
        attempt_id=first_envelope["attemptId"],
    )
    second_before = copy.deepcopy(second)
    second_envelope = _cancel_envelope(second)

    with pytest.raises(JobCommandCollisionError):
        claim_legacy_job_cancellation(
            store,
            second["id"],
            requested_at="2026-07-26T19:02:00+08:00",
            command_id=second_envelope["commandId"],
            expected_status=second_envelope["expectedStatus"],
            expected_updated_at=second_envelope["expectedUpdatedAt"],
            attempt_id=second_envelope["attemptId"],
        )

    assert second == second_before


def test_concurrent_cancel_requests_append_one_receipt(tmp_path) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _active_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    envelope = _cancel_envelope(job)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _: request_legacy_job_cancellation_response(
                job["id"], envelope
            ),
            range(2),
        ))

    assert [status for status, _ in results] == [200, 200]
    assert sorted(body["replayed"] for _, body in results) == [False, True]
    assert len(jobs.BACKGROUND_JOBS[job["id"]]["cancellationRequests"]) == 1


def test_cancellation_receipt_survives_reload(tmp_path) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _active_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True

    status, response = request_legacy_job_cancellation_response(
        job["id"], _cancel_envelope(job)
    )
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    loaded = jobs._job_detail(job["id"])

    assert status == 200
    assert loaded["activeCancellationRequestId"] == response["requestId"]
    assert loaded["cancellationRequests"][0]["commandId"] == "cancel-command-1"


def test_restart_reconciliation_marks_pending_cancel_manual_uncertain(
    tmp_path,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _active_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    request_legacy_job_cancellation_response(
        job["id"], _cancel_envelope(job)
    )
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False

    loaded = jobs._job_detail(job["id"])

    assert loaded["status"] == "failed"
    assert loaded["cancellationDisposition"] == "manual_uncertain"
    assert loaded["failureKeyword"] == "job_cancellation_uncertain"
    assert (
        loaded["cancellationAcknowledgements"][0]["stage"]
        == "restart_reconciliation"
    )


def test_worker_acknowledges_running_cancel_without_result_overwrite(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    started = threading.Event()
    release = threading.Event()

    def fake_chat(_prompt: str, _job_id: str) -> dict:
        started.set()
        release.wait(timeout=1)
        return {"role": "assistant", "text": "不得写入"}

    monkeypatch.setattr(jobs, "_run_job_chat_with_tools", fake_chat)
    _, created = routes.payload_post("/jobs", {
        "title": "cooperative cancel",
        "prompt": "等待取消",
    })
    job_id = created["job"]["id"]
    assert started.wait(timeout=1)
    _, detail = routes.payload_get(f"/jobs/{job_id}")
    envelope = _cancel_envelope(detail["job"])

    cancel_status, cancel = routes.payload_post(
        f"/jobs/{job_id}/cancel", envelope
    )
    release.set()
    for _ in range(40):
        _, detail = routes.payload_get(f"/jobs/{job_id}")
        if detail["job"].get("cancellationDisposition"):
            break
        time.sleep(0.01)

    assert cancel_status == 200
    assert cancel["job"]["status"] == "running"
    assert detail["job"]["status"] == "failed"
    assert detail["job"]["cancellationDisposition"] == "manual_uncertain"
    assert detail["job"]["result"] == ""


def test_waiting_approval_cancel_blocks_tool_execution(tmp_path) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _active_job(status="waiting_approval")
    job["pendingTool"] = {
        "eventId": "tool-event-1",
        "toolName": "unknown",
        "displayName": "待执行工具",
        "draft": {},
    }
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    request_legacy_job_cancellation_response(
        job["id"], _cancel_envelope(job)
    )

    status, response = routes.payload_post(
        f"/jobs/{job['id']}/approve",
        {"eventId": "tool-event-1", "decision": "approved"},
    )

    assert status == 200
    assert response["job"]["status"] == "cancelled"
    assert response["job"]["cancellationDisposition"] == (
        "cancelled_cooperatively"
    )
    assert response["job"]["result"] == ""


def test_result_persist_closes_cancel_race_as_uncertain(
    tmp_path,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _active_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    request_legacy_job_cancellation_response(
        job["id"], _cancel_envelope(job)
    )

    completed = complete_legacy_job_result(job["id"], "late result")

    assert completed is None
    persisted = jobs.BACKGROUND_JOBS[job["id"]]
    assert persisted["status"] == "failed"
    assert persisted["cancellationDisposition"] == "manual_uncertain"
    assert "resultArtifact" not in persisted


def test_cancel_api_errors_and_legacy_empty_payload_compatibility(
    tmp_path,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    queued = _active_job(status="queued")
    jobs.BACKGROUND_JOBS[queued["id"]] = queued
    jobs.BACKGROUND_JOBS_LOADED = True

    invalid_status, invalid = routes.payload_post(
        f"/jobs/{queued['id']}/cancel", {"commandId": "partial"}
    )
    stale_status, stale = routes.payload_post(
        f"/jobs/{queued['id']}/cancel",
        {
            **_cancel_envelope(queued, command_id="cancel-stale"),
            "expectedUpdatedAt": "stale",
        },
    )
    legacy_status, legacy = routes.payload_post(
        f"/jobs/{queued['id']}/cancel", {}
    )
    missing_status, missing = routes.payload_post("/jobs/missing/cancel", {})

    assert (invalid_status, invalid["error"]) == (
        400, "invalid_job_cancel_command"
    )
    assert (stale_status, stale["error"]) == (409, "job_snapshot_stale")
    assert legacy_status == 200
    assert legacy["job"]["status"] == "cancelled"
    assert (missing_status, missing["reason"]) == (404, "job_not_found")
    assert LEGACY_JOB_V0_CAPABILITIES == frozenset()
