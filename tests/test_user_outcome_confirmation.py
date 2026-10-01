from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event

import pytest
from fastapi.testclient import TestClient

from core.outcome_store import list_artifacts, list_verifications, record_artifact
from core.run_contract import (
    ArtifactRecord,
    RunRecord,
    RunState,
    StepRecord,
    StepState,
    VerificationStatus,
)
from core.run_store import create_run, get_run, list_events, transition_run
from core.runtime_context import create_runtime_context
from core.step_store import create_step, get_step, transition_step
from core.user_outcome_confirmation import (
    UserOutcomeConfirmationConflict,
    UserOutcomeConfirmationUnavailable,
    confirm_user_outcome,
)
from memory.migrations import run_migrations
from terminal.api.fastapi_app import create_app

NOW = "2026-07-31T14:00:00+08:00"


def _setup(db_path):
    run_migrations(db_path)
    run = RunRecord(
        id="run-confirm-1",
        objective="deliver analysis",
        source="runtime.background_job",
        created_at=NOW,
        updated_at=NOW,
    )
    create_run(db_path, run, event_id="event-confirm-run-created")
    for target in (
        RunState.UNDERSTANDING,
        RunState.PLANNING,
        RunState.EXECUTING,
        RunState.VERIFYING,
    ):
        run = transition_run(
            db_path,
            run.id,
            target,
            expected_version=run.version,
            event_id=f"event-confirm-run-{target.value}",
            updated_at=NOW,
        )
    step = StepRecord(
        id="step-confirm-1",
        run_id=run.id,
        ordinal=1,
        title="produce analysis",
        kind="analysis",
        success_criteria=("user_confirmed",),
    )
    create_step(
        db_path,
        step,
        event_id="event-confirm-step-created",
        created_at=NOW,
    )
    for target in (StepState.READY, StepState.RUNNING, StepState.VERIFYING):
        step = transition_step(
            db_path,
            step.id,
            target,
            expected_state=step.state,
            event_id=f"event-confirm-step-{target.value}",
            transitioned_at=NOW,
        )
    artifact = ArtifactRecord(
        id="artifact-confirm-1",
        run_id=run.id,
        step_id=step.id,
        kind="analysis_result",
        uri_or_path="runtime://jobs/job-1/result",
        fingerprint="sha256-confirm-1",
        media_type="text/markdown",
        created_by="legacy.background_job.v1.shadow",
        metadata={"attemptId": "attempt-confirm-1"},
    )
    record_artifact(
        db_path,
        artifact,
        event_id="event-confirm-artifact",
        created_at=NOW,
    )
    return run, step, artifact


def _confirm(db_path, decision="accepted"):
    return confirm_user_outcome(
        db_path,
        run_id="run-confirm-1",
        step_id="step-confirm-1",
        attempt_id="attempt-confirm-1",
        artifact_id="artifact-confirm-1",
        artifact_fingerprint="sha256-confirm-1",
        decision=decision,
        confirmed_at=NOW,
    )


