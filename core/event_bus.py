"""Part 8 event bus primitives.

The first 8.0 slice keeps delivery in-process and synchronous. It gives the
rest of the system a stable event contract without introducing background
workers or real initiative delivery yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


SESSION_END = "session_end"
INITIATIVE_DUE = "initiative_due"
TURN_RECEIPT_READY = "turn_receipt_ready"


@dataclass(frozen=True)
class ArcherEvent:
    type: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.now)

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "source": self.source,
            "payload": dict(self.payload),
            "priority": self.priority,
            "createdAt": self.created_at.isoformat(timespec="seconds"),
        }


EventHandler = Callable[[ArcherEvent], None]


class ArcherEventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: ArcherEvent) -> ArcherEvent:
        for handler in self._handlers.get(event.type, []):
            handler(event)
        return event
