"""Part 8.4 low-frequency, explainable surprise candidates."""
from __future__ import annotations

from dataclasses import dataclass

from core.connector import MemoryConnection

MIN_SURPRISE_SCORE = 0.7


@dataclass(frozen=True)
class SurpriseDraft:
    connection_key: str
    message: str
    score: float


def propose_surprise(
    connection: MemoryConnection,
    *,
    seen_connection_keys: set[str] | None = None,
) -> SurpriseDraft | None:
    """Turn one strong unseen connection into a non-delivered reminder draft."""
    key = _connection_key(connection)
    if connection.score < MIN_SURPRISE_SCORE or key in (seen_connection_keys or set()):
        return None
    tags = "、".join(connection.shared_tags)
    return SurpriseDraft(
        connection_key=key,
        message=f"有两条看似独立的线索共享了「{tags}」，也许值得先放在一起看一眼。",
        score=connection.score,
    )


def _connection_key(connection: MemoryConnection) -> str:
    left, right = sorted((str(connection.left_id), str(connection.right_id)))
    return f"{left}:{right}"
