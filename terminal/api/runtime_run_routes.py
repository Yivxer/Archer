"""FastAPI routes for Runtime Closure run state and safe reverification."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from core.authority_migration import (
    list_authority_comparisons,
    resolve_migration_mode,
)
from core.checkpoint_store import latest_checkpoint
from core.job_cutover_evidence_window import (
    EvidenceWindowError,
    review_job_cutover_evidence_window,
)
from core.obsidian_runtime import (
    RuntimeCancellationUnavailable,
    VerificationRetryUnavailable,
    request_write_cancellation,
    retry_obsidian_verification,
)
from core.outcome_store import list_artifacts
from core.run_contract import (
    RUN_CONTRACT_VERSION,
    RunCheckpoint,
    RunRecord,
    RunState,
)
from core.run_store import (
    RunSnapshotMismatch,
    get_verified_run,
)
from core.runtime_recovery import (
    inspect_startup_recovery,
    obsidian_resume_issue,
)
from core.step_store import list_steps_for_run
from core.task_plan_job_shadow import (
    TaskPlanJobShadowConflict,
    TaskPlanJobShadowUnavailable,
    bind_task_plan_job,
    list_task_plan_job_bindings,
    list_task_plan_job_observations,
    record_task_plan_job_observation,
)
from core.task_plan_observation import (
    TaskPlanObservationConflict,
    TaskPlanObservationUnavailable,
    list_task_plan_observations,
    record_task_plan_observation,
)
from core.task_plan_shadow import TASK_PLAN_SHADOW_SOURCE
from core.user_outcome_confirmation import (
    UserOutcomeConfirmationConflict,
    UserOutcomeConfirmationUnavailable,
    confirm_user_outcome,
)


def _runtime_db_path(request: Request) -> Path:
    return request.app.state.runtime_context.db_path


def _snapshot_conflict(exc: RunSnapshotMismatch) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"error": "run_snapshot_mismatch", "message": str(exc)},
    )


def _resume_unavailable(message: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"error": "runtime_resume_unavailable", "message": message},
    )


async def _list_runtime_runs(request: Request) -> dict[str, object]:
    report = await run_in_threadpool(
        inspect_startup_recovery,
        _runtime_db_path(request),
    )
    visible_runs = [
        run for run in report.scanned_runs
        if run.source != TASK_PLAN_SHADOW_SOURCE
    ]
    return {
        "ok": True,
        "runContractVersion": RUN_CONTRACT_VERSION,
        "scope": "non_terminal",
        "runs": [run.to_dict() for run in visible_runs],
        "recovery": report.to_dict(),
        "shadowRunCount": len(report.scanned_runs) - len(visible_runs),
    }


async def _background_job_evidence_window(
    request: Request,
    started_at: str | None = Query(default=None, alias="startedAt"),
) -> dict[str, object]:
    runtime = request.app.state.runtime_context
    try:
        report = await run_in_threadpool(
            review_job_cutover_evidence_window,
            runtime.db_path,
            runtime.config,
            started_at=started_at,
        )
    except EvidenceWindowError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_evidence_window", "message": str(exc)},
        ) from exc
    return {
        "ok": True,
        "runContractVersion": RUN_CONTRACT_VERSION,
        "evidenceWindow": report.to_dict(),
    }


async def _runtime_run_detail(
    run_id: str,
    request: Request,
) -> dict[str, object]:
    try:
        run = await run_in_threadpool(
            get_verified_run,
            _runtime_db_path(request),
            run_id,
        )
    except RunSnapshotMismatch as exc:
        raise _snapshot_conflict(exc) from exc
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "run_not_found", "runId": run_id},
        )
    checkpoint = await run_in_threadpool(
        latest_checkpoint,
        _runtime_db_path(request),
        run_id,
    )
    steps = await run_in_threadpool(
        list_steps_for_run,
        _runtime_db_path(request),
        run_id,
    )
    return {
        "ok": True,
        "runContractVersion": RUN_CONTRACT_VERSION,
        "run": run.to_dict(),
        "steps": [step.to_dict() for step in steps],
        "latestCheckpoint": checkpoint.to_dict() if checkpoint else None,
    }


async def _task_plan_shadow_detail(
    run_id: str,
    request: Request,
) -> dict[str, object]:
    try:
        run = await run_in_threadpool(
            get_verified_run,
            _runtime_db_path(request),
            run_id,
        )
    except RunSnapshotMismatch as exc:
        raise _snapshot_conflict(exc) from exc
    if run is None or run.source != TASK_PLAN_SHADOW_SOURCE:
        raise HTTPException(
            status_code=404,
            detail={"error": "task_plan_shadow_not_found", "runId": run_id},
        )
    steps = await run_in_threadpool(
        list_steps_for_run,
        _runtime_db_path(request),
        run_id,
    )
    observations = await run_in_threadpool(
        list_task_plan_observations,
        _runtime_db_path(request),
        run_id,
    )
    job_bindings = await run_in_threadpool(
        list_task_plan_job_bindings,
        _runtime_db_path(request),
        run_id,
    )
    job_observations = await run_in_threadpool(
        list_task_plan_job_observations,
        _runtime_db_path(request),
        run_id,
    )
    artifacts = [
        artifact
        for step in steps
        for artifact in await run_in_threadpool(
            list_artifacts,
            _runtime_db_path(request),
            step.id,
        )
    ]
    return {
        "ok": True,
        "runContractVersion": RUN_CONTRACT_VERSION,
        "run": run.to_dict(),
        "steps": [step.to_dict() for step in steps],
        "observations": [item.to_dict() for item in observations],
        "jobBindings": [item.to_dict() for item in job_bindings],
        "jobObservations": [item.to_dict() for item in job_observations],
        "artifacts": [item.to_dict() for item in artifacts],
        "authorityComparisons": [
            item.to_dict() for item in list_authority_comparisons(
                _runtime_db_path(request),
                domain="task_plan",
                run_id=run_id,
            )
        ],
    }


async def _observe_task_plan_shadow(
    run_id: str,
    payload: dict,
    request: Request,
) -> dict[str, object]:
    plan_id = str(payload.get("planId", "")).strip()
    trace_id = str(payload.get("traceId", "")).strip()
    legacy_status = str(payload.get("status", "")).strip()
    observed_at = str(payload.get("observedAt", "")).strip()
    if not all((plan_id, trace_id, observed_at)):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_task_plan_observation"},
        )
    try:
        observation, run = await run_in_threadpool(
            record_task_plan_observation,
            _runtime_db_path(request),
            run_id=run_id,
            plan_id=plan_id,
            trace_id=trace_id,
            legacy_status=legacy_status,
            observed_at=observed_at,
            migration_mode=resolve_migration_mode(
                request.app.state.runtime_context.config,
                "task_plan",
            ),
        )
    except (TaskPlanObservationConflict, TaskPlanObservationUnavailable) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "task_plan_observation_unavailable",
                "message": str(exc),
            },
        ) from exc
    return {
        "ok": True,
        "runContractVersion": RUN_CONTRACT_VERSION,
        "run": run.to_dict(),
        "observation": observation.to_dict(),
    }


def _job_shadow_conflict(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"error": "task_plan_job_shadow_unavailable", "message": str(exc)},
    )


async def _bind_task_plan_shadow_job(
    run_id: str,
    payload: dict,
    request: Request,
) -> dict[str, object]:
    plan_id = str(payload.get("planId", "")).strip()
    legacy_job_id = str(payload.get("jobId", "")).strip()
    job_kind = str(payload.get("jobKind", "")).strip()
    bound_at = str(payload.get("boundAt", "")).strip()
    if not all((plan_id, legacy_job_id, job_kind, bound_at)):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_task_plan_job_binding"},
        )
    try:
        binding, run = await run_in_threadpool(
            bind_task_plan_job,
            _runtime_db_path(request),
            run_id=run_id,
            plan_id=plan_id,
            legacy_job_id=legacy_job_id,
            job_kind=job_kind,
            bound_at=bound_at,
        )
    except (TaskPlanJobShadowConflict, TaskPlanJobShadowUnavailable) as exc:
        raise _job_shadow_conflict(exc) from exc
    return {
        "ok": True,
        "runContractVersion": RUN_CONTRACT_VERSION,
        "run": run.to_dict(),
        "binding": binding.to_dict(),
    }


async def _observe_task_plan_shadow_job(
    run_id: str,
    job_id: str,
    payload: dict,
    request: Request,
) -> dict[str, object]:
    legacy_status = str(payload.get("status", "")).strip()
    job_updated_at = str(payload.get("jobUpdatedAt", "")).strip()
    observed_at = str(payload.get("observedAt", "")).strip()
    evidence_summary = payload.get("evidenceSummary")
    if (
        not all((legacy_status, job_updated_at, observed_at))
        or (
            evidence_summary is not None
            and not isinstance(evidence_summary, dict)
        )
    ):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_task_plan_job_observation"},
        )
    try:
        observation = await run_in_threadpool(
            record_task_plan_job_observation,
            _runtime_db_path(request),
            run_id=run_id,
            legacy_job_id=job_id,
            legacy_status=legacy_status,
            job_updated_at=job_updated_at,
            observed_at=observed_at,
            evidence_summary=evidence_summary,
        )
    except (TaskPlanJobShadowConflict, TaskPlanJobShadowUnavailable) as exc:
        raise _job_shadow_conflict(exc) from exc
    try:
        from terminal.api.job_cutover_shadow import (
            record_observation_cutover_decisions,
        )

        await run_in_threadpool(
            record_observation_cutover_decisions,
            request.app.state.runtime_context,
            observation,
        )
    except Exception:
        # Command-level shadow evidence must never block the legacy Job path.
        pass
    return {
        "ok": True,
        "runContractVersion": RUN_CONTRACT_VERSION,
        "observation": observation.to_dict(),
    }


async def _retry_runtime_verification(
    run_id: str,
    request: Request,
) -> dict[str, object]:
    runtime = request.app.state.runtime_context
    try:
        receipt = await run_in_threadpool(
            retry_obsidian_verification,
            runtime.db_path,
            run_id,
            now=runtime.now().isoformat(),
        )
    except VerificationRetryUnavailable as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "verification_retry_unavailable", "message": str(exc)},
        ) from exc
    run = await run_in_threadpool(get_verified_run, runtime.db_path, run_id)
    return {
        "ok": True,
        "runContractVersion": RUN_CONTRACT_VERSION,
        "run": run.to_dict() if run else None,
        "verificationReceipt": receipt.to_dict(),
    }


async def _confirm_runtime_outcome(
    run_id: str,
    payload: dict,
    request: Request,
) -> dict[str, object]:
    required = {
        "stepId": str(payload.get("stepId", "")).strip(),
        "attemptId": str(payload.get("attemptId", "")).strip(),
        "artifactId": str(payload.get("artifactId", "")).strip(),
        "artifactFingerprint": str(
            payload.get("artifactFingerprint", "")
        ).strip(),
        "decision": str(payload.get("decision", "")).strip(),
    }
    if not all(required.values()):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_outcome_confirmation"},
        )
    try:
        confirmation = await run_in_threadpool(
            confirm_user_outcome,
            _runtime_db_path(request),
            run_id=run_id,
            step_id=required["stepId"],
            attempt_id=required["attemptId"],
            artifact_id=required["artifactId"],
            artifact_fingerprint=required["artifactFingerprint"],
            decision=required["decision"],
            confirmed_at=request.app.state.runtime_context.now().isoformat(),
        )
    except (UserOutcomeConfirmationConflict, UserOutcomeConfirmationUnavailable) as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "outcome_confirmation_conflict", "message": str(exc)},
        ) from exc
    return {
        "ok": True,
        "runContractVersion": RUN_CONTRACT_VERSION,
        "confirmation": confirmation.to_dict(),
    }


def _require_obsidian_resume_checkpoint(
    run: RunRecord | None,
    checkpoint: RunCheckpoint | None,
) -> None:
    if run is None:
        raise _resume_unavailable("run does not exist")
    issue = obsidian_resume_issue(run, checkpoint)
    if issue is not None:
        raise _resume_unavailable(issue)


async def _resume_runtime_run(
    run_id: str,
    request: Request,
) -> dict[str, object]:
    runtime = request.app.state.runtime_context
    run = await run_in_threadpool(get_verified_run, runtime.db_path, run_id)
    checkpoint = await run_in_threadpool(
        latest_checkpoint,
        runtime.db_path,
        run_id,
    )
    _require_obsidian_resume_checkpoint(run, checkpoint)
    result = await _retry_runtime_verification(run_id, request)
    result["resumeAdapter"] = "obsidian_verification"
    result["checkpointId"] = checkpoint.id if checkpoint else None
    return result


async def _cancel_runtime_run(
    run_id: str,
    request: Request,
) -> dict[str, object]:
    runtime = request.app.state.runtime_context
    try:
        run = await run_in_threadpool(
            request_write_cancellation,
            runtime.db_path,
            run_id,
            runtime.cancellations,
            now=runtime.now().isoformat(),
        )
    except RuntimeCancellationUnavailable as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "runtime_cancellation_unavailable", "message": str(exc)},
        ) from exc
    if run.state is RunState.CANCELLED:
        runtime.cancellations.release(run_id)
    return {
        "ok": True,
        "runContractVersion": RUN_CONTRACT_VERSION,
        "run": run.to_dict(),
        "cancellationRequested": True,
    }


def register_runtime_run_routes(app: FastAPI) -> None:
    app.add_api_route(
        "/runtime/authority/background-job/evidence-window",
        _background_job_evidence_window,
        methods=["GET"],
    )
    app.add_api_route(
        "/runtime/runs",
        _list_runtime_runs,
        methods=["GET"],
    )
    app.add_api_route(
        "/runtime/task-plan-shadows/{run_id}",
        _task_plan_shadow_detail,
        methods=["GET"],
    )
    app.add_api_route(
        "/runtime/task-plan-shadows/{run_id}/observe",
        _observe_task_plan_shadow,
        methods=["POST"],
    )
    app.add_api_route(
        "/runtime/task-plan-shadows/{run_id}/jobs/bind",
        _bind_task_plan_shadow_job,
        methods=["POST"],
    )
    app.add_api_route(
        "/runtime/task-plan-shadows/{run_id}/jobs/{job_id}/observe",
        _observe_task_plan_shadow_job,
        methods=["POST"],
    )
    app.add_api_route(
        "/runtime/runs/{run_id}",
        _runtime_run_detail,
        methods=["GET"],
    )
    app.add_api_route(
        "/runtime/runs/{run_id}/retry-verification",
        _retry_runtime_verification,
        methods=["POST"],
    )
    app.add_api_route(
        "/runtime/runs/{run_id}/outcome-confirmation",
        _confirm_runtime_outcome,
        methods=["POST"],
    )
    app.add_api_route(
        "/runtime/runs/{run_id}/resume",
        _resume_runtime_run,
        methods=["POST"],
    )
    app.add_api_route(
        "/runtime/runs/{run_id}/cancel",
        _cancel_runtime_run,
        methods=["POST"],
    )
