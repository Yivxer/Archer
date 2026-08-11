from __future__ import annotations

from threading import Thread as CallerThread

from core.job_execution_adapter import (
    JobCommandCollisionError,
    JobCommandStaleSnapshotError,
)
from terminal.api import job_routes as jobs


def _reset_jobs(path) -> None:
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    jobs.BACKGROUND_JOBS_PATH = path


def _queued_job(tmp_path) -> dict:
    _reset_jobs(tmp_path / "background_jobs.json")
    return jobs._create_job({
        "title": "原子启动",
        "kind": "analysis",
        "prompt": "验证 legacy Job start claim",
        "autoStart": False,
    })["job"]


class _FakeThread:
    starts: list[str] = []

    def __init__(self, *, target, args, daemon) -> None:
        self.job_id = str(args[0])

    def start(self) -> None:
        self.starts.append(self.job_id)


def _patch_threads(monkeypatch) -> None:
    _FakeThread.starts = []
    monkeypatch.setattr(jobs.threading, "Thread", _FakeThread)


def test_start_claim_is_atomic_and_replay_does_not_launch_second_worker(
    tmp_path,
    monkeypatch,
) -> None:
    job = _queued_job(tmp_path)
    _patch_threads(monkeypatch)
    command = {
        "command_id": "start-command-001",
        "expected_status": "queued",
        "expected_updated_at": job["updatedAt"],
    }

    first = jobs._start_job(job["id"], **command)
    replay = jobs._start_job(job["id"], **command)

    assert first["claimed"] is True
    assert replay["claimed"] is False
    assert replay["replayed"] is True
    assert _FakeThread.starts == [job["id"]]
    assert jobs.BACKGROUND_JOBS[job["id"]]["status"] == "running"


def test_concurrent_start_claims_launch_only_one_worker(tmp_path, monkeypatch) -> None:
    job = _queued_job(tmp_path)
    _patch_threads(monkeypatch)
    command = {
        "command_id": "start-command-concurrent",
        "expected_status": "queued",
        "expected_updated_at": job["updatedAt"],
    }
    results: list[dict] = []

    callers = [
        CallerThread(target=lambda: results.append(jobs._start_job(job["id"], **command)))
        for _ in range(2)
    ]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join()

    assert sorted(result["claimed"] for result in results) == [False, True]
    assert _FakeThread.starts == [job["id"]]


def test_start_claim_rejects_stale_snapshot_before_mutation(
    tmp_path,
    monkeypatch,
) -> None:
    job = _queued_job(tmp_path)
    _patch_threads(monkeypatch)

    try:
        jobs._start_job(
            job["id"],
            command_id="start-command-stale",
            expected_status="queued",
            expected_updated_at="2026-01-01T00:00:00",
        )
    except JobCommandStaleSnapshotError as exc:
        assert "start-command-stale" in str(exc)
    else:
        raise AssertionError("stale start snapshot must be rejected")

    assert jobs.BACKGROUND_JOBS[job["id"]]["status"] == "queued"
    assert "startCommandId" not in jobs.BACKGROUND_JOBS[job["id"]]
    assert _FakeThread.starts == []


def test_start_command_collision_cannot_claim_another_job(
    tmp_path,
    monkeypatch,
) -> None:
    first = _queued_job(tmp_path)
    second = jobs._create_job({
        "title": "第二个任务",
        "prompt": "不能复用另一个 Job 的 start command",
        "autoStart": False,
    })["job"]
    _patch_threads(monkeypatch)
    jobs._start_job(
        first["id"],
        command_id="start-command-collision",
        expected_status="queued",
        expected_updated_at=first["updatedAt"],
    )

    try:
        jobs._start_job(
            second["id"],
            command_id="start-command-collision",
            expected_status="queued",
            expected_updated_at=second["updatedAt"],
        )
    except JobCommandCollisionError as exc:
        assert exc.command_id == "start-command-collision"
        assert "job start command collision" in str(exc)
    else:
        raise AssertionError("start command collision must be rejected")

    assert jobs.BACKGROUND_JOBS[second["id"]]["status"] == "queued"
    assert _FakeThread.starts == [first["id"]]


def test_start_claim_survives_restart_and_replay_stays_suppressed(
    tmp_path,
    monkeypatch,
) -> None:
    job = _queued_job(tmp_path)
    _patch_threads(monkeypatch)
    command = {
        "command_id": "start-command-restart",
        "expected_status": "queued",
        "expected_updated_at": job["updatedAt"],
    }
    jobs._start_job(job["id"], **command)

    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    replay = jobs._start_job(job["id"], **command)

    assert replay["replayed"] is True
    assert replay["job"]["status"] == "failed"
    assert replay["job"]["startCommandId"] == "start-command-restart"
    assert _FakeThread.starts == [job["id"]]


def test_legacy_start_without_command_envelope_remains_compatible(
    tmp_path,
    monkeypatch,
) -> None:
    job = _queued_job(tmp_path)
    _patch_threads(monkeypatch)

    first = jobs._start_job(job["id"])
    second = jobs._start_job(job["id"])

    assert first["claimed"] is True
    assert second["claimed"] is False
    assert second["reason"] == "job_not_queued"
    assert _FakeThread.starts == [job["id"]]
