"""SQLite schema owned by the Archer Runtime Closure store."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def init_run_store_schema(db_path: str | Path) -> None:
    resolved_db_path = Path(db_path).expanduser()
    resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved_db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runtime_runs (
                id                 TEXT PRIMARY KEY,
                contract_version   INTEGER NOT NULL,
                objective          TEXT NOT NULL,
                source             TEXT NOT NULL,
                state              TEXT NOT NULL,
                stop_reason        TEXT,
                current_step_id    TEXT,
                session_id         TEXT,
                thread_id          TEXT,
                parent_run_id      TEXT REFERENCES runtime_runs(id),
                context_receipt_id TEXT,
                budget_json        TEXT NOT NULL,
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL,
                completed_at       TEXT,
                version            INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_steps (
                id                TEXT PRIMARY KEY,
                run_id            TEXT NOT NULL REFERENCES runtime_runs(id),
                ordinal           INTEGER NOT NULL,
                title             TEXT NOT NULL,
                kind              TEXT NOT NULL,
                state             TEXT NOT NULL,
                depends_on_json   TEXT NOT NULL,
                capability        TEXT,
                requires_approval INTEGER NOT NULL,
                success_json      TEXT NOT NULL,
                attempt_count     INTEGER NOT NULL,
                max_attempts      INTEGER NOT NULL,
                started_at        TEXT,
                finished_at       TEXT,
                error_code        TEXT,
                error_summary     TEXT,
                UNIQUE(run_id, ordinal)
            );

            CREATE TABLE IF NOT EXISTS runtime_events (
                id           TEXT PRIMARY KEY,
                run_id       TEXT NOT NULL REFERENCES runtime_runs(id),
                step_id      TEXT REFERENCES runtime_steps(id),
                sequence     INTEGER NOT NULL,
                event_type   TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                UNIQUE(run_id, sequence)
            );

            CREATE TABLE IF NOT EXISTS runtime_artifacts (
                id            TEXT PRIMARY KEY,
                run_id        TEXT NOT NULL REFERENCES runtime_runs(id),
                step_id       TEXT NOT NULL REFERENCES runtime_steps(id),
                kind          TEXT NOT NULL,
                uri_or_path   TEXT NOT NULL,
                fingerprint   TEXT NOT NULL,
                media_type    TEXT NOT NULL,
                created_by    TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_verifications (
                id             TEXT PRIMARY KEY,
                run_id         TEXT NOT NULL REFERENCES runtime_runs(id),
                step_id        TEXT NOT NULL REFERENCES runtime_steps(id),
                verifier       TEXT NOT NULL,
                status         TEXT NOT NULL,
                criteria_json  TEXT NOT NULL,
                evidence_json  TEXT NOT NULL,
                tool_call_id   TEXT,
                checked_at     TEXT NOT NULL,
                error_code     TEXT,
                summary        TEXT NOT NULL
            );

            CREATE TRIGGER IF NOT EXISTS runtime_events_no_update
            BEFORE UPDATE ON runtime_events
            BEGIN
                SELECT RAISE(ABORT, 'runtime events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS runtime_events_no_delete
            BEFORE DELETE ON runtime_events
            BEGIN
                SELECT RAISE(ABORT, 'runtime events are append-only');
            END;
            """
        )
        conn.commit()
    finally:
        conn.close()


