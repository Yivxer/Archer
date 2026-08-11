"""Stable domain contracts for Archer's unified run lifecycle.

This module is intentionally independent from persistence, FastAPI, Desktop,
jobs, and tool execution. Early Runtime Closure slices can depend on these
types without moving an existing production path behind the new runtime.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

RUN_CONTRACT_VERSION = 1


class RunState(StrEnum):
    RECEIVED = "received"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    WAITING_USER = "waiting_user"
    WAITING_APPROVAL = "waiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    UNCERTAIN = "uncertain"
    INTERRUPTED = "interrupted"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepState(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    WAITING_APPROVAL = "waiting_approval"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class RunEventType(StrEnum):
    RUN_RECEIVED = "run.received"
    RUN_STATE_CHANGED = "run.state_changed"
    CHECKPOINT_RECORDED = "checkpoint.recorded"
    STEP_CREATED = "step.created"
    STEP_STATE_CHANGED = "step.state_changed"
    ARTIFACT_RECORDED = "artifact.recorded"
    VERIFICATION_RECORDED = "verification.recorded"


class StopReason(StrEnum):
    GOAL_SATISFIED = "goal_satisfied"
    USER_CANCELLED = "user_cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    POLICY_DENIED = "policy_denied"
    VERIFICATION_FAILED = "verification_failed"
    VERIFICATION_UNCERTAIN = "verification_uncertain"
    EXECUTOR_FAILED = "executor_failed"
    TIMEOUT = "timeout"
    DEPENDENCY_FAILED = "dependency_failed"
    USER_INPUT_REQUIRED = "user_input_required"
    APPLICATION_INTERRUPTED = "application_interrupted"


TERMINAL_RUN_STATES = frozenset(
    {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
)
TERMINAL_STEP_STATES = frozenset(
    {StepState.COMPLETED, StepState.FAILED, StepState.SKIPPED, StepState.CANCELLED}
)


RUN_STATE_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.RECEIVED: frozenset(
        {RunState.UNDERSTANDING, RunState.CANCELLING, RunState.FAILED}
    ),
    RunState.UNDERSTANDING: frozenset(
        {
            RunState.PLANNING,
            RunState.WAITING_USER,
            RunState.CANCELLING,
            RunState.FAILED,
        }
    ),
    RunState.PLANNING: frozenset(
        {
            RunState.WAITING_USER,
            RunState.WAITING_APPROVAL,
            RunState.EXECUTING,
            RunState.CANCELLING,
            RunState.FAILED,
        }
    ),
    RunState.WAITING_USER: frozenset(
        {
            RunState.PLANNING,
            RunState.EXECUTING,
            RunState.CANCELLING,
            RunState.FAILED,
        }
    ),
    RunState.WAITING_APPROVAL: frozenset(
        {
            RunState.EXECUTING,
            RunState.CANCELLING,
            RunState.FAILED,
        }
    ),
    RunState.EXECUTING: frozenset(
        {
            RunState.WAITING_USER,
            RunState.WAITING_APPROVAL,
            RunState.VERIFYING,
            RunState.INTERRUPTED,
            RunState.CANCELLING,
            RunState.FAILED,
        }
    ),
    RunState.VERIFYING: frozenset(
        {
            RunState.EXECUTING,
            RunState.WAITING_USER,
            RunState.COMPLETED,
            RunState.UNCERTAIN,
            RunState.CANCELLING,
            RunState.FAILED,
        }
    ),
    RunState.UNCERTAIN: frozenset(
        {
            RunState.VERIFYING,
            RunState.WAITING_USER,
            RunState.CANCELLING,
            RunState.FAILED,
        }
    ),
    RunState.INTERRUPTED: frozenset(
        {
            RunState.PLANNING,
            RunState.EXECUTING,
            RunState.VERIFYING,
            RunState.CANCELLING,
            RunState.FAILED,
        }
    ),
    RunState.CANCELLING: frozenset(
        {RunState.CANCELLED, RunState.UNCERTAIN, RunState.FAILED}
    ),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


STEP_STATE_TRANSITIONS: dict[StepState, frozenset[StepState]] = {
    StepState.PENDING: frozenset(
        {StepState.READY, StepState.SKIPPED, StepState.CANCELLED}
    ),
    StepState.READY: frozenset(
        {
            StepState.RUNNING,
            StepState.WAITING_APPROVAL,
            StepState.SKIPPED,
            StepState.CANCELLED,
        }
    ),
    StepState.RUNNING: frozenset(
        {
            StepState.WAITING_APPROVAL,
            StepState.WAITING_USER,
            StepState.VERIFYING,
            StepState.FAILED,
            StepState.CANCELLED,
        }
    ),
    StepState.WAITING_USER: frozenset(
        {StepState.RUNNING, StepState.CANCELLED}
    ),
    StepState.WAITING_APPROVAL: frozenset(
        {StepState.RUNNING, StepState.FAILED, StepState.CANCELLED}
    ),
    StepState.VERIFYING: frozenset(
        {
            StepState.RUNNING,
            StepState.WAITING_USER,
            StepState.COMPLETED,
            StepState.FAILED,
            StepState.CANCELLED,
        }
    ),
    StepState.COMPLETED: frozenset(),
    StepState.FAILED: frozenset(),
    StepState.SKIPPED: frozenset(),
    StepState.CANCELLED: frozenset(),
}


class InvalidRunTransition(ValueError):
    """Raised when a caller attempts an illegal run state transition."""


class InvalidStepTransition(ValueError):
    """Raised when a caller attempts an illegal step state transition."""


def require_run_transition(current: RunState, target: RunState) -> None:
    if target not in RUN_STATE_TRANSITIONS[current]:
        raise InvalidRunTransition(f"invalid run transition: {current.value} -> {target.value}")


def require_step_transition(current: StepState, target: StepState) -> None:
    if target not in STEP_STATE_TRANSITIONS[current]:
        raise InvalidStepTransition(
            f"invalid step transition: {current.value} -> {target.value}"
        )


@dataclass(frozen=True)
class RunBudget:
    max_steps: int = 20
    max_tool_calls: int = 20
    max_attempts_per_step: int = 3
    timeout_seconds: int = 600
    token_budget: int | None = None


@dataclass(frozen=True)
class RunRecord:
    id: str
    objective: str
    source: str
    state: RunState = RunState.RECEIVED
    stop_reason: StopReason | None = None
    current_step_id: str | None = None
    session_id: str | None = None
    thread_id: str | None = None
    parent_run_id: str | None = None
    context_receipt_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
    version: int = 1
    contract_version: int = RUN_CONTRACT_VERSION
    budget: RunBudget = field(default_factory=RunBudget)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state"] = self.state.value
        payload["stop_reason"] = (
            self.stop_reason.value if self.stop_reason is not None else None
        )
        return payload


@dataclass(frozen=True)
class StepRecord:
    id: str
    run_id: str
    ordinal: int
    title: str
    kind: str
    state: StepState = StepState.PENDING
    depends_on: tuple[str, ...] = ()
    capability: str | None = None
    requires_approval: bool = False
    success_criteria: tuple[str, ...] = ()
    attempt_count: int = 0
    max_attempts: int = 3
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    error_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state"] = self.state.value
        payload["depends_on"] = list(self.depends_on)
        payload["success_criteria"] = list(self.success_criteria)
        return payload


@dataclass(frozen=True)
class ArtifactRecord:
    id: str
    run_id: str
    step_id: str
    kind: str
    uri_or_path: str
    fingerprint: str
    media_type: str
    created_by: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationReceipt:
    id: str
    run_id: str
    step_id: str
    verifier: str
    status: VerificationStatus
    criteria: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    tool_call_id: str | None = None
    checked_at: str = ""
    error_code: str | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["criteria"] = list(self.criteria)
        payload["evidence_refs"] = list(self.evidence_refs)
        return payload


@dataclass(frozen=True)
class RunCheckpoint:
    id: str
    run_id: str
    resume_state: RunState
    cursor: dict[str, Any]
    created_at: str
    step_id: str | None = None
    cursor_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resume_state"] = self.resume_state.value
        return payload


@dataclass(frozen=True)
class RunEventRecord:
    id: str
    run_id: str
    sequence: int
    event_type: RunEventType
    created_at: str
    step_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event_type"] = self.event_type.value
        return payload
