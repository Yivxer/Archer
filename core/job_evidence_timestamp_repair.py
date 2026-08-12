"""Append-only, audited repairs for legacy naive evidence timestamps."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.authority_migration import (
    AuthorityComparisonReceipt,
    AuthorityMigrationError,
    AuthorityVerdict,
    MigrationMode,
    build_authority_comparison,
    list_authority_comparisons,
    record_authority_comparison,
)

TIMESTAMP_REPAIR_DOMAIN = "background_job_evidence_repair"
TIMESTAMP_REPAIR_PREFIX = "background_job_evidence_timestamp_repair:"
LEGACY_NAIVE_CLOCK_REASON = "legacy_runtime_context_naive_local_clock"
OBSERVATION_PREFIX = "background_job_command_observation:"


def _aware_instant(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AuthorityMigrationError(f"invalid {field}: {value}") from exc
    if parsed.tzinfo is None:
        raise AuthorityMigrationError(f"{field} must include timezone")
    return parsed.astimezone(UTC)


def _naive_instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AuthorityMigrationError(
            f"invalid original observation timestamp: {value}"
        ) from exc
    if parsed.tzinfo is not None:
        raise AuthorityMigrationError(
            "timestamp repair only accepts a naive original observation"
        )
    return parsed


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise AuthorityMigrationError(f"unknown source timezone: {name}") from exc


def _original_receipts(
    db_path: str | Path,
) -> dict[str, AuthorityComparisonReceipt]:
    return {
        receipt.id: receipt
        for receipt in list_authority_comparisons(
            db_path,
            domain="background_job",
        )
    }


def _repair_payload(
    original: AuthorityComparisonReceipt,
    *,
    source_timezone: str,
    reason: str,
) -> dict[str, str]:
    if not original.reason.startswith(OBSERVATION_PREFIX):
        raise AuthorityMigrationError(
            "timestamp repair target is not a background job observation"
        )
    if reason != LEGACY_NAIVE_CLOCK_REASON:
        raise AuthorityMigrationError(f"unsupported timestamp repair reason: {reason}")
    corrected_at = (
        _naive_instant(original.recorded_at)
        .replace(tzinfo=_timezone(source_timezone))
        .astimezone(UTC)
        .isoformat()
    )
    return {
        "correctedAt": corrected_at,
        "reason": reason,
        "sourceTimezone": source_timezone,
    }


def _repair_reason(payload: dict[str, str]) -> str:
    return TIMESTAMP_REPAIR_PREFIX + json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _build_repair(
    original: AuthorityComparisonReceipt,
    *,
    source_timezone: str,
    reason: str,
    recorded_at: str,
) -> AuthorityComparisonReceipt:
    _aware_instant(recorded_at, field="repair recorded_at")
    payload = _repair_payload(
        original,
        source_timezone=source_timezone,
        reason=reason,
    )
    return build_authority_comparison(
        run_id=original.run_id,
        domain=TIMESTAMP_REPAIR_DOMAIN,
        legacy_id=original.id,
        mode=MigrationMode.SHADOW,
        legacy_snapshot={
            "receiptId": original.id,
            "recordedAt": original.recorded_at,
        },
        runtime_snapshot=payload,
        verdict=AuthorityVerdict.ALIGNED,
        reason=_repair_reason(payload),
        recorded_at=recorded_at,
    )


def record_timestamp_repair(
    db_path: str | Path,
    *,
    receipt_id: str,
    source_timezone: str,
    reason: str,
    recorded_at: str,
) -> AuthorityComparisonReceipt:
    """Append a deterministic repair receipt without changing the source receipt."""
    original = _original_receipts(db_path).get(receipt_id)
    if original is None:
        raise AuthorityMigrationError(f"timestamp repair target not found: {receipt_id}")
    return record_authority_comparison(
        db_path,
        _build_repair(
            original,
            source_timezone=source_timezone,
            reason=reason,
            recorded_at=recorded_at,
        ),
    )


def audited_timestamp_repairs(
    db_path: str | Path,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Return validated UTC corrections plus fail-closed audit blockers."""
    originals = _original_receipts(db_path)
    corrections: dict[str, str] = {}
    blockers: list[str] = []
    for repair in list_authority_comparisons(
        db_path,
        domain=TIMESTAMP_REPAIR_DOMAIN,
    ):
        try:
            original = originals[repair.legacy_id]
            if not repair.reason.startswith(TIMESTAMP_REPAIR_PREFIX):
                raise AuthorityMigrationError("invalid timestamp repair reason prefix")
            raw_payload = repair.reason.removeprefix(TIMESTAMP_REPAIR_PREFIX)
            payload = json.loads(raw_payload)
            if not isinstance(payload, dict) or set(payload) != {
                "correctedAt",
                "reason",
                "sourceTimezone",
            }:
                raise AuthorityMigrationError("invalid timestamp repair payload")
            expected = _build_repair(
                original,
                source_timezone=str(payload["sourceTimezone"]),
                reason=str(payload["reason"]),
                recorded_at=repair.recorded_at,
            )
            if repair != expected or payload["correctedAt"] != json.loads(
                expected.reason.removeprefix(TIMESTAMP_REPAIR_PREFIX)
            )["correctedAt"]:
                raise AuthorityMigrationError("timestamp repair receipt does not verify")
            if original.id in corrections:
                raise AuthorityMigrationError("duplicate timestamp repair receipt")
            corrections[original.id] = str(payload["correctedAt"])
        except (AuthorityMigrationError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            blockers.append(f"invalid_timestamp_repair:{repair.id}")
    return corrections, tuple(sorted(set(blockers)))
