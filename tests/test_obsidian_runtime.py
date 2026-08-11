from __future__ import annotations

import threading
from datetime import UTC, datetime, timezone
from pathlib import Path

import pytest

from core.checkpoint_store import latest_checkpoint
from core.obsidian_runtime import (
    ApprovalFingerprintMismatch,
    ObsidianRuntimeBinding,
    begin_approved_write,
    cancel_write,
    request_write_cancellation,
    retry_obsidian_verification,
    stage_obsidian_write,
)
from core.outcome_store import get_artifact, list_artifacts, list_verifications
from core.run_contract import RunRecord, RunState, StepRecord, StepState, VerificationStatus
from core.run_store import create_run, get_run, transition_run
from core.runtime_context import create_runtime_context
from core.step_store import create_step, get_step, transition_step
from memory.migrations import run_migrations
from skills import obsidian_write
from terminal.api._config import set_tool_draft, tool_request_fingerprint
from terminal.api.obsidian_runtime_bridge import (
    begin_runtime_approval,
    finalize_runtime_execution,
)
from terminal.api.tool_approval_routes import _retry_tool_outbox, _tool_approval
from terminal.api.tool_stage import ApprovalExecution

NOW = "2026-07-24T10:00:00+00:00"


def _patch_vault(monkeypatch: pytest.MonkeyPatch, vault: Path) -> None:
    from skills import _vault

    monkeypatch.setattr(_vault, "read_vault_path", lambda: vault)
    monkeypatch.setattr(_vault, "resolve_vault", lambda: vault)


def _args(path: str, content: str, preview: dict) -> dict:
    return {
        "path": path,
        "content": content,
        "mode": "overwrite",
        "expected_mtime": preview["mtime"],
        "expected_size": preview["size"],
        "expected_fingerprint": preview["fingerprint"],
        "expected_exists": preview["exists"],
    }


def _stage(db_path: Path, args: dict):
    fingerprint = tool_request_fingerprint("obsidian_write", args)
    binding = stage_obsidian_write(
        db_path,
        objective="受控写入测试笔记",
        approval_fingerprint=fingerprint,
        now=NOW,
        trace_id="trace-1",
    )
    return binding, fingerprint


def _runtime_context(db_path: Path):
    clock = lambda: datetime(2026, 7, 24, 10, tzinfo=UTC)
    return create_runtime_context(db_path=db_path, clock=clock)


def test_denied_write_has_zero_side_effect_and_cancels_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)
    note = vault / "note.md"
    note.write_text("original", encoding="utf-8")
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    preview = obsidian_write.compute_preview(
        {"path": "note.md", "content": "replacement", "mode": "overwrite"}
    )
    binding, _ = _stage(db_path, _args("note.md", "replacement", preview))

    cancel_write(db_path, binding, now=NOW)

    assert note.read_text(encoding="utf-8") == "original"
    assert get_run(db_path, binding.run_id).state is RunState.CANCELLED
    assert get_step(db_path, binding.step_id).state is StepState.CANCELLED