def test_acceptance_records_receipt_then_completes_and_replays(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    _setup(db_path)
    first = _confirm(db_path)
    event_count = len(list_events(db_path, "run-confirm-1"))
    replay = _confirm(db_path)

    assert first.receipt.status is VerificationStatus.VERIFIED
    assert first.run.state is RunState.COMPLETED
    assert first.step.state is StepState.COMPLETED
    assert replay.replayed is True
    assert replay.receipt == first.receipt
    assert len(list_events(db_path, "run-confirm-1")) == event_count
    assert len(list_verifications(db_path, "step-confirm-1")) == 1


def test_correction_preserves_artifact_and_returns_to_waiting_user(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    _setup(db_path)
    result = _confirm(db_path, decision="correction")

    assert result.receipt.status is VerificationStatus.FAILED
    assert result.receipt.error_code == "user_correction_requested"
    assert result.run.state is RunState.WAITING_USER
    assert result.step.state is StepState.WAITING_USER
    assert [item.id for item in list_artifacts(db_path, result.step.id)] == [
        "artifact-confirm-1"
    ]


def test_confirmation_rejects_stale_evidence_and_conflicting_decision(
    tmp_path,
) -> None:
    db_path = tmp_path / "archer.db"
    _setup(db_path)
    with pytest.raises(UserOutcomeConfirmationUnavailable, match="stale"):
        confirm_user_outcome(
            db_path,
            run_id="run-confirm-1",
            step_id="step-confirm-1",
            attempt_id="attempt-confirm-1",
            artifact_id="artifact-confirm-1",
            artifact_fingerprint="different",
            decision="accepted",
            confirmed_at=NOW,
        )
    _confirm(db_path)
    with pytest.raises(UserOutcomeConfirmationConflict, match="conflicts"):
        _confirm(db_path, decision="correction")


def test_concurrent_confirmation_replays_one_receipt_and_terminal_state(
    tmp_path,
) -> None:
    db_path = tmp_path / "archer.db"
    _setup(db_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _confirm(db_path), range(2)))

    assert sum(not item.replayed for item in results) == 1
    assert sum(item.replayed for item in results) == 1
    assert len(list_verifications(db_path, "step-confirm-1")) == 1
    assert get_run(db_path, "run-confirm-1").state is RunState.COMPLETED


@pytest.mark.parametrize("decision", ["accepted", "correction"])
def test_concurrent_confirmation_converges_after_step_before_run(
    tmp_path, monkeypatch, decision,
) -> None:
    """A losing Step CAS must converge the same receipt's partial completion."""
    import core.user_outcome_confirmation as confirmation

    db_path = tmp_path / "archer.db"
    _setup(db_path)
    winner_paused, loser_finished = Event(), Event()
    actual_step_transition = confirmation.transition_step

    def paused_transition(*args, **kwargs):
        step = actual_step_transition(*args, **kwargs)
        winner_paused.set()
        assert loser_finished.wait(5), "replay did not finish"
        return step

    monkeypatch.setattr(confirmation, "transition_step", paused_transition)
    with ThreadPoolExecutor(max_workers=1) as executor:
        winner = executor.submit(_confirm, db_path, decision)
        assert winner_paused.wait(5), "winner did not complete Step"
        # Replay with a deliberately stale verifying snapshot, as a second
        # request can read the Step immediately before the winner writes it.
        def stale_step_transition(*args, **kwargs):
            from core.step_store import StepStateConflict
            raise StepStateConflict("stale verifying snapshot")

        original_finish = confirmation._finish_confirmation

        def conflicting_finish(*args, **kwargs):
            monkeypatch.setattr(confirmation, "transition_step", stale_step_transition)
            from dataclasses import replace
            kwargs["step"] = replace(kwargs["step"], state=StepState.VERIFYING)
            try:
                return original_finish(*args, **kwargs)
            finally:
                monkeypatch.setattr(confirmation, "_finish_confirmation", original_finish)

        monkeypatch.setattr(confirmation, "_finish_confirmation", conflicting_finish)
        try:
            replay = _confirm(db_path, decision)
        finally:
            loser_finished.set()
        first = winner.result(timeout=5)
    assert replay.replayed and not first.replayed
    assert len(list_verifications(db_path, "step-confirm-1")) == 1
    expected_run = RunState.COMPLETED if decision == "accepted" else RunState.WAITING_USER
    expected_step = StepState.COMPLETED if decision == "accepted" else StepState.WAITING_USER
    assert replay.run.state is first.run.state is expected_run
    assert replay.step.state is first.step.state is expected_step


def test_partial_confirmation_does_not_override_concurrent_cancellation(tmp_path, monkeypatch) -> None:
    import core.user_outcome_confirmation as confirmation
    from core.step_store import StepStateConflict

    db_path = tmp_path / "archer.db"
    _setup(db_path)

    def cancellation_wins(*args, **kwargs):
        transition_step(
            db_path, "step-confirm-1", StepState.COMPLETED,
            expected_state=StepState.VERIFYING,
            event_id="event-partial-step", transitioned_at=NOW,
        )
        run = get_run(db_path, "run-confirm-1")
        for state in (RunState.CANCELLING, RunState.CANCELLED):
            run = transition_run(
                db_path, run.id, state, expected_version=run.version,
                event_id=f"event-concurrent-{state.value}", updated_at=NOW,
            )
        raise StepStateConflict("another request changed state")

    monkeypatch.setattr(confirmation, "_finish_confirmation", cancellation_wins)
    with pytest.raises(UserOutcomeConfirmationConflict):
        _confirm(db_path)
    assert get_run(db_path, "run-confirm-1").state is RunState.CANCELLED
    assert len(list_verifications(db_path, "step-confirm-1")) == 1


def test_outcome_confirmation_api_validates_and_returns_runtime_state(
    tmp_path,
) -> None:
    db_path = tmp_path / "archer.db"
    _setup(db_path)
    context = create_runtime_context(
        db_path=db_path,
        config={},
        clock=lambda: datetime.fromisoformat(NOW),
    )
    client = TestClient(create_app("test-token", runtime_context=context))
    headers = {"Authorization": "Bearer test-token"}

    invalid = client.post(
        "/runtime/runs/run-confirm-1/outcome-confirmation",
        json={"decision": "accepted"},
        headers=headers,
    )
    accepted = client.post(
        "/runtime/runs/run-confirm-1/outcome-confirmation",
        json={
            "stepId": "step-confirm-1",
            "attemptId": "attempt-confirm-1",
            "artifactId": "artifact-confirm-1",
            "artifactFingerprint": "sha256-confirm-1",
            "decision": "accepted",
        },
        headers=headers,
    )

    assert invalid.status_code == 400
    assert accepted.status_code == 200
    payload = accepted.json()["confirmation"]
    assert payload["run"]["state"] == "completed"
    assert payload["step"]["state"] == "completed"
    assert get_run(db_path, "run-confirm-1").state is RunState.COMPLETED
    assert get_step(db_path, "step-confirm-1").state is StepState.COMPLETED
