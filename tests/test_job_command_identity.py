from __future__ import annotations

import json

from terminal.api import _routes as routes, job_routes as jobs


def _reset_jobs(path) -> None:
    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    jobs.BACKGROUND_JOBS_PATH = path


def _create_payload(**overrides: object) -> dict:
    payload = {
        "title": "持久化命令",
        "kind": "analysis",
        "prompt": "检查 legacy Job command identity",
        "autoStart": False,
        "commandId": "create-command-001",
    }
    payload.update(overrides)
    return payload


def test_create_command_replay_reuses_job_without_duplicate_start(
    tmp_path,
    monkeypatch,
) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    starts: list[str] = []
    monkeypatch.setattr(jobs, "_start_job", starts.append)
    payload = _create_payload(autoStart=True)

    first = jobs._create_job(payload)
    replay = jobs._create_job(dict(payload))

    assert replay["job"]["id"] == first["job"]["id"]
    assert first["replayed"] is False
    assert replay["replayed"] is True
    assert starts == [first["job"]["id"]]
    assert len(jobs.BACKGROUND_JOBS) == 1


def test_create_command_collision_is_explicit_and_does_not_overwrite(tmp_path) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    first_status, first = routes.payload_post("/jobs", _create_payload())

    collision_status, collision = routes.payload_post(
        "/jobs",
        _create_payload(prompt="同一命令改成另一份载荷"),
    )

    assert first_status == 200
    assert collision_status == 409
    assert collision == {
        "ok": False,
        "error": "job_command_collision",
        "message": "job create command collision: create-command-001",
        "commandId": "create-command-001",
    }
    assert len(jobs.BACKGROUND_JOBS) == 1
    assert jobs.BACKGROUND_JOBS[first["job"]["id"]]["prompt"] == first["job"]["prompt"]


def test_create_command_identity_survives_process_restart(tmp_path) -> None:
    path = tmp_path / "background_jobs.json"
    _reset_jobs(path)
    first = jobs._create_job(_create_payload())

    persisted = json.loads(path.read_text(encoding="utf-8"))["jobs"][0]
    assert persisted["createCommandId"] == "create-command-001"
    assert len(persisted["createPayloadFingerprint"]) == 64

    jobs.BACKGROUND_JOBS.clear()
    jobs.BACKGROUND_JOBS_LOADED = False
    replay = jobs._create_job(_create_payload())

    assert replay["replayed"] is True
    assert replay["job"]["id"] == first["job"]["id"]
    assert len(jobs.BACKGROUND_JOBS) == 1


def test_create_without_command_id_remains_backward_compatible(tmp_path) -> None:
    _reset_jobs(tmp_path / "background_jobs.json")
    payload = _create_payload()
    payload.pop("commandId")

    first = jobs._create_job(payload)
    second = jobs._create_job(payload)

    assert first["job"]["id"] != second["job"]["id"]
    assert "createCommandId" not in first["job"]
    assert len(jobs.BACKGROUND_JOBS) == 2