def test_approval_fingerprint_mismatch_fails_before_write(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    args = {"path": "note.md", "content": "safe"}
    binding, _ = _stage(db_path, args)
    draft = {
        "skillName": "obsidian_write",
        "args": args,
        "runtimeContract": binding.to_dict(),
    }

    with pytest.raises(ApprovalFingerprintMismatch):
        begin_runtime_approval(
            draft,
            fingerprint="different",
            runtime_context=_runtime_context(db_path),
        )

    assert get_run(db_path, binding.run_id).state is RunState.FAILED
    assert get_step(db_path, binding.step_id).state is StepState.FAILED
    receipt = list_verifications(db_path, binding.step_id)[0]
    assert receipt.error_code == "approval_fingerprint_mismatch"


def test_begin_approved_write_rejects_mixed_run_step_binding(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    first, first_fingerprint = _stage(db_path, {"path": "first.md"})
    second, _ = _stage(db_path, {"path": "second.md"})
    mixed = type(first)(
        run_id=first.run_id,
        step_id=second.step_id,
        approval_fingerprint=first_fingerprint,
        trace_id=first.trace_id,
    )

    with pytest.raises(ValueError, match="runtime binding"):
        begin_approved_write(
            db_path,
            mixed,
            actual_fingerprint=first_fingerprint,
            now=NOW,
        )

    assert get_run(db_path, first.run_id).state is RunState.WAITING_APPROVAL
    assert get_step(db_path, second.step_id).state is StepState.WAITING_APPROVAL


def test_begin_approved_write_rejects_stale_lifecycle_binding(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run = RunRecord(
        id="run-stale-lifecycle",
        objective="stale approval",
        source="desktop.obsidian_write",
        current_step_id="step-stale-lifecycle",
        context_receipt_id="fingerprint-stale",
        created_at=NOW,
        updated_at=NOW,
    )
    create_run(db_path, run, event_id="event-stale-run")
    step = StepRecord(
        id="step-stale-lifecycle",
        run_id=run.id,
        ordinal=1,
        title="stale write",
        kind="tool",
        capability="obsidian_write",
        requires_approval=True,
    )
    create_step(db_path, step, event_id="event-stale-step", created_at=NOW)
    run = transition_run(
        db_path,
        run.id,
        RunState.UNDERSTANDING,
        expected_version=run.version,
        event_id="event-stale-understanding",
        updated_at=NOW,
    )
    transition_run(
        db_path,
        run.id,
        RunState.PLANNING,
        expected_version=run.version,
        event_id="event-stale-planning",
        updated_at=NOW,
    )
    transition_step(
        db_path,
        step.id,
        StepState.READY,
        expected_state=StepState.PENDING,
        event_id="event-stale-ready",
        transitioned_at=NOW,
    )
    binding = ObsidianRuntimeBinding(
        run_id=run.id,
        step_id=step.id,
        approval_fingerprint="fingerprint-stale",
    )

    with pytest.raises(ValueError, match="runtime binding"):
        begin_approved_write(
            db_path,
            binding,
            actual_fingerprint="fingerprint-stale",
            now=NOW,
        )

    assert get_run(db_path, run.id).state is RunState.PLANNING
    assert get_step(db_path, step.id).state is StepState.READY


def test_prewrite_conflict_does_not_overwrite_and_records_failed_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)
    note = vault / "note.md"
    note.write_text("original", encoding="utf-8")
    preview = obsidian_write.compute_preview(
        {"path": "note.md", "content": "replacement", "mode": "overwrite"}
    )
    args = _args("note.md", "replacement", preview)
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding, fingerprint = _stage(db_path, args)
    draft = {
        "skillName": "obsidian_write",
        "args": args,
        "runtimeContract": binding.to_dict(),
    }
    context = _runtime_context(db_path)
    begin_runtime_approval(draft, fingerprint=fingerprint, runtime_context=context)
    note.write_text("external edit", encoding="utf-8")
    result = obsidian_write.run_structured(args)
    execution = ApprovalExecution(
        False,
        result["output"],
        result["summary"],
        None,
        result,
    )

    receipt = finalize_runtime_execution(
        draft,
        execution,
        fingerprint=fingerprint,
        event_id="tool-1",
        runtime_context=context,
    )

    assert receipt is None
    assert note.read_text(encoding="utf-8") == "external edit"
    assert get_run(db_path, binding.run_id).state is RunState.FAILED
    assert get_step(db_path, binding.step_id).state is StepState.FAILED
    verification = list_verifications(db_path, binding.step_id)[0]
    assert verification.status is VerificationStatus.FAILED
    assert verification.error_code == "prewrite_conflict"


def test_successful_write_records_artifact_receipt_and_completes_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)
    note = vault / "note.md"
    note.write_text("original", encoding="utf-8")
    preview = obsidian_write.compute_preview(
        {"path": "note.md", "content": "replacement", "mode": "overwrite"}
    )
    args = _args("note.md", "replacement", preview)
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding, fingerprint = _stage(db_path, args)
    draft = {
        "skillName": "obsidian_write",
        "args": args,
        "runtimeContract": binding.to_dict(),
    }
    context = _runtime_context(db_path)
    begin_runtime_approval(draft, fingerprint=fingerprint, runtime_context=context)
    result = obsidian_write.run_structured(args)
    execution = ApprovalExecution(
        True,
        result["output"],
        result["summary"],
        result["metadata"]["workReceipt"],
        result,
    )

    receipt = finalize_runtime_execution(
        draft,
        execution,
        fingerprint=fingerprint,
        event_id="tool-1",
        runtime_context=context,
    )

    assert note.read_text(encoding="utf-8") == "replacement"
    assert receipt and receipt["status"] == "verified"
    artifact = get_artifact(db_path, receipt["evidence_refs"][0])
    assert artifact and artifact.uri_or_path == str(note)
    assert artifact.metadata["approvalFingerprint"] == fingerprint
    assert get_step(db_path, binding.step_id).state is StepState.COMPLETED
    assert get_run(db_path, binding.run_id).state is RunState.COMPLETED


def test_tool_approval_route_returns_bound_runtime_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.api_tool_service import make_tool_request
    from skills.loader import load_skills
    from terminal.api._config import _load_config

    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)
    note = vault / "note.md"
    note.write_text("original", encoding="utf-8")
    preview = obsidian_write.compute_preview(
        {"path": "note.md", "content": "replacement", "mode": "overwrite"}
    )
    args = _args("note.md", "replacement", preview)
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding, fingerprint = _stage(db_path, args)
    event_id = "obsidian-runtime-route"
    loaded_skills = load_skills()
    request = make_tool_request(
        "obsidian_write",
        args,
        loaded_skills,
        cfg=_load_config(),
        event_id=event_id,
        force_approval=True,
    )
    request["approvalFingerprint"] = fingerprint
    request["runtimeContract"] = binding.to_dict()
    set_tool_draft(event_id, request)

    response = _tool_approval(
        {"eventId": event_id, "decision": "approved"},
        _runtime_context(db_path),
    )

    assert response["executed"] is True
    assert response["fingerprint"] == fingerprint
    assert response["runtimeContract"]["runId"] == binding.run_id
    assert response["verificationReceipt"]["status"] == "verified"
    assert response["workReceipt"]["target"] == str(note)
    assert note.read_text(encoding="utf-8") == "replacement"


