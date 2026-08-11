"""Best-effort command-level shadow observations for legacy Background Jobs."""
from __future__ import annotations

from typing import Any, Mapping

from core.authority_migration import (
    AuthorityVerdict,
    MigrationMode,
    build_authority_comparison,
    list_authority_comparisons,
    record_authority_comparison,
    snapshot_fingerprint,
)
from core.job_approval import legacy_job_pending_tool_fingerprint
from core.job_authority_cutover import (
    JobCutoverRequest,
    record_job_authority_cutover_decision,
)
from core.job_cutover_observation import record_job_cutover_observation
from core.job_execution_adapter import (
    JobCommand,
    JobCommandEnvelope,
    job_command_id,
    legacy_job_attempt_identity,
)
from core.run_store import get_run
from core.step_store import list_steps_for_run
from core.task_plan_job_shadow import (
    TaskPlanJobObservation,
    find_task_plan_job_binding,
    record_task_plan_job_observation,
)

_JOB_STATUSES = frozenset({
    "queued", "running", "waiting_approval", "complete", "failed", "cancelled",
})


def _now(runtime_context: Any) -> str:
    return runtime_context.now().isoformat()


def _config(runtime_context: Any) -> Mapping[str, object]:
    config = getattr(runtime_context, "config", None)
    return config if isinstance(config, Mapping) else {}


def prepare_shadow_create_payload(
    payload: Mapping[str, object],
    runtime_context: Any,
) -> dict[str, object]:
    prepared = dict(payload)
    run_id = str(payload.get("runtimeShadowRunId", "")).strip()
    if not run_id or runtime_context is None:
        return prepared
    run = get_run(runtime_context.db_path, run_id)
    steps = list_steps_for_run(runtime_context.db_path, run_id)
    if run is None or run.source != "shadow.task_plan" or not steps:
        return prepared
    step = steps[-1]
    if (
        str(payload.get("kind", "")).strip() == "vault_reflection"
        and step.capability != "vault_reflection"
    ):
        raise ValueError(
            "vault_reflection Job requires a matching shadow Step capability"
        )
    create_command_id = job_command_id(
        run.id,
        step.id,
        JobCommand.CREATE,
        "initial",
    )
    prepared["commandId"] = create_command_id
    prepared["runtimeShadowStepId"] = step.id
    return prepared


def _evidence_from_job(job: Mapping[str, object]) -> dict[str, object]:
    evidence: dict[str, object] = {}
    for field in ("createCommandId", "startCommandId"):
        value = job.get(field)
        if value:
            evidence[field] = value
    attempt_id, source = legacy_job_attempt_identity(job)
    evidence["attemptId"] = attempt_id
    evidence["attemptIdentitySource"] = source
    artifact = job.get("resultArtifact")
    if isinstance(artifact, Mapping):
        evidence.update({
            "artifactId": artifact.get("id"),
            "contentFingerprint": artifact.get("contentFingerprint"),
        })
    verification = job.get("resultVerification")
    if isinstance(verification, Mapping):
        evidence.update({
            "verificationId": verification.get("id"),
            "verificationArtifactId": verification.get("artifactId"),
            "verificationExpectedFingerprint": verification.get("expectedFingerprint"),
            "verificationObservedFingerprint": verification.get("observedFingerprint"),
            "verificationStatus": verification.get("status"),
            "verifier": verification.get("verifier"),
            "verificationReason": verification.get("reason"),
        })
    outcome = job.get("outcomeVerification")
    if isinstance(outcome, Mapping):
        evidence.update({
            "outcomeVerificationId": outcome.get("id"),
            "outcomeStatus": outcome.get("status"),
            "outcomeVerifier": outcome.get("verifier"),
            "outcomeReason": outcome.get("reason"),
        })
    return {key: value for key, value in evidence.items() if value is not None}


