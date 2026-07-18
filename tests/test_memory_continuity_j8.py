from __future__ import annotations

import statistics
import time
from pathlib import Path

import memory.store as store
from memory.retrieve import for_context
from memory.thread_context import latest_thread_context, update_thread_context
from terminal.api.turn_pipeline import trim_model_messages


def test_j8_semantic_recall_and_warm_latency(tmp_path: Path, monkeypatch) -> None:
    original = store.DB_PATH
    store.DB_PATH = tmp_path / "archer.db"
    try:
        store.init_db()
        cases = [(f"archerfact{index:02d}", f"稳定事实 {index:02d}") for index in range(30)]
        for query, expected in cases:
            store.save(f"{query} {expected}", type="fact", importance=3)
        monkeypatch.setattr("memory.embedder.is_warmed", lambda: False)

        correct = 0
        injected = 0
        irrelevant = 0
        durations: list[float] = []
        for query, expected in cases:
            started = time.perf_counter()
            core, related = for_context(query, limit=5, intent="chat")
            durations.append((time.perf_counter() - started) * 1000)
            contents = [str(item.get("content", "")) for item in core + related]
            correct += int(any(expected in content for content in contents))
            injected += len(contents)
            irrelevant += sum(expected not in content for content in contents)

        assert correct / len(cases) >= 0.90
        assert irrelevant / max(1, injected) < 0.05
        assert statistics.quantiles(durations, n=20)[18] < 300
    finally:
        store.DB_PATH = original


def test_j8_resume_returns_exact_latest_thread(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    for index in range(10):
        update_thread_context(
            f"thread-{index}",
            [
                {"role": "user", "content": f"目标 {index}"},
                {"role": "assistant", "content": f"结论 {index}"},
                {"role": "user", "content": f"接下来继续任务 {index}"},
            ],
            db_path=db_path,
        )
        latest = latest_thread_context(db_path=db_path)
        assert latest is not None
        assert latest["threadId"] == f"thread-{index}"
        assert latest["lastStop"] == f"接下来继续任务 {index}"


def test_j8_eighty_message_context_preserves_semantics() -> None:
    messages = [{"role": "system", "content": "safety"}]
    for index in range(40):
        user = "初始目标：完成 Archer 上下文记忆" if index == 0 else f"用户消息 {index}"
        if index == 8:
            user = "不对，纠正为先做 Part 10"
        if index == 15:
            user = "接下来还要完成 J8"
        messages.extend([
            {"role": "user", "content": user},
            {"role": "assistant", "content": f"已确认结论 {index}"},
        ])
    messages.extend([
        {"role": "user", "content": "最近任务：验证安装版"},
        {"role": "assistant", "content": "等待执行最短 smoke"},
    ])

    trimmed = trim_model_messages(messages, keep_recent=20, threshold=36)
    joined = "\n".join(str(item.get("content", "")) for item in trimmed)
    assert "初始目标：完成 Archer 上下文记忆" in joined
    assert "纠正为先做 Part 10" in joined
    assert "接下来还要完成 J8" in joined
    assert "最近任务：验证安装版" in joined