def test_tool_approval_route_serializes_runtime_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from core.api_tool_service import make_tool_request
    from core.runtime_cancellation import CancellationToken
    from skills.loader import load_skills
    from terminal.api._config import _load_config

    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)
    note = vault / "note.md"
    note.write_text("original", encoding="utf-8")
    preview = obsidian_write.compute_preview(
        {"path": "note.md", "content": "replacement", "mode": "overwrite"}
    )
    args = _args("note.md", "replacement", preview)
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding, fingerprint = _stage(db_path, args)
    event_id = "obsidian-runtime-finalization-guard"
    request = make_tool_request(
        "obsidian_write",
        args,
        load_skills(),
        cfg=_load_config(),
        event_id=event_id,
        force_approval=True,
    )
    request["approvalFingerprint"] = fingerprint
    request["runtimeContract"] = binding.to_dict()
    set_tool_draft(event_id, request)
    original_guard = CancellationToken.finalization_guard
    entered = False

    @contextmanager
    def observed_guard(token: CancellationToken):
        nonlocal entered
        entered = True
        with original_guard(token) as requested:
            yield requested

    monkeypatch.setattr(CancellationToken, "finalization_guard", observed_guard)

    response = _tool_approval(
        {"eventId": event_id, "decision": "approved"},
        _runtime_context(db_path),
    )

    assert entered is True
    assert response["verificationReceipt"]["status"] == "verified"
    assert get_run(db_path, binding.run_id).state is RunState.COMPLETED


def test_uncertain_verification_can_retry_without_rewriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)
    note = vault / "note.md"
    note.write_text("original", encoding="utf-8")
    preview = obsidian_write.compute_preview(
        {"path": "note.md", "content": "replacement", "mode": "overwrite"}
    )
    args = _args("note.md", "replacement", preview)
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding, fingerprint = _stage(db_path, args)
    draft = {
        "skillName": "obsidian_write",
        "args": args,
        "runtimeContract": binding.to_dict(),
    }
    context = _runtime_context(db_path)
    begin_runtime_approval(draft, fingerprint=fingerprint, runtime_context=context)
    result = obsidian_write.run_structured(args)
    execution = ApprovalExecution(
        True,
        result["output"],
        result["summary"],
        result["metadata"]["workReceipt"],
        result,
    )
    from core import obsidian_runtime

    original_match = obsidian_runtime._content_matches
    monkeypatch.setattr(
        obsidian_runtime,
        "_content_matches",
        lambda path, payload: (_ for _ in ()).throw(OSError("reader busy")),
    )
    uncertain = finalize_runtime_execution(
        draft,
        execution,
        fingerprint=fingerprint,
        event_id="tool-uncertain",
        runtime_context=context,
    )
    monkeypatch.setattr(obsidian_runtime, "_content_matches", original_match)
    monkeypatch.setattr(
        obsidian_write,
        "run_structured",
        lambda payload: (_ for _ in ()).throw(AssertionError("must not rewrite")),
    )

    retried = retry_obsidian_verification(
        db_path,
        binding.run_id,
        now="2026-07-24T10:05:00+00:00",
    )

    assert uncertain and uncertain["status"] == "uncertain"
    checkpoint = latest_checkpoint(db_path, binding.run_id)
    assert checkpoint and checkpoint.resume_state is RunState.VERIFYING
    assert checkpoint.cursor["kind"] == "obsidian_verification"
    assert retried.status is VerificationStatus.VERIFIED
    assert note.read_text(encoding="utf-8") == "replacement"
    assert get_run(db_path, binding.run_id).state is RunState.COMPLETED
    assert get_step(db_path, binding.step_id).state is StepState.COMPLETED
    assert [item.status for item in list_verifications(db_path, binding.step_id)] == [
        VerificationStatus.UNCERTAIN,
        VerificationStatus.VERIFIED,
    ]
    assert [item.kind for item in list_artifacts(db_path, binding.step_id)] == [
        "obsidian_verification_target",
        "obsidian_markdown",
    ]


