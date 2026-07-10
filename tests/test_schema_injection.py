from __future__ import annotations

import sqlite3

import pytest

from memory.critique import init_critiques_table
from memory.feedback import init_table as init_feedback_table
from memory.skill_gap import init_skill_gap_table
from memory.workflow_crystal import init_table as init_workflow_crystal_table
from memory.hypothesis_tracker import init_hypotheses_table
from memory.work import init_work_table
from memory.subtask import init_subtask_table
from memory.emotion import init_emotion_table
from memory.store import init_db
from memory.schema_setup import initialize_schema


@pytest.mark.integration
def test_memory_owned_schema_initializers_accept_explicit_database(tmp_path):
    db_path = tmp_path / "isolated" / "archer.db"
    db_path.parent.mkdir(parents=True)

    init_critiques_table(db_path)
    init_skill_gap_table(db_path)
    init_workflow_crystal_table(db_path)
    init_feedback_table(db_path)
    init_hypotheses_table(db_path)
    init_work_table(db_path)
    init_subtask_table(db_path)
    init_emotion_table(db_path)

    conn = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    conn.close()

    assert {
        "self_critiques",
        "skill_events",
        "workflow_crystal",
        "interaction_feedback",
        "hypotheses",
        "work_items",
        "sub_tasks",
        "session_emotions",
    } <= tables


@pytest.mark.integration
def test_full_legacy_schema_can_initialize_an_explicit_empty_database(tmp_path):
    db_path = tmp_path / "full" / "archer.db"

    init_db(db_path)

    conn = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    conn.close()
    assert {
        "memories",
        "pending_memories",
        "scheduled_tasks",
        "self_critiques",
        "skill_events",
        "workflow_crystal",
        "interaction_feedback",
        "hypotheses",
        "initiative_sent_log",
        "part8_threads",
        "part8_monologues",
        "part8_presence_state",
        "work_items",
        "sub_tasks",
        "contradictions",
        "session_emotions",
    } <= tables


@pytest.mark.integration
def test_schema_layer_initializes_without_crud_store_entrypoint(tmp_path):
    db_path = tmp_path / "schema-layer" / "archer.db"

    initialize_schema(db_path)

    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='memories'"
    ).fetchone()[0] == 1
    conn.close()
