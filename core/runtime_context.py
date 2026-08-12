"""Explicit runtime dependencies for new Archer execution paths.

Legacy functions may keep their current signatures while they migrate behind
facades. New paths should receive one RuntimeContext instead of capturing
database paths, configuration, clocks, buses, or model clients at import time.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.event_bus import ArcherEventBus
from core.llm_client import LLMClient
from core.paths import memory_db_path
from core.runtime_cancellation import CancellationRegistry

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class RuntimeContext:
    db_path: Path
    config: Mapping[str, Any]
    clock: Clock
    event_bus: ArcherEventBus
    llm_client: LLMClient | None
    cancellations: CancellationRegistry = field(default_factory=CancellationRegistry)

    def now(self) -> datetime:
        return self.clock()


def create_runtime_context(
    *,
    db_path: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    clock: Clock | None = None,
    event_bus: ArcherEventBus | None = None,
    llm_client: LLMClient | None = None,
    cancellations: CancellationRegistry | None = None,
) -> RuntimeContext:
    """Build dependencies at call time so tests and app roots can isolate state."""
    resolved_db_path = (
        Path(db_path).expanduser()
        if db_path is not None
        else memory_db_path()
    )
    return RuntimeContext(
        db_path=resolved_db_path,
        config=dict(config or {}),
        clock=clock or (lambda: datetime.now(UTC)),
        event_bus=event_bus or ArcherEventBus(),
        llm_client=llm_client,
        cancellations=cancellations or CancellationRegistry(),
    )
