"""Safe startup classification and recovery for persistent Runtime Runs."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path

from core.checkpoint_store import latest_checkpoint
from core.obsidian_runtime import (
    VerificationRetryUnavailable,
    retry_obsidian_verification,
)
from core.run_contract import (
    RunCheckpoint,
    RunRecord,
    RunState,
    VerificationStatus,
)
from core.run_store import (
    RunLedgerCorrupted,
    RunNotFound,
    get_verified_run,
    list_non_terminal_runs,
)
from core.step_store import (
    StepNotFound,
    StepStateConflict,
    StepVerificationRequired,
)

OBSIDIAN_SOURCE = "desktop.obsidian_write"
OBSIDIAN_VERIFICATION_ADAPTER = "obsidian_verification"
OBSIDIAN_CURSOR_VERSION = 1


class RecoveryClassification(StrEnum):
    RECOVERABLE = "recoverable"
    WAITING = "waiting"
    MANUAL = "manual"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class StartupRecoveryItem:
    run_id: str
    original_state: RunState
    classification: RecoveryClassification
    reason: str
    adapter: str | None = None
    checkpoint_id: str | None = None
    attempted: bool = False
    resulting_state: RunState | None = None
    verification_status: VerificationStatus | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["original_state"] = self.original_state.value
        payload["classification"] = self.classification.value
        if self.resulting_state is not None:
            payload["resulting_state"] = self.resulting_state.value
        if self.verification_status is not None:
            payload["verification_status"] = self.verification_status.value
        return payload


@dataclass(frozen=True, slots=True)
class StartupRecoveryReport:
    scanned_runs: tuple[RunRecord, ...]
    items: tuple[StartupRecoveryItem, ...]

    def to_dict(self) -> dict[str, object]:
        counts = {
            classification.value: sum(
                item.classification is classification for item in self.items
            )
            for classification in RecoveryClassification
        }
        return {
            "counts": counts,
            "items": [item.to_dict() for item in self.items],
        }


def _invalid(run: RunRecord, reason: str) -> StartupRecoveryItem:
    return StartupRecoveryItem(
        run_id=run.id,
        original_state=run.state,
        classification=RecoveryClassification.INVALID,
        reason=reason,
    )


def obsidian_resume_issue(
    run: RunRecord,
    checkpoint: RunCheckpoint | None,
) -> str | None:
    if run.source != OBSIDIAN_SOURCE or run.state is not RunState.UNCERTAIN:
        return "no_registered_resume_adapter"
    if checkpoint is None:
        return "checkpoint_missing"
    if checkpoint.step_id != run.current_step_id:
        return "checkpoint_step_mismatch"
    if checkpoint.resume_state is not RunState.VERIFYING:
        return "checkpoint_state_unsupported"
    if checkpoint.cursor_version != OBSIDIAN_CURSOR_VERSION:
        return "cursor_version_unsupported"
    if checkpoint.cursor.get("kind") != OBSIDIAN_VERIFICATION_ADAPTER:
        return "cursor_kind_unsupported"
    if not checkpoint.cursor.get("targetArtifactId"):
        return "cursor_target_missing"
    return None


def classify_startup_run(
    db_path: str | Path,
    snapshot: RunRecord,
) -> StartupRecoveryItem:
    try:
        run = get_verified_run(db_path, snapshot.id)
    except RunLedgerCorrupted:
        return _invalid(snapshot, "snapshot_or_ledger_invalid")
    if run is None:
        return _invalid(snapshot, "run_missing")
    if run.state is RunState.WAITING_USER:
        return StartupRecoveryItem(
            run.id,
            run.state,
            RecoveryClassification.WAITING,
            "waiting_for_user",
        )
    if run.state is RunState.WAITING_APPROVAL:
        return StartupRecoveryItem(
            run.id,
            run.state,
            RecoveryClassification.WAITING,
            "waiting_for_approval",
        )
    if run.state is not RunState.UNCERTAIN or run.source != OBSIDIAN_SOURCE:
        return StartupRecoveryItem(
            run.id,
            run.state,
            RecoveryClassification.MANUAL,
            "no_registered_startup_adapter",
        )
    checkpoint = latest_checkpoint(db_path, run.id)
    invalid_reason = obsidian_resume_issue(run, checkpoint)
    if invalid_reason is not None:
        return _invalid(run, invalid_reason)
    return StartupRecoveryItem(
        run.id,
        run.state,
        RecoveryClassification.RECOVERABLE,
        "adapter_ready",
        adapter=OBSIDIAN_VERIFICATION_ADAPTER,
        checkpoint_id=checkpoint.id if checkpoint else None,
    )


def _recover_obsidian_verification(
    db_path: str | Path,
    item: StartupRecoveryItem,
    *,
    now: str,
) -> StartupRecoveryItem:
    try:
        receipt = retry_obsidian_verification(db_path, item.run_id, now=now)
        run = get_verified_run(db_path, item.run_id)
    except (
        RunLedgerCorrupted,
        RunNotFound,
        StepNotFound,
        StepStateConflict,
        StepVerificationRequired,
        VerificationRetryUnavailable,
    ):
        return replace(
            item,
            classification=RecoveryClassification.INVALID,
            reason="adapter_rejected",
            attempted=True,
        )
    resulting_state = run.state if run is not None else None
    reason = (
        "recovered"
        if resulting_state is RunState.COMPLETED
        else "verification_did_not_complete"
    )
    return replace(
        item,
        reason=reason,
        attempted=True,
        resulting_state=resulting_state,
        verification_status=receipt.status,
    )


def coordinate_startup_recovery(
    db_path: str | Path,
    *,
    now: str,
) -> StartupRecoveryReport:
    report = inspect_startup_recovery(db_path)
    items: list[StartupRecoveryItem] = []
    for item in report.items:
        if item.classification is RecoveryClassification.RECOVERABLE:
            item = _recover_obsidian_verification(db_path, item, now=now)
        items.append(item)
    return StartupRecoveryReport(
        scanned_runs=report.scanned_runs,
        items=tuple(items),
    )


def inspect_startup_recovery(
    db_path: str | Path,
) -> StartupRecoveryReport:
    snapshots = tuple(list_non_terminal_runs(db_path))
    items = tuple(classify_startup_run(db_path, snapshot) for snapshot in snapshots)
    return StartupRecoveryReport(scanned_runs=snapshots, items=items)