def _record_current_observation(
    runtime_context: Any,
    job: Mapping[str, object],
) -> TaskPlanJobObservation | None:
    job_id = str(job.get("id", "")).strip()
    status = str(job.get("status", "")).strip()
    updated_at = str(job.get("updatedAt", "")).strip()
    binding = find_task_plan_job_binding(runtime_context.db_path, job_id)
    if binding is None or status not in _JOB_STATUSES or not updated_at:
        return None
    return record_task_plan_job_observation(
        runtime_context.db_path,
        run_id=binding.run_id,
        legacy_job_id=job_id,
        legacy_status=status,
        job_updated_at=updated_at,
        observed_at=_now(runtime_context),
        evidence_summary=_evidence_from_job(job),
    )


def _shadow_receipt_for_observation(
    runtime_context: Any,
    observation: TaskPlanJobObservation,
    job_kind: str,
):
    evidence = observation.evidence_summary
    expected_fingerprint = snapshot_fingerprint({
        "jobId": observation.legacy_job_id,
        "jobKind": job_kind,
        "status": observation.legacy_status,
        "updatedAt": observation.job_updated_at,
        "attemptId": evidence.get("attemptId"),
        "verificationId": evidence.get("verificationId"),
        "outcomeVerificationId": evidence.get("outcomeVerificationId"),
    })
    receipts = list_authority_comparisons(
        runtime_context.db_path,
        domain="background_job",
        run_id=observation.run_id,
    )
    matching = [
        item for item in receipts
        if item.legacy_id == observation.legacy_job_id
        and item.reason == "legacy_job_shadow_projection_aligned"
        and item.legacy_snapshot_fingerprint == expected_fingerprint
    ]
    return matching[-1] if matching else None


def _runtime_snapshot(runtime_context: Any, run_id: str):
    run = get_run(runtime_context.db_path, run_id)
    steps = list_steps_for_run(runtime_context.db_path, run_id)
    if run is None or not steps:
        return None, None
    return run, steps[-1]


def _record_decision(
    runtime_context: Any,
    request: JobCutoverRequest,
    *,
    recorded_at: str,
) -> None:
    decision, receipt = record_job_authority_cutover_decision(
        runtime_context.db_path,
        _config(runtime_context),
        request,
        recorded_at=recorded_at,
    )
    record_job_cutover_observation(
        runtime_context.db_path,
        request,
        decision,
        receipt,
        recorded_at=recorded_at,
    )


def record_observation_cutover_decisions(
    runtime_context: Any,
    observation: TaskPlanJobObservation,
) -> None:
    binding = find_task_plan_job_binding(
        runtime_context.db_path,
        observation.legacy_job_id,
    )
    if binding is None:
        return
    run, step = _runtime_snapshot(runtime_context, binding.run_id)
    if run is None or step is None:
        return
    evidence = observation.evidence_summary
    create_id = evidence.get("createCommandId")
    if create_id:
        precreate = record_authority_comparison(
            runtime_context.db_path,
            build_authority_comparison(
                run_id=run.id,
                domain="background_job",
                legacy_id=create_id,
                mode=MigrationMode.SHADOW,
                legacy_snapshot={"commandId": create_id, "jobExists": False},
                runtime_snapshot={"jobKind": binding.job_kind},
                verdict=AuthorityVerdict.ALIGNED,
                reason="legacy_job_create_shadow_projection_aligned",
                recorded_at=observation.observed_at,
            ),
        )
        _record_decision(
            runtime_context,
            JobCutoverRequest(
                envelope=JobCommandEnvelope(
                    command_id=create_id,
                    run_id=run.id,
                    step_id=step.id,
                    command=JobCommand.CREATE,
                    requested_at=observation.observed_at,
                ),
                job_kind=binding.job_kind,
                expected_run_version=run.version,
                expected_run_state=run.state,
                expected_step_state=step.state,
                expected_attempt_id=None,
                comparison_receipt_id=precreate.id,
            ),
            recorded_at=observation.observed_at,
        )
    start_id = evidence.get("startCommandId")
    if start_id and observation.legacy_status == "queued":
        receipt = _shadow_receipt_for_observation(
            runtime_context,
            observation,
            binding.job_kind,
        )
        _record_decision(
            runtime_context,
            JobCutoverRequest(
                envelope=JobCommandEnvelope(
                    command_id=start_id,
                    run_id=run.id,
                    step_id=step.id,
                    command=JobCommand.START,
                    requested_at=observation.observed_at,
                    legacy_job_id=observation.legacy_job_id,
                    expected_job_status=observation.legacy_status,
                    expected_job_updated_at=observation.job_updated_at,
                    attempt_id=start_id,
                ),
                job_kind=binding.job_kind,
                expected_run_version=run.version,
                expected_run_state=run.state,
                expected_step_state=step.state,
                expected_attempt_id=start_id,
                comparison_receipt_id=receipt.id if receipt else "missing",
            ),
            recorded_at=observation.observed_at,
        )


