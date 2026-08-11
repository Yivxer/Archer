from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.job_approval import (
    JobApprovalFingerprintMismatchError,
    claim_legacy_job_approval,
    legacy_job_pending_tool_fingerprint,
)
from core.job_execution_adapter import (
    LEGACY_JOB_V0_CAPABILITIES,
    JobCommandCollisionError,
    JobCommandStaleSnapshotError,
    legacy_job_attempt_identity,
)
from terminal.api import _routes as routes, job_approval, job_routes as jobs
from terminal.api.job_cancellation import (
    request_legacy_job_cancellation_response,
)

UPDATED_AT = "2026-07-26T20:00:00+08:00"


def _waiting_job(job_id: str = "job-approval-1") -> dict:
    pending_tool = {
        "eventId": f"event-{job_id}",
        "toolName": "unknown",
        "displayName": "测试工具",
        "risk": "medium",
        "summary": "执行测试工具",
        "detail": "稳定审批草稿",
        "draft": {"args": {"value": job_id}},
        "createdAt": "2026-07-26T19:59:00+08:00",
    }
    pending_tool["fingerprint"] = legacy_job_pending_tool_fingerprint(
        pending_tool
    )
    return {
        "id": job_id,
        "title": "审批任务",
        "kind": "analysis",
        "prompt": "等待 Tool 审批",
        "status": "waiting_approval",
        "result": "",
        "createdAt": "2026-07-26T19:00:00+08:00",
        "updatedAt": UPDATED_AT,
        "startCommandId": f"start-{job_id}",
        "pendingTool": pending_tool,
    }


def _approval_envelope(
    job: dict,
    *,
    command_id: str = "approval-command-1",
    decision: str = "approved",
) -> dict[str, str]:
    attempt_id, _ = legacy_job_attempt_identity(job)
    pending_tool = job["pendingTool"]
    return {
        "commandId": command_id,
        "expectedStatus": "waiting_approval",
        "expectedUpdatedAt": str(job["updatedAt"]),
        "attemptId": attempt_id,
        "eventId": str(pending_tool["eventId"]),
        "approvalFingerprint": legacy_job_pending_tool_fingerprint(
            pending_tool
        ),
        "decision": decision,
    }


def _reset_jobs(path) -> None:
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    jobs.BACKGROUND_JOBS_PATH = path


def test_approval_claim_persists_one_receipt_and_replays() -> None:
    job = _waiting_job()
    store = {job["id"]: job}
    envelope = _approval_envelope(job)

    first = claim_legacy_job_approval(
        store,
        job["id"],
        envelope,
        decided_at="2026-07-26T20:01:00+08:00",
    )
    replay = claim_legacy_job_approval(
        store,
        job["id"],
        envelope,
        decided_at="2099-01-01T00:00:00+08:00",
    )

    assert first.accepted is True
    assert first.execute_tool is True
    assert replay.replayed is True
    assert replay.execute_tool is False
    assert replay.receipt_id == first.receipt_id
    assert len(job["approvalDecisions"]) == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("status", "running"),
        ("updatedAt", "2026-07-26T20:00:01+08:00"),
        ("startCommandId", "different-attempt"),
    ],
)
def test_approval_rejects_stale_snapshot_without_mutation(
    field: str,
    replacement: str,
) -> None:
    job = _waiting_job()
    envelope = _approval_envelope(job)
    job[field] = replacement
    before = copy.deepcopy(job)

    with pytest.raises(JobCommandStaleSnapshotError):
        claim_legacy_job_approval(
            {job["id"]: job},
            job["id"],
            envelope,
            decided_at="2026-07-26T20:01:00+08:00",
        )

    assert job == before


