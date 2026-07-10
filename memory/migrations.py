"""Versioned, checksummed SQLite migrations with local backup recovery."""
from __future__ import annotations

import hashlib
import inspect
import shutil
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


MigrationCallable = Callable[[Path], None]


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    checksum: str
    description: str
    apply: MigrationCallable

    @classmethod
    def create(
        cls,
        version: int,
        description: str,
        apply: MigrationCallable,
        *,
        checksum_material: str | None = None,
    ) -> "Migration":
        material = checksum_material
        if material is None:
            try:
                material = inspect.getsource(apply)
            except (OSError, TypeError):
                material = repr(apply)
        checksum = hashlib.sha256(
            f"{version}\0{description}\0{material}".encode("utf-8")
        ).hexdigest()
        return cls(version, checksum, description, apply)


@dataclass(frozen=True)
class MigrationResult:
    version: int
    applied: list[int]
    backup_path: Path | None


def _apply_baseline_schema(db_path: Path) -> None:
    from memory.schema_setup import initialize_schema

    initialize_schema(db_path)


MIGRATIONS: tuple[Migration, ...] = (
    Migration.create(
        1,
        "baseline current Archer schema",
        _apply_baseline_schema,
        checksum_material="archer-baseline-schema-v1",
    ),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def _sidecar_paths(db_path: Path) -> tuple[Path, Path]:
    return (
        db_path.with_name(f"{db_path.name}-wal"),
        db_path.with_name(f"{db_path.name}-shm"),
    )


def _applied_rows(db_path: Path) -> dict[int, tuple[str, str]]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        if not exists:
            return {}
        return {
            int(version): (str(checksum), str(description))
            for version, checksum, description in conn.execute(
                "SELECT version, checksum, description FROM schema_version"
            )
        }
    finally:
        conn.close()


def _validate_applied(
    applied: dict[int, tuple[str, str]],
    migrations: Sequence[Migration],
) -> None:
    expected = {migration.version: migration for migration in migrations}
    unknown = sorted(set(applied) - set(expected))
    if unknown:
        raise MigrationError(f"unknown applied migration versions: {unknown}")
    for version, (checksum, _description) in applied.items():
        if checksum != expected[version].checksum:
            raise MigrationError(f"migration checksum mismatch: version {version}")


def _checkpoint_wal(db_path: Path) -> None:
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL)").fetchone()
    finally:
        conn.close()


def _create_backup(
    db_path: Path,
    backup_dir: Path,
    now: datetime,
) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / f"{db_path.name}.pre-migration-{stamp}.bak"
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup_path


def _restore_backup(db_path: Path, backup_path: Path | None) -> None:
    for path in (db_path, *_sidecar_paths(db_path)):
        path.unlink(missing_ok=True)
    if backup_path is not None:
        shutil.copy2(backup_path, db_path)


def _ensure_version_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version     INTEGER PRIMARY KEY,
                checksum    TEXT NOT NULL,
                description TEXT NOT NULL,
                applied_at  TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def run_migrations(
    db_path: str | Path,
    *,
    migrations: Sequence[Migration] = MIGRATIONS,
    backup_dir: str | Path | None = None,
    clock: Callable[[], datetime] = datetime.now,
) -> MigrationResult:
    resolved_db_path = Path(db_path).expanduser()
    resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = tuple(sorted(migrations, key=lambda migration: migration.version))
    if not ordered:
        return MigrationResult(version=0, applied=[], backup_path=None)
    if len({migration.version for migration in ordered}) != len(ordered):
        raise MigrationError("duplicate migration version")

    already_applied = _applied_rows(resolved_db_path)
    _validate_applied(already_applied, ordered)
    pending = [migration for migration in ordered if migration.version not in already_applied]
    if not pending:
        return MigrationResult(
            version=max(already_applied, default=0),
            applied=[],
            backup_path=None,
        )

    now = clock()
    resolved_backup_dir = (
        Path(backup_dir).expanduser()
        if backup_dir is not None
        else resolved_db_path.parent / ".backups"
    )
    _checkpoint_wal(resolved_db_path)
    backup_path = _create_backup(resolved_db_path, resolved_backup_dir, now)
    applied_now: list[int] = []
    try:
        _ensure_version_table(resolved_db_path)
        for migration in pending:
            migration.apply(resolved_db_path)
            conn = sqlite3.connect(resolved_db_path)
            try:
                conn.execute(
                    "INSERT INTO schema_version(version, checksum, description, applied_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        migration.version,
                        migration.checksum,
                        migration.description,
                        now.isoformat(timespec="seconds"),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            applied_now.append(migration.version)
        final_rows = _applied_rows(resolved_db_path)
        _validate_applied(final_rows, ordered)
        if set(final_rows) != {migration.version for migration in ordered}:
            raise MigrationError("migration version sequence is incomplete")
    except Exception as exc:
        _restore_backup(resolved_db_path, backup_path)
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError(f"migration failed: {exc}") from exc

    return MigrationResult(
        version=max(migration.version for migration in ordered),
        applied=applied_now,
        backup_path=backup_path,
    )