def observe_bound_job_command(
    runtime_context: Any,
    job: Mapping[str, object],
    command: JobCommand,
    payload: Mapping[str, object],
) -> None:
    observation = _record_current_observation(runtime_context, job)
    if observation is None:
        return
    binding = find_task_plan_job_binding(runtime_context.db_path, observation.legacy_job_id)
    if binding is None:
        return
    run, step = _runtime_snapshot(runtime_context, binding.run_id)
    receipt = _shadow_receipt_for_observation(
        runtime_context,
        observation,
        binding.job_kind,
    )
    if run is None or step is None:
        return
    attempt_id = observation.evidence_summary.get("attemptId") or "missing_attempt"
    approval_event_id = None
    approval_fingerprint = None
    if command in {JobCommand.APPROVE, JobCommand.DENY}:
        approval_event_id = str(payload.get("eventId", "")).strip() or None
        pending_tool = job.get("pendingTool")
        if isinstance(pending_tool, Mapping):
            approval_fingerprint = legacy_job_pending_tool_fingerprint(pending_tool)
    envelope = JobCommandEnvelope(
        command_id=job_command_id(run.id, step.id, command, attempt_id),
        run_id=run.id,
        step_id=step.id,
        command=command,
        requested_at=_now(runtime_context),
        legacy_job_id=observation.legacy_job_id,
        expected_job_status=observation.legacy_status,
        expected_job_updated_at=observation.job_updated_at,
        attempt_id=attempt_id,
        approval_event_id=approval_event_id,
        approval_fingerprint=approval_fingerprint,
    )
    _record_decision(
        runtime_context,
        JobCutoverRequest(
            envelope=envelope,
            job_kind=binding.job_kind,
            expected_run_version=run.version,
            expected_run_state=run.state,
            expected_step_state=step.state,
            expected_attempt_id=attempt_id,
            comparison_receipt_id=receipt.id if receipt else "missing",
        ),
        recorded_at=_now(runtime_context),
    )


def observe_bound_job_snapshot(runtime_context: Any, job: object) -> None:
    if isinstance(job, Mapping):
        _record_current_observation(runtime_context, job)


def observe_legacy_job_command(
    runtime_context: Any,
    job_id: str,
    command: JobCommand,
    payload: Mapping[str, object],
) -> None:
    if runtime_context is None:
        return
    try:
        from terminal.api import job_routes as store

        with store.BACKGROUND_JOB_LOCK:
            store._load_jobs_locked()
            job = store.BACKGROUND_JOBS.get(job_id)
            snapshot = dict(job) if job is not None else None
        if snapshot is not None:
            observe_bound_job_command(
                runtime_context,
                snapshot,
                command,
                payload,
            )
    except Exception:
        # Shadow evidence never changes the authoritative legacy response.
        return


def observe_legacy_job_result(runtime_context: Any, result: object) -> None:
    if runtime_context is None or not isinstance(result, Mapping):
        return
    try:
        observe_bound_job_snapshot(runtime_context, result.get("job"))
    except Exception:
        return