def test_approval_rejects_event_and_draft_fingerprint_changes() -> None:
    for mutation in ("event", "draft"):
        job = _waiting_job()
        envelope = _approval_envelope(job)
        if mutation == "event":
            job["pendingTool"]["eventId"] = "different-event"
            expected_error = JobCommandStaleSnapshotError
        else:
            job["pendingTool"]["draft"]["args"]["value"] = "changed"
            expected_error = JobApprovalFingerprintMismatchError
        before = copy.deepcopy(job)

        with pytest.raises(expected_error):
            claim_legacy_job_approval(
                {job["id"]: job},
                job["id"],
                envelope,
                decided_at="2026-07-26T20:01:00+08:00",
            )

        assert job == before


def test_approval_command_collision_does_not_touch_second_job() -> None:
    first = _waiting_job("job-approval-1")
    second = _waiting_job("job-approval-2")
    store = {first["id"]: first, second["id"]: second}
    claim_legacy_job_approval(
        store,
        first["id"],
        _approval_envelope(first),
        decided_at="2026-07-26T20:01:00+08:00",
    )
    second_before = copy.deepcopy(second)

    with pytest.raises(JobCommandCollisionError):
        claim_legacy_job_approval(
            store,
            second["id"],
            _approval_envelope(second),
            decided_at="2026-07-26T20:02:00+08:00",
        )

    assert second == second_before


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("decision", "denied"),
        ("eventId", "different-event"),
        ("approvalFingerprint", "different-fingerprint"),
    ],
)
def test_reused_approval_command_rejects_changed_identity(
    field: str,
    replacement: str,
) -> None:
    job = _waiting_job()
    store = {job["id"]: job}
    envelope = _approval_envelope(job)
    claim_legacy_job_approval(
        store,
        job["id"],
        envelope,
        decided_at="2026-07-26T20:01:00+08:00",
    )
    changed = dict(envelope)
    changed[field] = replacement

    with pytest.raises(JobCommandCollisionError):
        claim_legacy_job_approval(
            store,
            job["id"],
            changed,
            decided_at="2026-07-26T20:02:00+08:00",
        )


def test_denial_is_terminal_without_executing_tool(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _waiting_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    calls = []
    monkeypatch.setattr(
        job_approval,
        "_execute_approved_tool",
        lambda *_: calls.append("executed") or ("", ""),
    )

    status, result = routes.payload_post(
        f"/jobs/{job['id']}/approve",
        _approval_envelope(job, decision="denied"),
    )

    assert status == 200
    assert result["accepted"] is True
    assert result["executeTool"] is False
    assert result["job"]["status"] == "failed"
    assert result["job"]["result"] == ""
    assert calls == []


def test_stable_approval_executes_once_and_result_uses_current_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _waiting_job()
    attempt_id, _ = legacy_job_attempt_identity(job)
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    calls = []

    def execute(*_args):
        calls.append("executed")
        return "Tool result", ""

    monkeypatch.setattr(job_approval, "_execute_approved_tool", execute)
    envelope = _approval_envelope(job)
    first_status, first = routes.payload_post(
        f"/jobs/{job['id']}/approve", envelope
    )
    replay_status, replay = routes.payload_post(
        f"/jobs/{job['id']}/approve", envelope
    )

    assert first_status == replay_status == 200
    assert first["job"]["status"] == "complete"
    assert first["job"]["resultArtifact"]["attemptId"] == attempt_id
    assert first["job"]["resultVerification"]["status"] == "verified"
    assert first["job"]["approvalDisposition"] == "executed_verified"
    assert replay["replayed"] is True
    assert calls == ["executed"]


def test_concurrent_approval_requests_execute_tool_once(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _waiting_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    calls = []
    monkeypatch.setattr(
        job_approval,
        "_execute_approved_tool",
        lambda *_: calls.append("executed") or ("Tool result", ""),
    )
    envelope = _approval_envelope(job)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: routes.payload_post(
                    f"/jobs/{job['id']}/approve", envelope
                ),
                range(2),
            )
        )

    assert [status for status, _ in results] == [200, 200]
    assert sum(body["accepted"] for _, body in results) == 1
    assert sum(body["replayed"] for _, body in results) == 1
    assert calls == ["executed"]
    assert len(jobs.BACKGROUND_JOBS[job["id"]]["approvalDecisions"]) == 1