def test_cancellation_during_write_suppresses_late_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.api_tool_service import make_tool_request
    from skills.loader import load_skills
    from terminal.api._config import _load_config

    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)
    note = vault / "note.md"
    note.write_text("original", encoding="utf-8")
    preview = obsidian_write.compute_preview(
        {"path": "note.md", "content": "replacement", "mode": "overwrite"}
    )
    args = _args("note.md", "replacement", preview)
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding, fingerprint = _stage(db_path, args)
    event_id = "obsidian-runtime-late-cancel"
    loaded_skills = load_skills()
    request = make_tool_request(
        "obsidian_write",
        args,
        loaded_skills,
        cfg=_load_config(),
        event_id=event_id,
        force_approval=True,
    )
    request["approvalFingerprint"] = fingerprint
    request["runtimeContract"] = binding.to_dict()
    set_tool_draft(event_id, request)
    entered = threading.Event()
    release = threading.Event()

    def slow_write(_args: dict) -> str:
        entered.set()
        assert release.wait(timeout=2)
        note.write_text("replacement", encoding="utf-8")
        return "已覆盖写入：note.md（原 1 行）"

    runtime_skill = loaded_skills["obsidian_write"]
    monkeypatch.setattr(runtime_skill, "_run_unchecked", slow_write)
    context = _runtime_context(db_path)
    responses: list[dict] = []
    errors: list[BaseException] = []

    def approve() -> None:
        try:
            responses.append(
                _tool_approval(
                    {"eventId": event_id, "decision": "approved"},
                    context,
                )
            )
        except BaseException as exc:
            errors.append(exc)
            entered.set()

    worker = threading.Thread(
        target=approve
    )
    worker.start()
    assert entered.wait(timeout=5)
    assert errors == []

    cancelling = request_write_cancellation(
        db_path,
        binding.run_id,
        context.cancellations,
        now="2026-07-24T10:04:00+00:00",
    )
    release.set()
    worker.join(timeout=3)

    assert cancelling.state is RunState.CANCELLING
    assert responses[0]["executed"] is False
    assert responses[0]["lateResultSuppressed"] is True
    assert responses[0]["verificationReceipt"]["status"] == "uncertain"
    assert note.read_text(encoding="utf-8") == "replacement"
    assert get_run(db_path, binding.run_id).state is RunState.UNCERTAIN
    assert get_step(db_path, binding.step_id).state is StepState.VERIFYING


