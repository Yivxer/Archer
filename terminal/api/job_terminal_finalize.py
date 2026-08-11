"""Terminal state authority for legacy Background Jobs."""
from __future__ import annotations

from datetime import datetime
from typing import Mapping, MutableMapping

from core.job_cancellation import acknowledge_legacy_job_cancellation
from core.job_terminal_finalize import (
    JobTerminalFinalizeStaleError,
    assert_legacy_job_finalize_snapshot,
    assess_legacy_child_rollup,
    legacy_job_finalize_snapshot,
    record_legacy_job_terminal_finalize,
    restore_legacy_job_terminal_metadata,
)
from terminal.api.job_result_evidence import complete_legacy_job_result


def restore_legacy_job_terminal_finalize(
    raw: Mapping[str, object],
    job: MutableMapping[str, object],
) -> None:
    restore_legacy_job_terminal_metadata(raw, job)


def finalize_legacy_job_failure(
    job_id: str,
    *,
    error: str,
    failure_keyword: str,
    source: str,
    expected_attempt_id: str | None = None,
    expected_updated_at: str | None = None,
) -> dict[str, object] | None:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        store._load_jobs_locked()
        job = store.BACKGROUND_JOBS.get(job_id)
        if job is None:
            return None
        if job.get("status") in {"complete", "failed", "cancelled"}:
            return dict(job)
        assert_legacy_job_finalize_snapshot(
            job,
            expected_attempt_id=expected_attempt_id,
            expected_updated_at=expected_updated_at,
        )
        finalized_at = datetime.now().isoformat()
        if acknowledge_legacy_job_cancellation(
            job,
            acknowledged_at=finalized_at,
            stage=source,
            side_effect_started=True,
        ):
            store._persist_jobs_locked()
            return dict(job)
        job["status"] = "failed"
        job["result"] = ""
        job["error"] = error
        job["failureKeyword"] = failure_keyword
        job["updatedAt"] = finalized_at
        record_legacy_job_terminal_finalize(
            job,
            status="failed",
            source=source,
            finalized_at=finalized_at,
        )
        store._persist_jobs_locked()
        return dict(job)


def _child_rollup_summary(children: list[dict]) -> str:
    lines: list[str] = []
    for child in children:
        title = str(child.get("title", "")).replace("[子] ", "").strip()
        lines.extend((
            f"## {title} [complete]",
            str(child.get("result", "")).strip(),
            "",
        ))
    return "\n".join(lines).strip()


def try_rollup_legacy_parent_result(parent_id: str) -> bool:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        store._load_jobs_locked()
        parent = store.BACKGROUND_JOBS.get(parent_id)
        if parent is None:
            return False
        child_ids = parent.get("childJobIds")
        if not isinstance(child_ids, list) or not child_ids:
            return False
        children = [store.BACKGROUND_JOBS.get(str(child_id)) for child_id in child_ids]
        assessment = assess_legacy_child_rollup(children)
        if not assessment.terminal:
            return False
        snapshot = legacy_job_finalize_snapshot(parent)
        concrete_children = [
            dict(child) for child in children if isinstance(child, dict)
        ]
    if not assessment.ready:
        try:
            finalized = finalize_legacy_job_failure(
                parent_id,
                error=f"child Job rollup blocked: {assessment.reason}",
                failure_keyword=f"child_rollup_{assessment.reason}",
                source="child_rollup",
                expected_attempt_id=snapshot.attempt_id,
                expected_updated_at=snapshot.updated_at,
            )
        except JobTerminalFinalizeStaleError:
            return False
        return finalized is not None
    try:
        completed = complete_legacy_job_result(
            parent_id,
            _child_rollup_summary(concrete_children),
            source="child_rollup",
            expected_attempt_id=snapshot.attempt_id,
            expected_updated_at=snapshot.updated_at,
        )
    except JobTerminalFinalizeStaleError:
        return False
    return completed is not None