def test_changed_receipt_after_tool_is_manual_uncertain(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _waiting_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True

    def execute(*_args):
        jobs.BACKGROUND_JOBS[job["id"]][
            "activeApprovalDecisionId"
        ] = "replaced"
        return "Tool result", ""

    monkeypatch.setattr(job_approval, "_execute_approved_tool", execute)
    status, result = routes.payload_post(
        f"/jobs/{job['id']}/approve", _approval_envelope(job)
    )

    assert status == 200
    assert result["job"]["status"] == "failed"
    assert result["job"]["approvalDisposition"] == "manual_uncertain"
    assert result["job"]["failureKeyword"] == "job_approval_uncertain"
    assert result["job"]["result"] == ""


def test_cancellation_during_tool_execution_is_manual_uncertain(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _waiting_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True

    def execute(*_args):
        current = jobs.BACKGROUND_JOBS[job["id"]]
        attempt_id, _ = legacy_job_attempt_identity(current)
        status, _ = request_legacy_job_cancellation_response(
            job["id"],
            {
                "commandId": "cancel-during-approval",
                "expectedStatus": "running",
                "expectedUpdatedAt": current["updatedAt"],
                "attemptId": attempt_id,
            },
        )
        assert status == 200
        return "Tool result", ""

    monkeypatch.setattr(job_approval, "_execute_approved_tool", execute)
    status, result = routes.payload_post(
        f"/jobs/{job['id']}/approve", _approval_envelope(job)
    )

    assert status == 200
    assert result["job"]["status"] == "failed"
    assert result["job"]["cancellationDisposition"] == "manual_uncertain"
    assert result["job"]["result"] == ""


def test_receipt_survives_reload_and_still_deduplicates(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "background_jobs.json"
    _reset_jobs(path)
    job = _waiting_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    monkeypatch.setattr(
        job_approval,
        "_execute_approved_tool",
        lambda *_: ("Tool result", ""),
    )
    envelope = _approval_envelope(job)
    routes.payload_post(f"/jobs/{job['id']}/approve", envelope)
    saved = json.loads(path.read_text(encoding="utf-8"))

    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    status, replay = routes.payload_post(
        f"/jobs/{job['id']}/approve", envelope
    )

    assert saved["jobs"][0]["approvalDecisions"]
    assert status == 200
    assert replay["replayed"] is True
    assert jobs.BACKGROUND_JOBS[job["id"]]["approvalDecisions"]


def test_legacy_desktop_payload_remains_compatible(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _waiting_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    monkeypatch.setattr(
        job_approval,
        "_execute_approved_tool",
        lambda *_: ("Tool result", ""),
    )

    status, result = routes.payload_post(
        f"/jobs/{job['id']}/approve",
        {"eventId": job["pendingTool"]["eventId"], "decision": "approved"},
    )

    assert status == 200
    assert result["accepted"] is True
    assert result["job"]["status"] == "complete"


def test_approval_api_errors_and_runtime_capability_boundary(tmp_path) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    job = _waiting_job()
    jobs.BACKGROUND_JOBS[job["id"]] = job
    jobs.BACKGROUND_JOBS_LOADED = True
    partial = _approval_envelope(job)
    partial.pop("approvalFingerprint")

    bad_status, bad = routes.payload_post(
        f"/jobs/{job['id']}/approve", partial
    )
    stale_envelope = _approval_envelope(job)
    stale_envelope["expectedUpdatedAt"] = "stale"
    stale_status, stale = routes.payload_post(
        f"/jobs/{job['id']}/approve", stale_envelope
    )
    missing_status, missing = routes.payload_post(
        "/jobs/missing/approve",
        {"eventId": "event", "decision": "approved"},
    )

    assert bad_status == 400
    assert bad["error"] == "invalid_job_approval_command"
    assert stale_status == 409
    assert stale["error"] == "job_snapshot_stale"
    assert missing_status == 404
    assert missing["reason"] == "job_not_found"
    assert LEGACY_JOB_V0_CAPABILITIES == frozenset()
