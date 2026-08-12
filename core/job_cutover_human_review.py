"""Append-only human review gate for Background Job authority cutover."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Mapping

from core.authority_migration import (
    AuthorityComparisonReceipt,
    AuthorityVerdict,
    MigrationMode,
    build_authority_comparison,
    list_authority_comparisons,
    record_authority_comparison,
    snapshot_fingerprint,
)
from core.job_cutover_evidence_window import (
    REQUIRED_COMMANDS,
    TARGET_JOB_KIND,
    EvidenceWindowStatus,
    review_job_cutover_evidence_window,
)

HUMAN_REVIEW_DOMAIN = "background_job_cutover_review"
_REVIEWER_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class HumanCutoverReviewError(ValueError):
    """The requested human cutover review is not safe to record."""


def _shadow_review_config(config: Mapping[str, object]) -> dict[str, object]:
    shadow = dict(config)
    raw_runtime = config.get("runtime")
    runtime = dict(raw_runtime) if isinstance(raw_runtime, dict) else {}
    raw_modes = runtime.get("migration_modes")
    modes = dict(raw_modes) if isinstance(raw_modes, dict) else {}
    modes["background_job"] = MigrationMode.SHADOW.value
    runtime["migration_modes"] = modes
    shadow["runtime"] = runtime
    return shadow


def _reviewed_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HumanCutoverReviewError("reviewed_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HumanCutoverReviewError("reviewed_at must include a timezone")
    return value


def _live_review_snapshot(
    db_path: str | Path,
    config: Mapping[str, object],
) -> dict[str, object]:
    report = review_job_cutover_evidence_window(
        db_path,
        _shadow_review_config(config),
    )
    return report.to_dict()


def record_background_job_cutover_review(
    db_path: str | Path,
    config: Mapping[str, object],
    *,
    reviewer_id: str,
    approved: bool,
    reviewed_at: str,
) -> AuthorityComparisonReceipt:
    """Record a human decision only against a live reviewable shadow window."""
    if not _REVIEWER_ID.fullmatch(reviewer_id):
        raise HumanCutoverReviewError("reviewer_id is invalid")
    snapshot = _live_review_snapshot(db_path, config)
    if snapshot["status"] != EvidenceWindowStatus.REVIEWABLE.value:
        raise HumanCutoverReviewError("evidence window is not reviewable")
    reviewed_at = _reviewed_at(reviewed_at)
    runtime_fingerprint = snapshot_fingerprint(snapshot)
    decision = "approved" if approved else "rejected"
    evidence_receipts = list_authority_comparisons(
        db_path,
        domain="background_job",
    )
    if not evidence_receipts:
        raise HumanCutoverReviewError("reviewable window has no evidence receipts")
    receipt = build_authority_comparison(
        run_id=evidence_receipts[-1].run_id,
        domain=HUMAN_REVIEW_DOMAIN,
        legacy_id=f"human-review:{reviewer_id}",
        mode=MigrationMode.SHADOW,
        legacy_snapshot={
            "reviewerId": reviewer_id,
            "decision": decision,
            "jobKind": TARGET_JOB_KIND,
            "commands": [command.value for command in REQUIRED_COMMANDS],
        },
        runtime_snapshot=snapshot,
        verdict=(
            AuthorityVerdict.ALIGNED
            if approved
            else AuthorityVerdict.DRIFTED
        ),
        reason=f"human_background_job_cutover_review:{decision}",
        recorded_at=reviewed_at,
    )
    return record_authority_comparison(db_path, receipt)


def background_job_cutover_review_approved(
    db_path: str | Path,
    config: Mapping[str, object],
) -> bool:
    """Return true only when the latest decision matches current clean evidence."""
    snapshot = _live_review_snapshot(db_path, config)
    if snapshot["status"] != EvidenceWindowStatus.REVIEWABLE.value:
        return False
    fingerprint = snapshot_fingerprint(snapshot)
    matching = [
        receipt
        for receipt in list_authority_comparisons(
            db_path,
            domain=HUMAN_REVIEW_DOMAIN,
        )
        if receipt.runtime_snapshot_fingerprint == fingerprint
    ]
    if not matching:
        return False
    latest = matching[-1]
    return (
        latest.verdict is AuthorityVerdict.ALIGNED
        and latest.reason == "human_background_job_cutover_review:approved"
    )
