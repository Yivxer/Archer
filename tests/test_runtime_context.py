from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.event_bus import ArcherEvent, INITIATIVE_DUE
from core.runtime_context import RuntimeContext, create_runtime_context
from terminal.api._routes import payload_get, payload_post


@pytest.mark.unit
def test_runtime_context_injects_temp_db_fixed_clock_and_dependencies(tmp_path):
    fixed_now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    llm_client = object()
    context = create_runtime_context(
        db_path=tmp_path / "isolated.db",
        config={"api": {"model": "test-model"}},
        clock=lambda: fixed_now,
        llm_client=llm_client,
    )

    assert isinstance(context, RuntimeContext)
    assert context.db_path == tmp_path / "isolated.db"
    assert context.config["api"]["model"] == "test-model"
    assert context.now() is fixed_now
    assert context.llm_client is llm_client


@pytest.mark.unit
def test_runtime_context_owns_an_isolated_event_bus(tmp_path):
    first = create_runtime_context(db_path=tmp_path / "first.db")
    second = create_runtime_context(db_path=tmp_path / "second.db")
    received: list[str] = []
    first.event_bus.subscribe(
        INITIATIVE_DUE,
        lambda event: received.append(event.source),
    )

    first.event_bus.publish(
        ArcherEvent(type=INITIATIVE_DUE, source="first-context"),
    )
    second.event_bus.publish(
        ArcherEvent(type=INITIATIVE_DUE, source="second-context"),
    )

    assert received == ["first-context"]


@pytest.mark.integration
def test_schedules_route_uses_injected_database_and_clock(tmp_path):
    fixed_now = datetime(2026, 7, 10, 12, 34, 56)
    context = create_runtime_context(
        db_path=tmp_path / "runtime" / "isolated.db",
        clock=lambda: fixed_now,
    )

    status, payload = payload_get("/schedules", runtime_context=context)

    assert status == 200
    assert payload["tasks"] == []
    assert payload["jsonPath"] == str(context.db_path.parent / "schedules.json")
    assert context.db_path.exists()
    assert '"updatedAt": "2026-07-10T12:34:56"' in (
        context.db_path.parent / "schedules.json"
    ).read_text(encoding="utf-8")


@pytest.mark.integration
def test_schedule_mutation_stays_inside_injected_runtime(tmp_path, monkeypatch):
    context = create_runtime_context(
        db_path=tmp_path / "isolated" / "archer.db",
        clock=lambda: datetime(2026, 7, 10, 8, 0, 0),
    )

    class Registry:
        def __contains__(self, name):
            return name == "weather"

    monkeypatch.setattr("skills.loader.register_all_skills", lambda: Registry())
    status, payload = payload_post(
        "/schedules",
        {"skillName": "weather", "interval": "daily"},
        runtime_context=context,
    )

    assert status == 200
    assert payload["task"]["createdAt"] == "2026-07-10T08:00:00"
    mirror = context.db_path.parent / "schedules.json"
    assert mirror.exists()
    assert '"updatedAt": "2026-07-10T08:00:00"' in mirror.read_text(encoding="utf-8")
