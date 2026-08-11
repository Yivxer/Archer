"""User-confirmed outcome verification for non-deterministic Runtime work."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.outcome_store import get_artifact, list_verifications, record_verification
from core.run_contract import (
    RunRecord,
    RunState,
    StepRecord,
    StepState,
    StopReason,
    VerificationReceipt,
    VerificationStatus,
)
from core.run_store import RunVersionConflict, get_run, transition_run
from core.step_store import StepStateConflict, get_step, transition_step

USER_CONFIRMATION_VERIFIER_ID = "user.confirmation.v1"
OutcomeDecision = Literal["accepted", "correction"]


class UserOutcomeConfirmationUnavailable(ValueError):
    """The requested confirmation is incomplete or does not target current evidence."""


class UserOutcomeConfirmationConflict(ValueError):
    """The confirmation identity was already used with another decision."""


@dataclass(frozen=True, slots=True)
class UserOutcomeConfirmation:
    decision: OutcomeDecision
    receipt: VerificationReceipt
    run: RunRecord
    step: StepRecord
    replayed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "receipt": self.receipt.to_dict(),
            "run": self.run.to_dict(),
            "step": self.step.to_dict(),
            "replayed": self.replayed,
        }


def _confirmation_id(
    run_id: str,
    step_id: str,
    attempt_id: str,
    artifact_id: str,
    artifact_fingerprint: str,
) -> str:
    material = "\0".join((
        USER_CONFIRMATION_VERIFIER_ID,
        run_id,
        step_id,
        attempt_id,
        artifact_id,
        artifact_fingerprint,
    ))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"user-outcome-confirmation-{digest}"


def _require_binding(
    db_path: str | Path,
    *,
    run_id: str,
    step_id: str,
    attempt_id: str,
    artifact_id: str,
    artifact_fingerprint: str,
) -> tuple[RunRecord, StepRecord]:
    run = get_run(db_path, run_id)
    step = get_step(db_path, step_id)
    artifact = get_artifact(db_path, artifact_id)
    if run is None or step is None or artifact is None:
        raise UserOutcomeConfirmationUnavailable("confirmation target does not exist")
    if step.run_id != run_id or artifact.run_id != run_id:
        raise UserOutcomeConfirmationUnavailable("confirmation target Run mismatch")
    if artifact.step_id != step_id or artifact.fingerprint != artifact_fingerprint:
        raise UserOutcomeConfirmationUnavailable("confirmation Artifact is stale")
    if str(artifact.metadata.get("attemptId", "")) != attempt_id:
        raise UserOutcomeConfirmationUnavailable("confirmation attempt is stale")
    if run.state not in {RunState.VERIFYING, RunState.UNCERTAIN, RunState.COMPLETED}:
        raise UserOutcomeConfirmationUnavailable(
            f"Run cannot accept outcome confirmation from {run.state.value}"
        )
    if step.state not in {
        StepState.VERIFYING,
        StepState.WAITING_USER,
        StepState.COMPLETED,
    }:
        raise UserOutcomeConfirmationUnavailable(
            f"Step cannot accept outcome confirmation from {step.state.value}"
        )
    return run, step


def _receipt(
    *,
    receipt_id: str,
    run_id: str,
    step: StepRecord,
    artifact_id: str,
    decision: OutcomeDecision,
    confirmed_at: str,
) -> VerificationReceipt:
    accepted = decision == "accepted"
    return VerificationReceipt(
        id=receipt_id,
        run_id=run_id,
        step_id=step.id,
        verifier=USER_CONFIRMATION_VERIFIER_ID,
        status=(
            VerificationStatus.VERIFIED
            if accepted
            else VerificationStatus.FAILED
        ),
        criteria=tuple(dict.fromkeys((*step.success_criteria, "user_confirmed"))),
        evidence_refs=(artifact_id,),
        checked_at=confirmed_at,
        error_code=None if accepted else "user_correction_requested",
        summary=(
            "user accepted current outcome"
            if accepted
            else "user requested outcome correction"
        ),
    )


def _existing_confirmation(
    db_path: str | Path,
    step_id: str,
    requested: VerificationReceipt,
) -> VerificationReceipt | None:
    existing = next(
        (
            item for item in list_verifications(db_path, step_id)
            if item.id == requested.id
        ),
        None,
    )
    if existing is None:
        return None
    if (
        existing.verifier,
        existing.status,
        existing.criteria,
        existing.evidence_refs,
        existing.error_code,
        existing.summary,
    ) != (
        requested.verifier,
        requested.status,
        requested.criteria,
        requested.evidence_refs,
        requested.error_code,
        requested.summary,
    ):
        raise UserOutcomeConfirmationConflict(
            "outcome confirmation decision conflicts with existing receipt"
        )
    return existing


def _finish_confirmation(
    db_path: str | Path,
    *,
    decision: OutcomeDecision,
    run: RunRecord,
    step: StepRecord,
    confirmed_at: str,
) -> tuple[RunRecord, StepRecord]:
    if decision == "accepted":
        if step.state is StepState.VERIFYING:
            step = transition_step(
                db_path,
                step.id,
                StepState.COMPLETED,
                expected_state=step.state,
                event_id=f"event-{step.id}-user-confirmed-completed",
                transitioned_at=confirmed_at,
            )
        if run.state in {RunState.VERIFYING, RunState.UNCERTAIN}:
            if run.state is RunState.UNCERTAIN:
                run = transition_run(
                    db_path,
                    run.id,
                    RunState.VERIFYING,
                    expected_version=run.version,
                    event_id=f"event-{run.id}-user-confirmed-verifying",
                    updated_at=confirmed_at,
                )
            run = transition_run(
                db_path,
                run.id,
                RunState.COMPLETED,
                expected_version=run.version,
                event_id=f"event-{run.id}-user-confirmed-completed",
                updated_at=confirmed_at,
                stop_reason=StopReason.GOAL_SATISFIED,
            )
        return run, step

    if step.state is StepState.VERIFYING:
        step = transition_step(
            db_path,
            step.id,
            StepState.WAITING_USER,
            expected_state=step.state,
            event_id=f"event-{step.id}-user-correction-waiting",
            transitioned_at=confirmed_at,
        )
    if run.state in {RunState.VERIFYING, RunState.UNCERTAIN}:
        run = transition_run(
            db_path,
            run.id,
            RunState.WAITING_USER,
            expected_version=run.version,
            event_id=f"event-{run.id}-user-correction-waiting",
            updated_at=confirmed_at,
            stop_reason=StopReason.USER_INPUT_REQUIRED,
        )
    return run, step


def confirm_user_outcome(
    db_path: str | Path,
    *,
    run_id: str,
    step_id: str,
    attempt_id: str,
    artifact_id: str,
    artifact_fingerprint: str,
    decision: OutcomeDecision,
    confirmed_at: str,
) -> UserOutcomeConfirmation:
    if decision not in {"accepted", "correction"}:
        raise UserOutcomeConfirmationUnavailable("unsupported outcome decision")
    if not all((
        run_id.strip(),
        step_id.strip(),
        attempt_id.strip(),
        artifact_id.strip(),
        artifact_fingerprint.strip(),
        confirmed_at.strip(),
    )):
        raise UserOutcomeConfirmationUnavailable(
            "outcome confirmation fields must not be empty"
        )
    run, step = _require_binding(
        db_path,
        run_id=run_id,
        step_id=step_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        artifact_fingerprint=artifact_fingerprint,
    )
    requested = _receipt(
        receipt_id=_confirmation_id(
            run_id,
            step_id,
            attempt_id,
            artifact_id,
            artifact_fingerprint,
        ),
        run_id=run_id,
        step=step,
        artifact_id=artifact_id,
        decision=decision,
        confirmed_at=confirmed_at,
    )
    existing = _existing_confirmation(db_path, step_id, requested)
    if existing is None:
        try:
            record_verification(
                db_path,
                requested,
                event_id=f"event-{requested.id}",
            )
        except sqlite3.IntegrityError:
            existing = _existing_confirmation(db_path, step_id, requested)
            if existing is None:
                raise
    current_run = get_run(db_path, run_id)
    current_step = get_step(db_path, step_id)
    if current_run is None or current_step is None:
        raise UserOutcomeConfirmationUnavailable("confirmation target disappeared")
    try:
        run, step = _finish_confirmation(
            db_path,
            decision=decision,
            run=current_run,
            step=current_step,
            confirmed_at=confirmed_at,
        )
    except (RunVersionConflict, StepStateConflict) as exc:
        run = get_run(db_path, run_id)
        step = get_step(db_path, step_id)
        expected = (
            (RunState.COMPLETED, StepState.COMPLETED)
            if decision == "accepted"
            else (RunState.WAITING_USER, StepState.WAITING_USER)
        )
        if run is None or step is None or (run.state, step.state) != expected:
            raise UserOutcomeConfirmationConflict(
                "outcome confirmation state changed concurrently"
            ) from exc
    return UserOutcomeConfirmation(
        decision=decision,
        receipt=existing or requested,
        run=run,
        step=step,
        replayed=existing is not None,
    )
