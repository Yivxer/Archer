"""A cache refresh must preserve durable payloads and authorization conflicts."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.runtime_context import create_runtime_context
from infrastructure.outbox import cancel, enqueue, get_item
from memory.migrations import run_migrations
from terminal.api._config import CACHE_CREATED_AT_FIELD
from terminal.api.tool_approval_routes import _enqueue_tool_outbox


def _existing(db: Path) -> tuple[object, dict, dict]:
    run_migrations(db)
    context = create_runtime_context(db_path=db)
    draft = {
        "kind": "tool_request", "skillName": "obsidian_write",
        "args": {"path": "original.md", "content": "same", "mode": "overwrite"},
        "requiresApproval": True, CACHE_CREATED_AT_FIELD: 10,
    }
    item = enqueue(
        db, kind="tool.execute", payload={"draft": draft},
        idempotency_key="tool:original", now=context.now(),
    )
    cancelled = cancel(db, item["id"], now=context.now())
    assert cancelled is not None
    return context, draft, cancelled


def test_cache_refresh_reuses_cancelled_outbox_without_changing_old_payload(tmp_path: Path) -> None:
    context, draft, before = _existing(tmp_path / "outbox.db")
    replay = _enqueue_tool_outbox(context, {**draft, CACHE_CREATED_AT_FIELD: 20}, "tool:original")
    assert replay["id"] == before["id"]
    assert replay["reused"] is True and replay["status"] == "cancelled"
    assert replay["payload"]["draft"][CACHE_CREATED_AT_FIELD] == 10
    assert get_item(context.db_path, before["id"]) == before


@pytest.mark.parametrize("field", ["args", "requiresApproval"])
def test_cache_refresh_still_rejects_business_or_approval_drift(
    tmp_path: Path, field: str,
) -> None:
    context, draft, before = _existing(tmp_path / "outbox.db")
    changed = {**draft, CACHE_CREATED_AT_FIELD: 20}
    changed[field] = {**draft["args"], "path": "another.md"} if field == "args" else False
    with pytest.raises(ValueError, match="different outbox payload"):
        _enqueue_tool_outbox(context, changed, "tool:original")
    assert get_item(context.db_path, before["id"]) == before
