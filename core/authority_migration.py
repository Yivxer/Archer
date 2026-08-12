"""Fail-closed authority migration gates and append-only comparisons."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from core.run_store_support import connect

AUTHORITY_COMPARISON_CONTRACT_VERSION = 1
REGISTERED_AUTHORITY_DOMAINS = frozenset({
    "task_plan",
    "background_job",
    "background_job_cutover_review",
    "background_job_evidence_repair",
    "child_job",
    "approval",
    "outbox",
    "hugo",
    "schedule",
    "thread_resume",
})


class MigrationMode(StrEnum):
    SHADOW = "shadow"
    AUTHORITATIVE = "authoritative"


class AuthorityVerdict(StrEnum):
    ALIGNED = "aligned"
    DRIFTED = "drifted"
    UNSUPPORTED = "unsupported"


class AuthorityMigrationError(ValueError):
    """An authority mode or comparison violates the migration contract."""


@dataclass(frozen=True, slots=True)
class AuthorityComparisonReceipt:
    id: str
    run_id: str
    domain: str
    legacy_id: str
    mode: MigrationMode
    legacy_snapshot_fingerprint: str
    runtime_snapshot_fingerprint: str
    verdict: AuthorityVerdict
    reason: str
    contract_version: int
    idempotency_key: str
    recorded_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "runId": self.run_id,
            "domain": self.domain,
            "legacyId": self.legacy_id,
            "mode": self.mode.value,
            "legacySnapshotFingerprint": self.legacy_snapshot_fingerprint,
            "runtimeSnapshotFingerprint": self.runtime_snapshot_fingerprint,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "contractVersion": self.contract_version,
            "idempotencyKey": self.idempotency_key,
            "recordedAt": self.recorded_at,
        }


def resolve_migration_mode(
    config: Mapping[str, object],
    domain: str,
) -> MigrationMode:
    if domain not in REGISTERED_AUTHORITY_DOMAINS:
        raise AuthorityMigrationError(f"unknown authority domain: {domain}")
    runtime = config.get("runtime")
    modes = runtime.get("migration_modes") if isinstance(runtime, dict) else None
    raw_mode = modes.get(domain) if isinstance(modes, dict) else None
    if raw_mode is None:
        return MigrationMode.SHADOW
    try:
        return MigrationMode(str(raw_mode).strip())
    except ValueError as exc:
        raise AuthorityMigrationError(
            f"unsupported migration mode for {domain}: {raw_mode}"
        ) from exc


def snapshot_fingerprint(snapshot: Mapping[str, object]) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _receipt_identity(
    *,
    run_id: str,
    domain: str,
    legacy_id: str,
    mode: MigrationMode,
    legacy_fingerprint: str,
    runtime_fingerprint: str,
    verdict: AuthorityVerdict,
) -> tuple[str, str]:
    material = "\0".join((
        str(AUTHORITY_COMPARISON_CONTRACT_VERSION),
        run_id,
        domain,
        legacy_id,
        mode.value,
        legacy_fingerprint,
        runtime_fingerprint,
        verdict.value,
    ))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"authority-comparison-{digest[:24]}", digest


def build_authority_comparison(
    *,
    run_id: str,
    domain: str,
    legacy_id: str,
    mode: MigrationMode,
    legacy_snapshot: Mapping[str, object],
    runtime_snapshot: Mapping[str, object],
    verdict: AuthorityVerdict,
    reason: str,
    recorded_at: str,
) -> AuthorityComparisonReceipt:
    if domain not in REGISTERED_AUTHORITY_DOMAINS:
        raise AuthorityMigrationError(f"unknown authority domain: {domain}")
    if not all((run_id.strip(), legacy_id.strip(), reason.strip(), recorded_at.strip())):
        raise AuthorityMigrationError("authority comparison fields must not be empty")
    legacy_fingerprint = snapshot_fingerprint(legacy_snapshot)
    runtime_fingerprint = snapshot_fingerprint(runtime_snapshot)
    receipt_id, idempotency_key = _receipt_identity(
        run_id=run_id,
        domain=domain,
        legacy_id=legacy_id,
        mode=mode,
        legacy_fingerprint=legacy_fingerprint,
        runtime_fingerprint=runtime_fingerprint,
        verdict=verdict,
    )
    return AuthorityComparisonReceipt(
        id=receipt_id,
        run_id=run_id,
        domain=domain,
        legacy_id=legacy_id,
        mode=mode,
        legacy_snapshot_fingerprint=legacy_fingerprint,
        runtime_snapshot_fingerprint=runtime_fingerprint,
        verdict=verdict,
        reason=reason,
        contract_version=AUTHORITY_COMPARISON_CONTRACT_VERSION,
        idempotency_key=idempotency_key,
        recorded_at=recorded_at,
    )


def _row_to_receipt(row: sqlite3.Row) -> AuthorityComparisonReceipt:
    return AuthorityComparisonReceipt(
        id=row["id"],
        run_id=row["run_id"],
        domain=row["domain"],
        legacy_id=row["legacy_id"],
        mode=MigrationMode(row["mode"]),
        legacy_snapshot_fingerprint=row["legacy_snapshot_fingerprint"],
        runtime_snapshot_fingerprint=row["runtime_snapshot_fingerprint"],
        verdict=AuthorityVerdict(row["verdict"]),
        reason=row["reason"],
        contract_version=int(row["contract_version"]),
        idempotency_key=row["idempotency_key"],
        recorded_at=row["recorded_at"],
    )


def list_authority_comparisons(
    db_path: str | Path,
    *,
    domain: str,
    run_id: str | None = None,
) -> list[AuthorityComparisonReceipt]:
    if domain not in REGISTERED_AUTHORITY_DOMAINS:
        raise AuthorityMigrationError(f"unknown authority domain: {domain}")
    conn = connect(db_path)
    try:
        query = "SELECT * FROM runtime_authority_comparisons WHERE domain = ?"
        parameters: tuple[object, ...] = (domain,)
        if run_id is not None:
            query += " AND run_id = ?"
            parameters += (run_id,)
        query += " ORDER BY recorded_at ASC, id ASC"
        rows = conn.execute(query, parameters).fetchall()
    finally:
        conn.close()
    return [_row_to_receipt(row) for row in rows]


def authority_comparison_schema_available(db_path: str | Path) -> bool:
    conn = connect(db_path)
    try:
        return conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'runtime_authority_comparisons'
            """
        ).fetchone() is not None
    finally:
        conn.close()


