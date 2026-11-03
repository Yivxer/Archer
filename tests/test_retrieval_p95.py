"""Retrieval tail: FTS metacharacters must not scan the memories table.

Nearest-rank p95 of n=17 is the slowest sample (ceil(0.95 * 17) == 17).
A single MATCH syntax error used to fall back to LIKE '%question%' and
become that sample. Phrase-quoting keeps the trigram index on the hot path.
"""
from __future__ import annotations

import math
import sqlite3
import time
from pathlib import Path

import pytest

import memory.store as store
from memory.retrieve import for_context


def _nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = math.ceil(percentile / 100 * len(ordered))
    rank = min(max(rank, 1), len(ordered))
    return ordered[rank - 1]


@pytest.fixture
def retrieval_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "archer.db"
    monkeypatch.setattr(store, "DB_PATH", db_path)
    monkeypatch.setattr("memory.embedder.is_warmed", lambda: False)
    store.init_db()
    return db_path


def test_punctuation_query_uses_index_and_keeps_recall(retrieval_db: Path) -> None:
    quoted = '他说"封面"要核对后再发。'
    paren = "发布边界：核对原稿(封面)和标题后再发。"
    filler = "项目笔记保留范围依赖和验收标准。" * 8
    now = "2026-08-01T10:00:00"
    conn = sqlite3.connect(retrieval_db)
    rows = [
        (quoted, "bench", "fact", 4, 3, "active", "synthetic", now, now, "user", 0.8, "[]", "human", ""),
        (paren, "bench", "fact", 4, 3, "active", "synthetic", now, now, "user", 0.8, "[]", "human", ""),
    ]
    rows.extend(
        (f"{filler}编号{index:05d}", "bench", "insight", 3, 3, "active", "synthetic", now, now, "user", 0.8, "[]", "insight", "")
        for index in range(20_000)
    )
    conn.executemany(
        "INSERT INTO memories (content, tags, type, importance, depth, status, source, "
        "created_at, updated_at, scope, confidence, observed_at, block_type, label) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()

    queries = [
        "关于写作原则，上次定的是什么？",
        "关于改稿顺序，上次定的是什么？",
        "关于阅读计划，上次定的是什么？",
        "关于训练频率，上次定的是什么？",
        "关于恢复安排，上次定的是什么？",
        "我之前说过的发布节奏是什么",
        "我的阅读计划是怎么安排的？",
        "稳定事实每周三复盘",
        "项目依赖和验收标准",
        "本地语义检索目标",
        "向量索引和全文索引",
        "偏好先给结论再补依据",
        "风险是尾延迟不是中位数",
        "洞察把冷启动移出计时",
        "待办保持召回阈值",
        '说"封面"要核对',
        "原稿(封面)",
    ]
    assert len(queries) == 17

    search_durations: list[float] = []
    retrieval_durations: list[float] = []
    last_contents: list[str] = []
    quote_contents: list[str] = []
    for query in queries:
        started = time.perf_counter()
        store.search(query, limit=5)
        search_durations.append((time.perf_counter() - started) * 1000)

        started = time.perf_counter()
        core, related = for_context(query, limit=5, intent="chat")
        retrieval_durations.append((time.perf_counter() - started) * 1000)
        contents = [str(item.get("content", "")) for item in core + related]
        if query == "原稿(封面)":
            last_contents = contents
        if '"' in query:
            quote_contents = contents

    plain_median = _nearest_rank(search_durations[:15], 50)
    special = max(search_durations[15], search_durations[16])
    p50 = _nearest_rank(retrieval_durations, 50)
    p95 = _nearest_rank(retrieval_durations, 95)

    assert any("原稿(封面)" in content for content in last_contents)
    assert any('"封面"' in content for content in quote_contents)
    assert p95 < 300
    assert p50 < 300
    # Indexed phrase MATCH stays with the other queries. LIKE '%...%' does not.
    assert special <= plain_median * 4 + 3
