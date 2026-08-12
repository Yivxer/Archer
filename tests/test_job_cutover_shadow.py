from __future__ import annotations

from datetime import datetime

from core.job_cutover_observation import list_job_cutover_observation_counts
from core.job_execution_adapter import JobCommand, job_command_id
from core.run_store import get_run, list_events
from core.runtime_context import create_runtime_context
from core.step_store import list_steps_for_run
from core.task_plan_job_shadow import (
    bind_task_plan_job,
    list_task_plan_job_observations,
    record_task_plan_job_observation,
)
from core.task_plan_observation import record_task_plan_observation
from core.task_plan_shadow import project_task_plan_shadow
from memory.migrations import run_migrations
from terminal.api import _routes as routes, job_routes
from terminal.api.job_cutover_shadow import (
    observe_bound_job_command,
    prepare_shadow_create_payload,
    record_observation_cutover_decisions,
)

NOW = "2026-07-31T20:00:00+08:00"


def _setup(tmp_path, *, job_kind: str = "vault_reflection"):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-command-observation",
        plan_event={
            "id": "plan-command-observation",
            "title": "观察真实 Job command",
            "status": "proposed",
            "steps": [{
                "id": 1,
                "action": "观察旧 Job",
                "tool": "vault_reflection",
            }],
        },
        now=NOW,
    )
    record_task_plan_observation(
        db_path,
        run_id=projection.run_id,
        plan_id="plan-command-observation",
        trace_id="trace-command-observation",
        legacy_status="accepted",
        observed_at=NOW,
    )
    bind_task_plan_job(
        db_path,
        run_id=projection.run_id,
        plan_id="plan-command-observation",
        legacy_job_id="job-observed-1",
        job_kind=job_kind,
        bound_at=NOW,
    )
    context = create_runtime_context(
        db_path=db_path,
        clock=lambda: datetime.fromisoformat(NOW),
    )
    return context, projection.run_id


def _command_counts(context, run_id: str) -> dict[tuple[str, str], int]:
    return {
        (item.command.value, item.status): item.count
        for item in list_job_cutover_observation_counts(
            context.db_path,
            run_id=run_id,
        )
    }


def test_plan_create_payload_gets_stable_runtime_command_identity(tmp_path) -> None:
    context, run_id = _setup(tmp_path)
    step = list_steps_for_run(context.db_path, run_id)[-1]
    payload = {
        "title": "真实 create",
        "kind": "vault_reflection",
        "prompt": "must-not-enter-receipt",
        "runtimeShadowRunId": run_id,
    }

    first = prepare_shadow_create_payload(payload, context)
    replay = prepare_shadow_create_payload(payload, context)

    assert replay == first
    assert first["runtimeShadowStepId"] == step.id
    assert first["commandId"] == job_command_id(
        run_id,
        step.id,
        JobCommand.CREATE,
        "initial",
    )


def test_vault_reflection_handoff_fails_closed_before_job_create(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-wrong-vault-capability",
        plan_event={
            "id": "plan-wrong-vault-capability",
            "title": "普通后台计划",
            "status": "proposed",
            "steps": [{"id": 1, "action": "分析", "tool": "llm"}],
        },
        now=NOW,
    )
    context = create_runtime_context(
        db_path=db_path,
        clock=lambda: datetime.fromisoformat(NOW),
    )
    called = False

    def _unexpected_create(_payload: dict) -> dict:
        nonlocal called
        called = True
        raise AssertionError("legacy Job must not be created")

    monkeypatch.setattr(job_routes, "_create_job", _unexpected_create)
    status, response = job_routes._create_job_response(
        {
            "title": "不得执行",
            "kind": "vault_reflection",
            "prompt": "不得执行",
            "runtimeShadowRunId": projection.run_id,
        },
        context,
    )

    assert status == 409
    assert response["error"] == "invalid_vault_reflection_shadow_handoff"
    assert called is False
    assert prepare_shadow_create_payload({"title": "legacy"}, context) == {
        "title": "legacy"
    }