def test_outbox_retry_refuses_cancelled_runtime_without_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infrastructure.outbox import (
        approve,
        claim_for_sending,
        enqueue,
        get_item,
        mark_failed,
    )

    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)
    note = vault / "note.md"
    note.write_text("original", encoding="utf-8")
    preview = obsidian_write.compute_preview(
        {"path": "note.md", "content": "replacement", "mode": "overwrite"}
    )
    args = _args("note.md", "replacement", preview)
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding, fingerprint = _stage(db_path, args)
    draft = {
        "kind": "tool_request",
        "skillName": "obsidian_write",
        "args": args,
        "approvalFingerprint": fingerprint,
        "runtimeContract": binding.to_dict(),
    }
    context = _runtime_context(db_path)
    item = enqueue(
        db_path,
        kind="tool.execute",
        payload={"draft": draft},
        idempotency_key=f"tool:{fingerprint}",
        now=context.now(),
    )
    approve(db_path, item["id"], now=context.now())
    claim_for_sending(db_path, item["id"], now=context.now())
    mark_failed(db_path, item["id"], "forced retry", now=context.now())
    request_write_cancellation(
        db_path,
        binding.run_id,
        context.cancellations,
        now="2026-07-24T10:01:00+00:00",
    )
    calls = 0
    original_run = obsidian_write._run_unchecked

    def counted_run(payload: dict) -> str:
        nonlocal calls
        calls += 1
        return original_run(payload)

    monkeypatch.setattr(obsidian_write, "_run_unchecked", counted_run)

    response = _retry_tool_outbox(item["id"], context)

    assert response["ok"] is False
    assert calls == 0
    assert note.read_text(encoding="utf-8") == "original"
    assert get_run(db_path, binding.run_id).state is RunState.CANCELLED
    assert get_step(db_path, binding.step_id).state is StepState.CANCELLED
    assert list_artifacts(db_path, binding.step_id) == []
    assert list_verifications(db_path, binding.step_id) == []
    assert get_item(db_path, item["id"])["status"] == "failed"


def test_normal_approval_begin_failure_releases_token_and_fails_outbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.api_tool_service import make_tool_request
    from infrastructure.outbox import list_items
    from skills.loader import load_skills
    from terminal.api._config import _load_config

    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)
    note = vault / "note.md"
    note.write_text("original", encoding="utf-8")
    preview = obsidian_write.compute_preview(
        {"path": "note.md", "content": "replacement", "mode": "overwrite"}
    )
    args = _args("note.md", "replacement", preview)
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding, fingerprint = _stage(db_path, args)
    event_id = "obsidian-runtime-cancelled-before-begin"
    request = make_tool_request(
        "obsidian_write",
        args,
        load_skills(),
        cfg=_load_config(),
        event_id=event_id,
        force_approval=True,
    )
    request["approvalFingerprint"] = fingerprint
    request["runtimeContract"] = binding.to_dict()
    set_tool_draft(event_id, request)
    context = _runtime_context(db_path)
    cancelled_token = context.cancellations.token(binding.run_id)
    request_write_cancellation(
        db_path,
        binding.run_id,
        context.cancellations,
        now="2026-07-24T10:01:00+00:00",
    )

    with pytest.raises(ValueError, match="runtime binding"):
        _tool_approval(
            {"eventId": event_id, "decision": "approved"},
            context,
        )

    outbox = [item for item in list_items(db_path) if item["kind"] == "tool.execute"]
    assert len(outbox) == 1
    assert outbox[0]["status"] == "failed"
    assert context.cancellations.token(binding.run_id) is not cancelled_token
    assert note.read_text(encoding="utf-8") == "original"


def test_outbox_retry_reenters_runtime_and_verifies_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infrastructure.outbox import (
        approve,
        claim_for_sending,
        enqueue,
        get_item,
        mark_failed,
    )

    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)
    note = vault / "note.md"
    note.write_text("original", encoding="utf-8")
    preview = obsidian_write.compute_preview(
        {"path": "note.md", "content": "replacement", "mode": "overwrite"}
    )
    args = _args("note.md", "replacement", preview)
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding, fingerprint = _stage(db_path, args)
    context = _runtime_context(db_path)
    item = enqueue(
        db_path,
        kind="tool.execute",
        payload={
            "draft": {
                "kind": "tool_request",
                "skillName": "obsidian_write",
                "args": args,
                "approvalFingerprint": fingerprint,
                "runtimeContract": binding.to_dict(),
            }
        },
        idempotency_key=f"tool:{fingerprint}",
        now=context.now(),
    )
    approve(db_path, item["id"], now=context.now())
    claim_for_sending(db_path, item["id"], now=context.now())
    mark_failed(db_path, item["id"], "forced retry", now=context.now())

    response = _retry_tool_outbox(item["id"], context)

    assert response["executed"] is True
    assert response["verificationReceipt"]["status"] == "verified"
    assert note.read_text(encoding="utf-8") == "replacement"
    assert get_run(db_path, binding.run_id).state is RunState.COMPLETED
    assert get_step(db_path, binding.step_id).state is StepState.COMPLETED
    assert [item.kind for item in list_artifacts(db_path, binding.step_id)] == [
        "obsidian_verification_target",
        "obsidian_markdown",
    ]
    assert len(list_verifications(db_path, binding.step_id)) == 1
    assert get_item(db_path, item["id"])["status"] == "sent"