def init_run_checkpoint_schema(db_path: str | Path) -> None:
    conn = sqlite3.connect(Path(db_path).expanduser())
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runtime_checkpoints (
                id             TEXT PRIMARY KEY,
                run_id         TEXT NOT NULL REFERENCES runtime_runs(id),
                step_id        TEXT REFERENCES runtime_steps(id),
                resume_state   TEXT NOT NULL,
                cursor_version INTEGER NOT NULL,
                cursor_json    TEXT NOT NULL,
                created_at     TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_runtime_checkpoints_run_created
            ON runtime_checkpoints(run_id, created_at, id);

            CREATE TRIGGER IF NOT EXISTS runtime_checkpoints_no_update
            BEFORE UPDATE ON runtime_checkpoints
            BEGIN
                SELECT RAISE(ABORT, 'runtime checkpoints are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS runtime_checkpoints_no_delete
            BEFORE DELETE ON runtime_checkpoints
            BEGIN
                SELECT RAISE(ABORT, 'runtime checkpoints are append-only');
            END;
            """
        )
        conn.commit()
    finally:
        conn.close()


def init_task_plan_observation_schema(db_path: str | Path) -> None:
    conn = sqlite3.connect(Path(db_path).expanduser())
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runtime_task_plan_observations (
                id                        TEXT PRIMARY KEY,
                run_id                    TEXT NOT NULL REFERENCES runtime_runs(id),
                plan_id                   TEXT NOT NULL,
                trace_id                  TEXT NOT NULL,
                legacy_status             TEXT NOT NULL,
                handoff                   TEXT NOT NULL,
                runtime_execution_claimed INTEGER NOT NULL,
                observed_at               TEXT NOT NULL,
                UNIQUE(run_id, legacy_status),
                CHECK(legacy_status IN ('accepted', 'dismissed')),
                CHECK(runtime_execution_claimed = 0)
            );

            CREATE INDEX IF NOT EXISTS idx_task_plan_observations_run
            ON runtime_task_plan_observations(run_id, observed_at, id);

            CREATE TRIGGER IF NOT EXISTS runtime_task_plan_observations_no_update
            BEFORE UPDATE ON runtime_task_plan_observations
            BEGIN
                SELECT RAISE(ABORT, 'task plan observations are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS runtime_task_plan_observations_no_delete
            BEFORE DELETE ON runtime_task_plan_observations
            BEGIN
                SELECT RAISE(ABORT, 'task plan observations are append-only');
            END;
            """
        )
        conn.commit()
    finally:
        conn.close()


def init_task_plan_job_shadow_schema(db_path: str | Path) -> None:
    conn = sqlite3.connect(Path(db_path).expanduser())
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runtime_task_plan_job_bindings (
                id                        TEXT PRIMARY KEY,
                run_id                    TEXT NOT NULL REFERENCES runtime_runs(id),
                plan_id                   TEXT NOT NULL,
                legacy_job_id             TEXT NOT NULL,
                job_kind                  TEXT NOT NULL,
                runtime_execution_claimed INTEGER NOT NULL,
                bound_at                  TEXT NOT NULL,
                UNIQUE(run_id),
                UNIQUE(legacy_job_id),
                CHECK(runtime_execution_claimed = 0)
            );

            CREATE TABLE IF NOT EXISTS runtime_task_plan_job_observations (
                id                      TEXT PRIMARY KEY,
                binding_id              TEXT NOT NULL
                                        REFERENCES runtime_task_plan_job_bindings(id),
                run_id                  TEXT NOT NULL REFERENCES runtime_runs(id),
                legacy_job_id           TEXT NOT NULL,
                legacy_status           TEXT NOT NULL,
                job_updated_at          TEXT NOT NULL,
                observed_at             TEXT NOT NULL,
                verification_receipt_id TEXT NOT NULL DEFAULT '',
                evidence_json           TEXT NOT NULL DEFAULT '{}',
                runtime_state_changed   INTEGER NOT NULL,
                UNIQUE(
                    legacy_job_id, legacy_status, job_updated_at,
                    verification_receipt_id
                ),
                CHECK(legacy_status IN (
                    'queued', 'running', 'waiting_approval',
                    'complete', 'failed', 'cancelled'
                )),
                CHECK(runtime_state_changed = 0)
            );

            CREATE INDEX IF NOT EXISTS idx_task_plan_job_observations_run
            ON runtime_task_plan_job_observations(
                run_id, job_updated_at, observed_at, id
            );

            CREATE TRIGGER IF NOT EXISTS runtime_task_plan_job_bindings_no_update
            BEFORE UPDATE ON runtime_task_plan_job_bindings
            BEGIN
                SELECT RAISE(ABORT, 'task plan job bindings are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS runtime_task_plan_job_bindings_no_delete
            BEFORE DELETE ON runtime_task_plan_job_bindings
            BEGIN
                SELECT RAISE(ABORT, 'task plan job bindings are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS runtime_task_plan_job_observations_no_update
            BEFORE UPDATE ON runtime_task_plan_job_observations
            BEGIN
                SELECT RAISE(ABORT, 'task plan job observations are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS runtime_task_plan_job_observations_no_delete
            BEFORE DELETE ON runtime_task_plan_job_observations
            BEGIN
                SELECT RAISE(ABORT, 'task plan job observations are append-only');
            END;
            """
        )
        conn.commit()
    finally:
        conn.close()


def upgrade_task_plan_job_evidence_schema(db_path: str | Path) -> None:
    """Add receipt-aware, no-body evidence to legacy Job observations."""
    resolved_db_path = Path(db_path).expanduser()
    conn = sqlite3.connect(resolved_db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        table_exists = conn.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table'
              AND name = 'runtime_task_plan_job_observations'
            """
        ).fetchone()
        if table_exists is None:
            conn.close()
            init_task_plan_job_shadow_schema(resolved_db_path)
            return
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(runtime_task_plan_job_observations)"
            )
        }
        if {"verification_receipt_id", "evidence_json"} <= columns:
            return
        with conn:
            conn.executescript(
                """
                ALTER TABLE runtime_task_plan_job_observations
                RENAME TO runtime_task_plan_job_observations_v8;

                CREATE TABLE runtime_task_plan_job_observations (
                    id                      TEXT PRIMARY KEY,
                    binding_id              TEXT NOT NULL
                                              REFERENCES runtime_task_plan_job_bindings(id),
                    run_id                  TEXT NOT NULL REFERENCES runtime_runs(id),
                    legacy_job_id           TEXT NOT NULL,
                    legacy_status           TEXT NOT NULL,
                    job_updated_at          TEXT NOT NULL,
                    observed_at             TEXT NOT NULL,
                    verification_receipt_id TEXT NOT NULL DEFAULT '',
                    evidence_json           TEXT NOT NULL DEFAULT '{}',
                    runtime_state_changed   INTEGER NOT NULL,
                    UNIQUE(
                        legacy_job_id, legacy_status, job_updated_at,
                        verification_receipt_id
                    ),
                    CHECK(legacy_status IN (
                        'queued', 'running', 'waiting_approval',
                        'complete', 'failed', 'cancelled'
                    )),
                    CHECK(runtime_state_changed = 0)
                );

                INSERT INTO runtime_task_plan_job_observations(
                    id, binding_id, run_id, legacy_job_id, legacy_status,
                    job_updated_at, observed_at, verification_receipt_id,
                    evidence_json, runtime_state_changed
                )
                SELECT
                    id, binding_id, run_id, legacy_job_id, legacy_status,
                    job_updated_at, observed_at, '', '{}', runtime_state_changed
                FROM runtime_task_plan_job_observations_v8;

                DROP TABLE runtime_task_plan_job_observations_v8;

                CREATE INDEX idx_task_plan_job_observations_run
                ON runtime_task_plan_job_observations(
                    run_id, job_updated_at, observed_at, id
                );

                CREATE TRIGGER runtime_task_plan_job_observations_no_update
                BEFORE UPDATE ON runtime_task_plan_job_observations
                BEGIN
                    SELECT RAISE(
                        ABORT, 'task plan job observations are append-only'
                    );
                END;

                CREATE TRIGGER runtime_task_plan_job_observations_no_delete
                BEFORE DELETE ON runtime_task_plan_job_observations
                BEGIN
                    SELECT RAISE(
                        ABORT, 'task plan job observations are append-only'
                    );
                END;
                """
            )
    finally:
        if conn:
            conn.close()


def init_runtime_authority_comparison_schema(db_path: str | Path) -> None:
    conn = sqlite3.connect(Path(db_path).expanduser())
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runtime_authority_comparisons (
                id                           TEXT PRIMARY KEY,
                run_id                       TEXT NOT NULL REFERENCES runtime_runs(id),
                domain                       TEXT NOT NULL,
                legacy_id                    TEXT NOT NULL,
                mode                         TEXT NOT NULL,
                legacy_snapshot_fingerprint  TEXT NOT NULL,
                runtime_snapshot_fingerprint TEXT NOT NULL,
                verdict                      TEXT NOT NULL,
                reason                       TEXT NOT NULL,
                contract_version             INTEGER NOT NULL,
                idempotency_key              TEXT NOT NULL UNIQUE,
                recorded_at                  TEXT NOT NULL,
                CHECK(mode IN ('shadow', 'authoritative')),
                CHECK(verdict IN ('aligned', 'drifted', 'unsupported'))
            );

            CREATE INDEX IF NOT EXISTS idx_runtime_authority_comparisons
            ON runtime_authority_comparisons(domain, run_id, recorded_at, id);

            CREATE TRIGGER IF NOT EXISTS runtime_authority_comparisons_no_update
            BEFORE UPDATE ON runtime_authority_comparisons
            BEGIN
                SELECT RAISE(ABORT, 'authority comparisons are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS runtime_authority_comparisons_no_delete
            BEFORE DELETE ON runtime_authority_comparisons
            BEGIN
                SELECT RAISE(ABORT, 'authority comparisons are append-only');
            END;
            """
        )
        conn.commit()
    finally:
        conn.close()