def test_create_response_passes_stable_start_snapshot_without_claiming_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    context, run_id = _setup(tmp_path)
    job_routes.BACKGROUND_JOBS.clear()
    job_routes.BACKGROUND_JOBS_LOADED = False
    job_routes.BACKGROUND_JOBS_PATH = tmp_path / "background_jobs.json"
    starts: list[dict[str, object]] = []

    def capture_start(job_id: str, **kwargs: object) -> dict[str, object]:
        starts.append({"jobId": job_id, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(job_routes, "_start_job", capture_start)
    status, result = job_routes._create_job_response(
        {
            "title": "真实 create/start",
            "kind": "vault_reflection",
            "prompt": "legacy still owns execution",
            "runtimeShadowRunId": run_id,
        },
        context,
    )

    assert status == 200
    assert result["job"]["createCommandId"]
    assert result["job"]["startCommandId"]
    assert starts == [{
        "jobId": result["job"]["id"],
        "command_id": result["job"]["startCommandId"],
        "expected_status": "queued",
        "expected_updated_at": result["job"]["updatedAt"],
    }]
    assert get_run(context.db_path, run_id).source == "shadow.task_plan"


def test_queued_observation_records_replay_safe_create_and_start_candidates(
    tmp_path,
) -> None:
    context, run_id = _setup(tmp_path)
    event_count = len(list_events(context.db_path, run_id))
    step = list_steps_for_run(context.db_path, run_id)[-1]
    create_id = job_command_id(run_id, step.id, JobCommand.CREATE, "initial")
    start_id = job_command_id(run_id, step.id, JobCommand.START, create_id)
    observation = record_task_plan_job_observation(
        context.db_path,
        run_id=run_id,
        legacy_job_id="job-observed-1",
        legacy_status="queued",
        job_updated_at=NOW,
        observed_at=NOW,
        evidence_summary={
            "createCommandId": create_id,
            "startCommandId": start_id,
            "attemptId": start_id,
            "attemptIdentitySource": "start_command",
        },
    )

    record_observation_cutover_decisions(context, observation)
    record_observation_cutover_decisions(context, observation)

    assert _command_counts(context, run_id) == {
        ("create", "candidate"): 1,
        ("start", "candidate"): 1,
    }
    assert len(list_events(context.db_path, run_id)) == event_count
    assert get_run(context.db_path, run_id).state.value == "waiting_user"


def test_retry_candidate_and_cancel_forbidden_are_observed_without_execution(
    tmp_path,
) -> None:
    context, run_id = _setup(tmp_path)
    attempt_id = "start-command-observed-1"
    failed_job = {
        "id": "job-observed-1",
        "kind": "vault_reflection",
        "status": "failed",
        "updatedAt": "2026-07-31T20:01:00+08:00",
        "startCommandId": attempt_id,
        "prompt": "must-not-enter-receipt",
        "result": "must-not-enter-receipt",
    }

    observe_bound_job_command(context, failed_job, JobCommand.RETRY, {})
    running_job = {
        **failed_job,
        "status": "running",
        "updatedAt": "2026-07-31T20:02:00+08:00",
    }
    observe_bound_job_command(context, running_job, JobCommand.CANCEL, {})

    assert _command_counts(context, run_id) == {
        ("cancel", "forbidden"): 1,
        ("retry", "candidate"): 1,
    }
    assert get_run(context.db_path, run_id).state.value == "waiting_user"


def test_job_detail_poll_records_bound_verified_terminal_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    context, run_id = _setup(tmp_path)
    complete_job = {
        "id": "job-observed-1",
        "kind": "vault_reflection",
        "status": "complete",
        "updatedAt": "2026-07-31T20:03:00+08:00",
        "startCommandId": "start-command-observed-1",
        "resultArtifact": {
            "id": "artifact-observed-1",
            "attemptId": "retry-attempt-observed-1",
            "attemptIdentitySource": "legacy_retry",
            "contentFingerprint": "a" * 64,
        },
        "resultVerification": {
            "id": "verification-observed-1",
            "artifactId": "artifact-observed-1",
            "expectedFingerprint": "a" * 64,
            "observedFingerprint": "a" * 64,
            "status": "verified",
            "verifier": "legacy_job.persisted_result.v1",
            "reason": "persisted_result_matches",
        },
        "outcomeVerification": {
            "id": "outcome-observed-1",
            "status": "verified",
            "verifier": "legacy_job.vault_reflection.record.v1",
            "reason": "reflection_record_matches",
        },
    }
    monkeypatch.setattr(routes, "_job_detail", lambda _job_id: complete_job)

    status, _response = routes.payload_get(
        "/jobs/job-observed-1",
        runtime_context=context,
    )

    latest = list_task_plan_job_observations(context.db_path, run_id)[-1]
    assert status == 200
    assert latest.legacy_status == "complete"
    assert latest.evidence_summary["attemptId"] == "retry-attempt-observed-1"
    assert latest.evidence_summary["verificationStatus"] == "verified"
    assert latest.evidence_summary["outcomeStatus"] == "verified"
