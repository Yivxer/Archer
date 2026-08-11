"""Append-only evidence linking TaskPlan shadow Runs to legacy Jobs."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.authority_migration import authority_comparison_schema_available
from core.job_adapter_shadow import record_job_adapter_shadow_audit
from core.job_artifact_projection import project_verified_job_result
from core.run_contract import RunRecord, RunState
from core.run_store import get_run
from core.run_store_support import connect
from core.step_store import list_steps_for_run
from core.task_plan_observation import list_task_plan_observations
from core.task_plan_shadow import TASK_PLAN_SHADOW_SOURCE

LegacyJobStatus = Literal[
    "queued",
    "running",
    "waiting_approval",
    "complete",
    "failed",
    "cancelled",
]
_ALLOWED_LEGACY_JOB_STATUSES = frozenset({
    "queued", "running", "waiting_approval",
    "complete", "failed", "cancelled",
})


class TaskPlanJobShadowUnavailable(RuntimeError):
    """Raised when a legacy Job cannot be correlated to a shadow Run."""


class TaskPlanJobShadowConflict(RuntimeError):
    """Raised when an append-only Job correlation collides."""


@dataclass(frozen=True, slots=True)
class TaskPlanJobBinding:
    id: str
    run_id: str
    plan_id: str
    legacy_job_id: str
    job_kind: str
    runtime_execution_claimed: bool
    bound_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "legacy_job_id": self.legacy_job_id,
            "job_kind": self.job_kind,
            "runtime_execution_claimed": self.runtime_execution_claimed,
            "bound_at": self.bound_at,
        }


@dataclass(frozen=True, slots=True)
class TaskPlanJobObservation:
    id: str
    binding_id: str
    run_id: str
    legacy_job_id: str
    legacy_status: LegacyJobStatus
    job_updated_at: str
    observed_at: str
    verification_receipt_id: str
    evidence_summary: dict[str, str]
    runtime_state_changed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "binding_id": self.binding_id,
            "run_id": self.run_id,
            "legacy_job_id": self.legacy_job_id,
            "legacy_status": self.legacy_status,
            "job_updated_at": self.job_updated_at,
            "observed_at": self.observed_at,
            "verification_receipt_id": self.verification_receipt_id,
            "evidence_summary": dict(self.evidence_summary),
            "runtime_state_changed": self.runtime_state_changed,
        }


def _stable_id(prefix: str, *parts: str) -> str:
    material = "\0".join(parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _row_to_binding(row: sqlite3.Row) -> TaskPlanJobBinding:
    return TaskPlanJobBinding(
        id=row["id"],
        run_id=row["run_id"],
        plan_id=row["plan_id"],
        legacy_job_id=row["legacy_job_id"],
        job_kind=row["job_kind"],
        runtime_execution_claimed=bool(row["runtime_execution_claimed"]),
        bound_at=row["bound_at"],
    )


def _row_to_observation(row: sqlite3.Row) -> TaskPlanJobObservation:
    try:
        raw_evidence = json.loads(row["evidence_json"])
    except (json.JSONDecodeError, TypeError):
        raw_evidence = {}
    evidence_summary = (
        {str(key): str(value) for key, value in raw_evidence.items()}
        if isinstance(raw_evidence, dict)
        else {}
    )
    return TaskPlanJobObservation(
        id=row["id"],
        binding_id=row["binding_id"],
        run_id=row["run_id"],
        legacy_job_id=row["legacy_job_id"],
        legacy_status=row["legacy_status"],
        job_updated_at=row["job_updated_at"],
        observed_at=row["observed_at"],
        verification_receipt_id=row["verification_receipt_id"],
        evidence_summary=evidence_summary,
        runtime_state_changed=bool(row["runtime_state_changed"]),
    )


def list_task_plan_job_bindings(
    db_path: str | Path,
    run_id: str,
) -> list[TaskPlanJobBinding]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM runtime_task_plan_job_bindings
            WHERE run_id = ? ORDER BY bound_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_binding(row) for row in rows]


def find_task_plan_job_binding(
    db_path: str | Path,
    legacy_job_id: str,
) -> TaskPlanJobBinding | None:
    conn = connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT * FROM runtime_task_plan_job_bindings
            WHERE legacy_job_id = ?
            """,
            (legacy_job_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_binding(row) if row is not None else None


def list_task_plan_job_observations(
    db_path: str | Path,
    run_id: str,
) -> list[TaskPlanJobObservation]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM runtime_task_plan_job_observations
            WHERE run_id = ?
            ORDER BY job_updated_at ASC, observed_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_observation(row) for row in rows]


