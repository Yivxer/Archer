from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from core.outcome_store import (
    InvalidVerificationReceipt,
    OutcomeLinkMismatch,
    get_artifact,
    list_verifications,
    record_artifact,
    record_verification,
)
from core.run_contract import (
    ArtifactRecord,
    RunRecord,
    StepRecord,
    StepState,
    VerificationReceipt,
    VerificationStatus,
)
from core.run_store import (
    StepVerificationRequired,
    create_run,
    create_step,
    list_events,
    transition_step,
)
from memory.migrations import run_migrations


def _artifact(step_id: str = "step-1") -> ArtifactRecord:
    return ArtifactRecord(
        id=f"artifact-{step_id}",
        run_id="run-1",
        step_id=step_id,
        kind="markdown",
        uri_or_path="/tmp/result.md",
        fingerprint="sha256:abc",
        media_type="text/markdown",
        created_by="obsidian_write",
    )


def _receipt(
    status: VerificationStatus = VerificationStatus.VERIFIED,
    *,
    evidence_refs: tuple[str, ...] = ("artifact-step-1",),
) -> VerificationReceipt:
    return VerificationReceipt(
        id=f"verification-{status.value}",
        run_id="run-1",
        step_id="step-1",
        verifier="markdown_fingerprint",
        status=status,
        criteria=("path_exists", "content_matches"),
        evidence_refs=evidence_refs,
        checked_at="2026-07-23T13:05:00+08:00",
        summary="verified independently",
    )


def _setup_verifying_step(db_path: Path) -> StepRecord:
    run_migrations(db_path)
    create_run(
        db_path,
        RunRecord(
            id="run-1",
            objective="验证写入结果",
            source="test",
            created_at="2026-07-23T13:00:00+08:00",
            updated_at="2026-07-23T13:00:00+08:00",
        ),
        event_id="event-1",
    )
    step = StepRecord(
        id="step-1",
        run_id="run-1",
        ordinal=1,
        title="写入并校验",
        kind="tool",
        success_criteria=("path_exists", "content_matches"),
    )
    create_step(
        db_path,
        step,
        event_id="event-2",
        created_at="2026-07-23T13:01:00+08:00",
    )
    current = step
    for event_id, target in (
        ("event-3", StepState.READY),
        ("event-4", StepState.RUNNING),
        ("event-5", StepState.VERIFYING),
    ):
        current = transition_step(
            db_path,
            step.id,
            target,
            expected_state=current.state,
            event_id=event_id,
            transitioned_at="2026-07-23T13:02:00+08:00",
        )
    return current


def test_artifact_and_verified_receipt_allow_step_completion(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    verifying = _setup_verifying_step(db_path)
    artifact = _artifact()
    receipt = _receipt()

    record_artifact(
        db_path,
        artifact,
        event_id="event-6",
        created_at="2026-07-23T13:04:00+08:00",
    )
    record_verification(db_path, receipt, event_id="event-7")
    completed = transition_step(
        db_path,
        "step-1",
        StepState.COMPLETED,
        expected_state=verifying.state,
        event_id="event-8",
        transitioned_at="2026-07-23T13:06:00+08:00",
    )

    assert get_artifact(db_path, artifact.id) == artifact
    assert list_verifications(db_path, "step-1") == [receipt]
    assert completed.state is StepState.COMPLETED
    assert len(list_events(db_path, "run-1")) == 8


def test_step_cannot_complete_without_verified_receipt(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    verifying = _setup_verifying_step(db_path)

    with pytest.raises(StepVerificationRequired, match="step-1"):
        transition_step(
            db_path,
            "step-1",
            StepState.COMPLETED,
            expected_state=verifying.state,
            event_id="event-6",
            transitioned_at="2026-07-23T13:06:00+08:00",
        )

    assert len(list_events(db_path, "run-1")) == 5


@pytest.mark.parametrize(
    "status",
    [VerificationStatus.FAILED, VerificationStatus.UNCERTAIN],
)
def test_non_verified_receipt_does_not_allow_completion(
    tmp_path: Path,
    status: VerificationStatus,
) -> None:
    db_path = tmp_path / "archer.db"
    verifying = _setup_verifying_step(db_path)
    record_artifact(
        db_path,
        _artifact(),
        event_id="event-6",
        created_at="2026-07-23T13:04:00+08:00",
    )
    record_verification(db_path, _receipt(status), event_id="event-7")

    with pytest.raises(StepVerificationRequired):
        transition_step(
            db_path,
            "step-1",
            StepState.COMPLETED,
            expected_state=verifying.state,
            event_id="event-8",
            transitioned_at="2026-07-23T13:06:00+08:00",
        )


def test_latest_uncertain_receipt_overrides_earlier_verified_receipt(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "archer.db"
    verifying = _setup_verifying_step(db_path)
    record_artifact(
        db_path,
        _artifact(),
        event_id="event-6",
        created_at="2026-07-23T13:04:00+08:00",
    )
    record_verification(db_path, _receipt(), event_id="event-7")
    uncertain = replace(
        _receipt(VerificationStatus.UNCERTAIN),
        checked_at="2026-07-23T13:06:00+08:00",
    )
    record_verification(db_path, uncertain, event_id="event-8")

    with pytest.raises(StepVerificationRequired, match="latest receipt"):
        transition_step(
            db_path,
            "step-1",
            StepState.COMPLETED,
            expected_state=verifying.state,
            event_id="event-9",
            transitioned_at="2026-07-23T13:07:00+08:00",
        )


def test_verified_receipt_requires_linked_artifact_and_criteria(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    _setup_verifying_step(db_path)

    with pytest.raises(InvalidVerificationReceipt, match="artifact evidence"):
        record_verification(
            db_path,
            _receipt(evidence_refs=()),
            event_id="event-6",
        )
    with pytest.raises(OutcomeLinkMismatch, match="artifact-step-1"):
        record_verification(db_path, _receipt(), event_id="event-7")

    assert list_verifications(db_path, "step-1") == []
    assert len(list_events(db_path, "run-1")) == 5


def test_duplicate_event_rolls_back_artifact_insert(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    _setup_verifying_step(db_path)
    artifact = _artifact()

    with pytest.raises(sqlite3.IntegrityError):
        record_artifact(
            db_path,
            artifact,
            event_id="event-1",
            created_at="2026-07-23T13:04:00+08:00",
        )

    assert get_artifact(db_path, artifact.id) is None
    assert len(list_events(db_path, "run-1")) == 5