def test_outbox_retry_closes_completed_runtime_without_rewriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infrastructure.outbox import (
        approve,
        claim_for_sending,
        enqueue,
        get_item,
        mark_failed,
    )
    from terminal.api.tool_approval_routes import _run_runtime_bound_outbox_draft

    vault = tmp_path / "vault"
    vault.mkdir()
    _patch_vault(monkeypatch, vault)
    note = vault / "note.md"
    note.write_text("original", encoding="utf-8")
    preview = obsidian_write.compute_preview(
        {"path": "note.md", "content": "replacement", "mode": "overwrite"}
    )
    args = _args("note.md", "replacement", preview)
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding, fingerprint = _stage(db_path, args)
    draft = {
        "kind": "tool_request",
        "skillName": "obsidian_write",
        "args": args,
        "approvalFingerprint": fingerprint,
        "runtimeContract": binding.to_dict(),
    }
    context = _runtime_context(db_path)
    item = enqueue(
        db_path,
        kind="tool.execute",
        payload={"draft": draft},
        idempotency_key=f"tool:{fingerprint}",
        now=context.now(),
    )
    approve(db_path, item["id"], now=context.now())
    claim_for_sending(db_path, item["id"], now=context.now())
    execution, _, receipt, cancellation = _run_runtime_bound_outbox_draft(
        draft,
        event_id="first-delivery",
        runtime_context=context,
    )
    assert execution.executed is True
    assert receipt and receipt["status"] == "verified"
    assert cancellation is None
    mark_failed(db_path, item["id"], "mark_sent persistence failed", now=context.now())
    monkeypatch.setattr(
        "terminal.api.tool_approval_routes._run_approved_draft",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("completed Runtime must not replay the write")
        ),
    )

    response = _retry_tool_outbox(item["id"], context)

    assert response["executed"] is True
    assert response["verificationReceipt"]["status"] == "verified"
    assert response["reused"] is True
    assert note.read_text(encoding="utf-8") == "replacement"
    assert get_item(db_path, item["id"])["status"] == "sent"


def test_outbox_retry_rejects_invalid_runtime_contract_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infrastructure.outbox import approve, enqueue, get_item

    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    context = _runtime_context(db_path)
    item = enqueue(
        db_path,
        kind="tool.execute",
        payload={
            "draft": {
                "kind": "tool_request",
                "skillName": "safe_tool",
                "args": {},
                "runtimeContract": {},
            }
        },
        idempotency_key="tool:invalid-runtime-contract",
        now=context.now(),
    )
    approve(db_path, item["id"], now=context.now())
    calls = 0

    def counted_run(_draft: dict) -> ApprovalExecution:
        nonlocal calls
        calls += 1
        return ApprovalExecution(True, "done", "done")

    monkeypatch.setattr(
        "terminal.api.tool_approval_routes._run_approved_draft",
        counted_run,
    )

    response = _retry_tool_outbox(item["id"], context)

    assert response["ok"] is False
    assert calls == 0
    assert get_item(db_path, item["id"])["status"] == "failed"


def test_outbox_retry_rejects_drifted_args_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infrastructure.outbox import approve, enqueue, get_item

    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    args = {
        "path": "note.md",
        "content": "original approved content",
        "mode": "overwrite",
        "expected_mtime": None,
        "expected_size": 0,
        "expected_fingerprint": "sha256:missing",
        "expected_exists": False,
    }
    binding, fingerprint = _stage(db_path, args)
    drifted = dict(args, content="tampered content")
    context = _runtime_context(db_path)
    item = enqueue(
        db_path,
        kind="tool.execute",
        payload={
            "draft": {
                "kind": "tool_request",
                "skillName": "obsidian_write",
                "args": drifted,
                "approvalFingerprint": fingerprint,
                "runtimeContract": binding.to_dict(),
            }
        },
        idempotency_key=f"tool:{fingerprint}",
        now=context.now(),
    )
    approve(db_path, item["id"], now=context.now())
    calls = 0

    def counted_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("drifted draft must not execute")

    monkeypatch.setattr(
        "terminal.api.tool_approval_routes._run_approved_draft",
        counted_run,
    )

    response = _retry_tool_outbox(item["id"], context)

    assert response["ok"] is False
    assert "fingerprint" in response["error"]
    assert calls == 0
    assert get_run(db_path, binding.run_id).state is RunState.WAITING_APPROVAL
    assert get_item(db_path, item["id"])["status"] == "failed"