def _require_accepted_shadow(
    db_path: str | Path,
    run_id: str,
    plan_id: str,
) -> RunRecord:
    run = get_run(db_path, run_id)
    if run is None or run.source != TASK_PLAN_SHADOW_SOURCE:
        raise TaskPlanJobShadowUnavailable(f"TaskPlan shadow does not exist: {run_id}")
    if run.state is not RunState.WAITING_USER:
        raise TaskPlanJobShadowUnavailable(
            f"accepted shadow must remain waiting_user, got {run.state.value}"
        )
    accepted = any(
        item.plan_id == plan_id and item.legacy_status == "accepted"
        for item in list_task_plan_observations(db_path, run_id)
    )
    if not accepted:
        raise TaskPlanJobShadowUnavailable("legacy plan was not observed as accepted")
    return run


def _binding_identity(binding: TaskPlanJobBinding) -> tuple[object, ...]:
    return (
        binding.id,
        binding.run_id,
        binding.plan_id,
        binding.legacy_job_id,
        binding.job_kind,
        binding.runtime_execution_claimed,
    )


def _existing_binding_or_conflict(
    db_path: str | Path,
    requested: TaskPlanJobBinding,
) -> TaskPlanJobBinding:
    conn = connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT * FROM runtime_task_plan_job_bindings
            WHERE run_id = ? OR legacy_job_id = ?
            """,
            (requested.run_id, requested.legacy_job_id),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise TaskPlanJobShadowConflict("legacy Job binding insert failed")
    existing = _row_to_binding(row)
    if _binding_identity(existing) != _binding_identity(requested):
        raise TaskPlanJobShadowConflict("legacy Job binding collision")
    return existing


def bind_task_plan_job(
    db_path: str | Path,
    *,
    run_id: str,
    plan_id: str,
    legacy_job_id: str,
    job_kind: str,
    bound_at: str,
) -> tuple[TaskPlanJobBinding, RunRecord]:
    if not all(
        value.strip() for value in (plan_id, legacy_job_id, job_kind, bound_at)
    ):
        raise TaskPlanJobShadowUnavailable("binding fields must not be empty")
    run = _require_accepted_shadow(db_path, run_id, plan_id)
    if job_kind == "vault_reflection":
        steps = list_steps_for_run(db_path, run_id)
        if not steps or steps[-1].capability != "vault_reflection":
            raise TaskPlanJobShadowUnavailable(
                "vault_reflection binding requires a matching final Step capability"
            )
    binding = TaskPlanJobBinding(
        id=_stable_id("task-plan-job-binding", run_id, legacy_job_id),
        run_id=run_id,
        plan_id=plan_id,
        legacy_job_id=legacy_job_id,
        job_kind=job_kind,
        runtime_execution_claimed=False,
        bound_at=bound_at,
    )
    conn = connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO runtime_task_plan_job_bindings(
                    id, run_id, plan_id, legacy_job_id, job_kind,
                    runtime_execution_claimed, bound_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    binding.id,
                    binding.run_id,
                    binding.plan_id,
                    binding.legacy_job_id,
                    binding.job_kind,
                    int(binding.runtime_execution_claimed),
                    binding.bound_at,
                ),
            )
        return binding, run
    except sqlite3.IntegrityError:
        return _existing_binding_or_conflict(db_path, binding), run
    finally:
        conn.close()


def _observation_identity(
    observation: TaskPlanJobObservation,
) -> tuple[object, ...]:
    return (
        observation.id,
        observation.binding_id,
        observation.run_id,
        observation.legacy_job_id,
        observation.legacy_status,
        observation.job_updated_at,
        observation.verification_receipt_id,
        _canonical_evidence_json(observation.evidence_summary),
        observation.runtime_state_changed,
    )


_EVIDENCE_FIELDS = (
    "createCommandId",
    "startCommandId",
    "artifactId",
    "contentFingerprint",
    "attemptId",
    "attemptIdentitySource",
    "verificationId",
    "verificationArtifactId",
    "verificationExpectedFingerprint",
    "verificationObservedFingerprint",
    "verificationStatus",
    "verifier",
    "verificationReason",
    "outcomeVerificationId",
    "outcomeStatus",
    "outcomeVerifier",
    "outcomeReason",
)


def _normalize_evidence_summary(
    evidence_summary: Mapping[str, object] | None,
) -> dict[str, str]:
    if evidence_summary is None:
        return {}
    normalized = {
        field: str(evidence_summary[field]).strip()
        for field in _EVIDENCE_FIELDS
        if evidence_summary.get(field) is not None
        and str(evidence_summary[field]).strip()
    }
    verification_status = normalized.get("verificationStatus")
    if verification_status not in {None, "verified", "failed", "uncertain"}:
        raise TaskPlanJobShadowUnavailable(
            f"unsupported Job verification status: {verification_status}"
        )
    outcome_status = normalized.get("outcomeStatus")
    if outcome_status not in {None, "verified", "failed", "uncertain"}:
        raise TaskPlanJobShadowUnavailable(
            f"unsupported Job outcome status: {outcome_status}"
        )
    return normalized


def _canonical_evidence_json(evidence_summary: Mapping[str, str]) -> str:
    return json.dumps(
        dict(evidence_summary),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _require_job_binding(
    db_path: str | Path,
    run_id: str,
    legacy_job_id: str,
) -> TaskPlanJobBinding:
    binding = next(
        (
            item for item in list_task_plan_job_bindings(db_path, run_id)
            if item.legacy_job_id == legacy_job_id
        ),
        None,
    )
    if binding is None:
        raise TaskPlanJobShadowUnavailable("legacy Job is not bound to this shadow")
    return binding


def _build_job_observation(
    *,
    binding: TaskPlanJobBinding,
    run_id: str,
    legacy_job_id: str,
    legacy_status: LegacyJobStatus,
    job_updated_at: str,
    observed_at: str,
    evidence_summary: dict[str, str],
) -> TaskPlanJobObservation:
    verification_id = evidence_summary.get("verificationId", "")
    return TaskPlanJobObservation(
        id=_stable_id(
            "task-plan-job-observation",
            legacy_job_id,
            legacy_status,
            job_updated_at,
            verification_id,
        ),
        binding_id=binding.id,
        run_id=run_id,
        legacy_job_id=legacy_job_id,
        legacy_status=legacy_status,
        job_updated_at=job_updated_at,
        observed_at=observed_at,
        verification_receipt_id=verification_id,
        evidence_summary=evidence_summary,
        runtime_state_changed=False,
    )


def _record_job_runtime_shadow(
    db_path: str | Path,
    observation: TaskPlanJobObservation,
    binding: TaskPlanJobBinding,
) -> None:
    projection = project_verified_job_result(
        db_path,
        observation_id=observation.id,
        run_id=observation.run_id,
        legacy_job_id=observation.legacy_job_id,
        job_kind=binding.job_kind,
        legacy_status=observation.legacy_status,
        evidence_summary=observation.evidence_summary,
        recorded_at=observation.observed_at,
    )
    record_job_adapter_shadow_audit(
        db_path,
        run_id=observation.run_id,
        legacy_job_id=observation.legacy_job_id,
        job_kind=binding.job_kind,
        legacy_status=observation.legacy_status,
        job_updated_at=observation.job_updated_at,
        evidence_summary=observation.evidence_summary,
        recorded_at=observation.observed_at,
        runtime_artifact_ready=projection.artifact is not None,
    )


def record_task_plan_job_observation(
    db_path: str | Path,
    *,
    run_id: str,
    legacy_job_id: str,
    legacy_status: LegacyJobStatus,
    job_updated_at: str,
    observed_at: str,
    evidence_summary: Mapping[str, object] | None = None,
) -> TaskPlanJobObservation:
    if legacy_status not in _ALLOWED_LEGACY_JOB_STATUSES:
        raise TaskPlanJobShadowUnavailable(
            f"unsupported legacy Job status: {legacy_status}"
        )
    if not all(value.strip() for value in (
        legacy_job_id, job_updated_at, observed_at
    )):
        raise TaskPlanJobShadowUnavailable("observation fields must not be empty")
    binding = _require_job_binding(db_path, run_id, legacy_job_id)
    normalized_evidence = _normalize_evidence_summary(evidence_summary)
    observation = _build_job_observation(
        binding=binding,
        run_id=run_id,
        legacy_job_id=legacy_job_id,
        legacy_status=legacy_status,
        job_updated_at=job_updated_at,
        observed_at=observed_at,
        evidence_summary=normalized_evidence,
    )
    persisted = _insert_observation(db_path, observation)
    if authority_comparison_schema_available(db_path):
        _record_job_runtime_shadow(db_path, persisted, binding)
    return persisted


def _insert_observation(
    db_path: str | Path,
    observation: TaskPlanJobObservation,
) -> TaskPlanJobObservation:
    conn = connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO runtime_task_plan_job_observations(
                    id, binding_id, run_id, legacy_job_id, legacy_status,
                    job_updated_at, observed_at, verification_receipt_id,
                    evidence_json, runtime_state_changed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.id,
                    observation.binding_id,
                    observation.run_id,
                    observation.legacy_job_id,
                    observation.legacy_status,
                    observation.job_updated_at,
                    observation.observed_at,
                    observation.verification_receipt_id,
                    _canonical_evidence_json(observation.evidence_summary),
                    int(observation.runtime_state_changed),
                ),
            )
        return observation
    except sqlite3.IntegrityError:
        existing = next(
            (
                item for item in list_task_plan_job_observations(
                    db_path, observation.run_id
                )
                if item.id == observation.id
            ),
            None,
        )
        if existing is None or _observation_identity(existing) != (
            _observation_identity(observation)
        ):
            raise TaskPlanJobShadowConflict("legacy Job observation collision")
        return existing
    finally:
        conn.close()
