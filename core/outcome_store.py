"""Artifact and verification persistence for Runtime Closure outcomes."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.run_contract import (
    ArtifactRecord,
    RunEventRecord,
    RunEventType,
    VerificationReceipt,
    VerificationStatus,
)
from core.run_store_support import (
    connect,
    insert_event,
    json_dump,
    next_event_sequence,
    require_run_exists,
)


class OutcomeLinkMismatch(ValueError):
    """Raised when outcome records do not belong to the same Run and Step."""


class InvalidArtifactRecord(ValueError):
    """Raised when an artifact lacks traceable identity or evidence."""


class InvalidVerificationReceipt(ValueError):
    """Raised when a verification receipt cannot support its status."""


def _require_linked_step(
    conn: sqlite3.Connection,
    run_id: str,
    step_id: str,
) -> tuple[str, ...]:
    require_run_exists(conn, run_id)
    row = conn.execute(
        "SELECT run_id, success_json FROM runtime_steps WHERE id = ?",
        (step_id,),
    ).fetchone()
    if row is None or row["run_id"] != run_id:
        raise OutcomeLinkMismatch(f"step does not belong to run: {step_id}")
    return tuple(json.loads(row["success_json"]))


def _insert_artifact(conn: sqlite3.Connection, record: ArtifactRecord) -> None:
    conn.execute(
        """
        INSERT INTO runtime_artifacts(
            id, run_id, step_id, kind, uri_or_path, fingerprint,
            media_type, created_by, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.id,
            record.run_id,
            record.step_id,
            record.kind,
            record.uri_or_path,
            record.fingerprint,
            record.media_type,
            record.created_by,
            json_dump(record.metadata),
        ),
    )


def record_artifact(
    db_path: str | Path,
    record: ArtifactRecord,
    *,
    event_id: str,
    created_at: str,
) -> RunEventRecord:
    if not record.fingerprint or not record.uri_or_path or not record.created_by:
        raise InvalidArtifactRecord("artifact requires path, fingerprint, and creator")
    conn = connect(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            _require_linked_step(conn, record.run_id, record.step_id)
            _insert_artifact(conn, record)
            event = RunEventRecord(
                id=event_id,
                run_id=record.run_id,
                step_id=record.step_id,
                sequence=next_event_sequence(conn, record.run_id),
                event_type=RunEventType.ARTIFACT_RECORDED,
                created_at=created_at,
                payload={"artifact": record.to_dict()},
            )
            insert_event(conn, event)
        return event
    finally:
        conn.close()


def _row_to_artifact(row: sqlite3.Row) -> ArtifactRecord:
    return ArtifactRecord(
        id=row["id"],
        run_id=row["run_id"],
        step_id=row["step_id"],
        kind=row["kind"],
        uri_or_path=row["uri_or_path"],
        fingerprint=row["fingerprint"],
        media_type=row["media_type"],
        created_by=row["created_by"],
        metadata=json.loads(row["metadata_json"]),
    )


def get_artifact(db_path: str | Path, artifact_id: str) -> ArtifactRecord | None:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM runtime_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_artifact(row) if row is not None else None


def list_artifacts(
    db_path: str | Path,
    step_id: str,
) -> list[ArtifactRecord]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM runtime_artifacts
            WHERE step_id = ?
            ORDER BY rowid
            """,
            (step_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_artifact(row) for row in rows]


def _require_evidence_links(
    conn: sqlite3.Connection,
    receipt: VerificationReceipt,
) -> None:
    for artifact_id in receipt.evidence_refs:
        row = conn.execute(
            "SELECT run_id, step_id FROM runtime_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if (
            row is None
            or row["run_id"] != receipt.run_id
            or row["step_id"] != receipt.step_id
        ):
            raise OutcomeLinkMismatch(
                f"artifact does not belong to verification step: {artifact_id}"
            )


def _validate_receipt(
    success_criteria: tuple[str, ...],
    receipt: VerificationReceipt,
) -> None:
    if not receipt.verifier or not receipt.checked_at or not receipt.criteria:
        raise InvalidVerificationReceipt(
            "verification requires verifier, checked_at, and criteria"
        )
    if not set(success_criteria).issubset(receipt.criteria):
        raise InvalidVerificationReceipt(
            "verification criteria do not cover step success criteria"
        )
    if (
        receipt.status is VerificationStatus.VERIFIED
        and not receipt.evidence_refs
    ):
        raise InvalidVerificationReceipt(
            "verified receipt requires artifact evidence"
        )


def _insert_verification(
    conn: sqlite3.Connection,
    receipt: VerificationReceipt,
) -> None:
    conn.execute(
        """
        INSERT INTO runtime_verifications(
            id, run_id, step_id, verifier, status, criteria_json,
            evidence_json, tool_call_id, checked_at, error_code, summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            receipt.id,
            receipt.run_id,
            receipt.step_id,
            receipt.verifier,
            receipt.status.value,
            json_dump(list(receipt.criteria)),
            json_dump(list(receipt.evidence_refs)),
            receipt.tool_call_id,
            receipt.checked_at,
            receipt.error_code,
            receipt.summary,
        ),
    )


def record_verification(
    db_path: str | Path,
    receipt: VerificationReceipt,
    *,
    event_id: str,
) -> RunEventRecord:
    conn = connect(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            success_criteria = _require_linked_step(
                conn,
                receipt.run_id,
                receipt.step_id,
            )
            _validate_receipt(success_criteria, receipt)
            _require_evidence_links(conn, receipt)
            _insert_verification(conn, receipt)
            event = RunEventRecord(
                id=event_id,
                run_id=receipt.run_id,
                step_id=receipt.step_id,
                sequence=next_event_sequence(conn, receipt.run_id),
                event_type=RunEventType.VERIFICATION_RECORDED,
                created_at=receipt.checked_at,
                payload={"verification": receipt.to_dict()},
            )
            insert_event(conn, event)
        return event
    finally:
        conn.close()


def _row_to_verification(row: sqlite3.Row) -> VerificationReceipt:
    return VerificationReceipt(
        id=row["id"],
        run_id=row["run_id"],
        step_id=row["step_id"],
        verifier=row["verifier"],
        status=VerificationStatus(row["status"]),
        criteria=tuple(json.loads(row["criteria_json"])),
        evidence_refs=tuple(json.loads(row["evidence_json"])),
        tool_call_id=row["tool_call_id"],
        checked_at=row["checked_at"],
        error_code=row["error_code"],
        summary=row["summary"],
    )


def list_verifications(
    db_path: str | Path,
    step_id: str,
) -> list[VerificationReceipt]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM runtime_verifications
            WHERE step_id = ?
            ORDER BY checked_at, id
            """,
            (step_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_verification(row) for row in rows]