def record_authority_comparison(
    db_path: str | Path,
    receipt: AuthorityComparisonReceipt,
) -> AuthorityComparisonReceipt:
    conn = connect(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO runtime_authority_comparisons(
                    id, run_id, domain, legacy_id, mode,
                    legacy_snapshot_fingerprint, runtime_snapshot_fingerprint,
                    verdict, reason, contract_version, idempotency_key, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.id,
                    receipt.run_id,
                    receipt.domain,
                    receipt.legacy_id,
                    receipt.mode.value,
                    receipt.legacy_snapshot_fingerprint,
                    receipt.runtime_snapshot_fingerprint,
                    receipt.verdict.value,
                    receipt.reason,
                    receipt.contract_version,
                    receipt.idempotency_key,
                    receipt.recorded_at,
                ),
            )
        return receipt
    except sqlite3.IntegrityError:
        existing = next(
            (
                item for item in list_authority_comparisons(
                    db_path,
                    domain=receipt.domain,
                    run_id=receipt.run_id,
                )
                if item.idempotency_key == receipt.idempotency_key
            ),
            None,
        )
        if existing is not None and (
            existing.id,
            existing.run_id,
            existing.domain,
            existing.legacy_id,
            existing.mode,
            existing.legacy_snapshot_fingerprint,
            existing.runtime_snapshot_fingerprint,
            existing.verdict,
            existing.reason,
            existing.contract_version,
            existing.idempotency_key,
        ) == (
            receipt.id,
            receipt.run_id,
            receipt.domain,
            receipt.legacy_id,
            receipt.mode,
            receipt.legacy_snapshot_fingerprint,
            receipt.runtime_snapshot_fingerprint,
            receipt.verdict,
            receipt.reason,
            receipt.contract_version,
            receipt.idempotency_key,
        ):
            return existing
        raise AuthorityMigrationError(
            f"authority comparison collision: {receipt.idempotency_key}"
        )
    finally:
        conn.close()


def authority_cutover_allowed(
    receipts: list[AuthorityComparisonReceipt],
) -> bool:
    if not receipts:
        return False
    latest_by_legacy_id: dict[str, AuthorityComparisonReceipt] = {}
    for receipt in receipts:
        latest_by_legacy_id[receipt.legacy_id] = receipt
    return all(
        receipt.verdict is AuthorityVerdict.ALIGNED
        for receipt in latest_by_legacy_id.values()
    )
