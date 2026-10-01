"""Natural recall and cross-process continuity in disposable databases."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import memory.store as store
from memory.retrieve import for_context
from memory.thread_context import register_thread_session, update_thread_context

CASES = json.loads((Path(__file__).parents[1] / "evals/foundation_memory_cases.json").read_text())["cases"]


def test_thirty_natural_recall_questions_with_unrelated_distractors(tmp_path, monkeypatch, record_property):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "memory.db")
    monkeypatch.setattr("memory.embedder.is_warmed", lambda: False)
    monkeypatch.setattr(store, "_try_embed", lambda *args: None)
    store.init_db()
    for case in CASES:
        store.save(case["content"], tags=case["topic"], type="fact", importance=3)
    store.save("无关事实：火星种植实验还没有确定浇水方案。", type="fact", importance=3)
    correct = injected = irrelevant = 0
    for case in CASES:
        core, related = for_context(case["question"], limit=5, intent="chat")
        contents = [item["content"] for item in core + related]
        correct += any(case["expected"] in text for text in contents)
        injected += len(contents)
        irrelevant += sum(case["content"] != text for text in contents)
    assert correct / len(CASES) >= 0.9, f"recall={correct}/{len(CASES)}"
    assert irrelevant / max(injected, 1) < 0.05, f"irrelevant={irrelevant}/{injected}"
    record_property("recall", f"{correct}/{len(CASES)}")
    record_property("irrelevant", f"{irrelevant}/{injected}")
    assert for_context("关于量子烹饪，上次定的是什么？", intent="chat") == ([], [])
    assert for_context("我想改变写作原则，你怎么看？", intent="chat") == ([], [])
    assert for_context("关于写作原则，替我编一个新的。", intent="chat") == ([], [])


def test_ten_threads_restore_their_own_goal_decisions_and_stop_after_restart(tmp_path, record_property):
    db_path = tmp_path / "threads.db"
    expected = {}
    for index, case in enumerate(CASES[:10]):
        thread = f"foundation-thread-{index}"
        goal = f"目标：核对{case['topic']}"
        decision = f"决定：{case['content']}"
        correction = f"不对，纠正为只处理{case['topic']}"
        stop = f"接下来继续核验{case['topic']}，尚未完成"
        messages = [
            {"role": "user", "content": goal},
            {"role": "assistant", "content": decision},
            {"role": "user", "content": correction},
            {"role": "assistant", "content": "已确认范围"},
            {"role": "user", "content": stop},
        ]
        update_thread_context(thread, messages, db_path=db_path)
        for session in (f"{thread}-first", f"{thread}-second", f"{thread}-second"):
            register_thread_session(thread, session, db_path=db_path)
        expected[thread] = (goal, decision, correction, stop)
    script = """
import json, sys
from memory.thread_context import get_thread_context
print(json.dumps({thread: get_thread_context(thread, db_path=sys.argv[1])
                  for thread in json.loads(sys.argv[2])}, ensure_ascii=False))
"""
    restored = json.loads(subprocess.check_output(
        [sys.executable, "-c", script, str(db_path), json.dumps(list(expected))],
        cwd=Path(__file__).parents[1], text=True,
    ))
    for thread, (goal, decision, correction, stop) in expected.items():
        state = restored[thread]["contextState"]
        assert state["goal"] == goal
        assert decision in state["decisions"]
        assert correction in state["corrections"]
        assert stop in state["pending"]
        assert restored[thread]["lastStop"] == stop
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT count(*) FROM conversation_thread_sessions").fetchone()[0] == 20
    record_property("restored_threads", "10/10")
