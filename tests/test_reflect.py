"""
Step 5 — /reflect Tests

分两层：
1. _reflect_to_text() 纯函数测试（无 LLM）
2. _reflect() 集成测试（mock stream_chat）
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── 1. _reflect_to_text() 纯函数 ──────────────────────────────────────────────

def test_reflect_to_text_full():
    from archer import _reflect_to_text
    data = {
        "summary": "讨论了 Archer 的架构方向",
        "user_intent": "决定 P0 优先级",
        "decisions": ["先做安全层", "暂缓 MCP"],
        "open_questions": ["向量检索用哪个库"],
        "next_actions": ["实现 ToolRuntime"],
        "memory_candidates": [{"content": "优先安全", "type": "decision", "importance": 4}],
    }
    text = _reflect_to_text(data)
    assert "讨论了 Archer 的架构方向" in text
    assert "决策" in text
    assert "先做安全层" in text
    assert "未解问题" in text
    assert "向量检索" in text
    assert "下一步行动" in text
    assert "1 条记忆候选" in text


def test_reflect_to_text_empty_data():
    from archer import _reflect_to_text
    text = _reflect_to_text({})
    assert text == "复盘完成，无关键信息。"


def test_reflect_to_text_partial():
    from archer import _reflect_to_text
    data = {"summary": "简短总结", "decisions": ["决定A"]}
    text = _reflect_to_text(data)
    assert "简短总结" in text
    assert "决定A" in text
    assert "未解问题" not in text  # 没有就不显示


def test_reflect_to_text_no_candidates():
    from archer import _reflect_to_text
    data = {"summary": "本次没有需要记录的内容", "memory_candidates": []}
    text = _reflect_to_text(data)
    assert "已提炼" not in text  # 空候选时不显示记忆候选行


# ── 2. _reflect() 集成测试（mock LLM + DB + artifacts）───────────────────────

def _mock_stream(json_data: dict):
    """返回一个模拟 stream_chat 的生成器，产出 JSON 字符串的每个字符。"""
    raw = json.dumps(json_data, ensure_ascii=False)
    def _gen(*args, **kwargs):
        yield raw
    return _gen


class _FakeSession:
    def __init__(self, history=None):
        self.history = history if history is not None else [
            {"role": "user",      "content": "你好"},
            {"role": "assistant", "content": "你好，有什么我可以帮你的？"},
        ]
        self.added = []

    def add(self, user: str, assistant: str):
        self.added.append((user, assistant))
        self.history.append({"role": "user",      "content": user})
        self.history.append({"role": "assistant", "content": assistant})


_SAMPLE_DATA = {
    "summary": "讨论了 Archer 架构",
    "user_intent": "决定下一步优先级",
    "decisions": ["先做 ToolRuntime"],
    "open_questions": ["MCP 何时介入"],
    "memory_candidates": [
        {"content": "优先安全稳定", "type": "decision", "importance": 4}
    ],
    "next_actions": ["实现 Step 1"],
}


def test_reflect_enters_history():
    """_reflect() 结果写入 session.history，可以追问。"""
    import memory.store as store_mod
    import core.artifacts as art_mod

    with tempfile.TemporaryDirectory() as tmp:
        store_mod.DB_PATH = Path(tmp) / "test.db"
        store_mod.init_db()
        art_mod.ARTIFACTS_DIR = Path(tmp) / ".artifacts"

        session = _FakeSession()
        with patch("archer.stream_chat", _mock_stream(_SAMPLE_DATA)):
            from archer import _reflect
            _reflect(session)

        assert len(session.added) == 1, "应有一条 (user, assistant) 加入历史"
        user_msg, assistant_msg = session.added[0]
        assert user_msg == "[/reflect]"
        assert "讨论了 Archer 架构" in assistant_msg


def test_reflect_stages_memory_candidates():
    """memory_candidates 写入 pending_memories。"""
    import memory.store as store_mod
    import core.artifacts as art_mod

    with tempfile.TemporaryDirectory() as tmp:
        store_mod.DB_PATH = Path(tmp) / "test.db"
        store_mod.init_db()
        art_mod.ARTIFACTS_DIR = Path(tmp) / ".artifacts"

        session = _FakeSession()
        with patch("archer.stream_chat", _mock_stream(_SAMPLE_DATA)):
            from archer import _reflect
            _reflect(session)

        pends = store_mod.list_pending()
        assert len(pends) == 1
        assert pends[0]["content"] == "优先安全稳定"
        assert pends[0]["type"] == "decision"
        assert pends[0]["importance"] == 4


def test_reflect_saves_summary_as_reflection_memory():
    """summary 保存为 type='reflection' 的记忆。"""
    import memory.store as store_mod
    import core.artifacts as art_mod

    with tempfile.TemporaryDirectory() as tmp:
        store_mod.DB_PATH = Path(tmp) / "test.db"
        store_mod.init_db()
        art_mod.ARTIFACTS_DIR = Path(tmp) / ".artifacts"

        session = _FakeSession()
        with patch("archer.stream_chat", _mock_stream(_SAMPLE_DATA)):
            from archer import _reflect
            _reflect(session)

        mems = store_mod.list_all(10)
        reflection_mems = [m for m in mems if m.get("type") == "reflection"]
        assert len(reflection_mems) == 1
        assert reflection_mems[0]["content"] == "讨论了 Archer 架构"


def test_reflect_saves_artifact():
    """完整 JSON 保存到 .artifacts/reflections/。"""
    import memory.store as store_mod
    import core.artifacts as art_mod

    with tempfile.TemporaryDirectory() as tmp:
        store_mod.DB_PATH = Path(tmp) / "test.db"
        store_mod.init_db()
        art_mod.ARTIFACTS_DIR = Path(tmp) / ".artifacts"

        session = _FakeSession()
        with patch("archer.stream_chat", _mock_stream(_SAMPLE_DATA)):
            from archer import _reflect
            _reflect(session)

        reflections_dir = Path(tmp) / ".artifacts" / "reflections"
        files = list(reflections_dir.rglob("*.txt"))
        assert len(files) == 1
        saved = json.loads(files[0].read_text(encoding="utf-8"))
        assert saved["summary"] == "讨论了 Archer 架构"


def test_reflect_short_history_skips():
    """对话太短时直接返回，不调用 LLM。"""
    import memory.store as store_mod
    import core.artifacts as art_mod

    with tempfile.TemporaryDirectory() as tmp:
        store_mod.DB_PATH = Path(tmp) / "test.db"
        store_mod.init_db()
        art_mod.ARTIFACTS_DIR = Path(tmp) / ".artifacts"

        session = _FakeSession(history=[])  # 空历史
        called = []

        def mock_stream(*a, **k):
            called.append(True)
            return iter([])

        with patch("archer.stream_chat", mock_stream):
            from archer import _reflect
            _reflect(session)

        assert not called, "对话太短时不应调用 LLM"
        assert session.added == []


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_reflect_to_text_full,
        test_reflect_to_text_empty_data,
        test_reflect_to_text_partial,
        test_reflect_to_text_no_candidates,
        test_reflect_enters_history,
        test_reflect_stages_memory_candidates,
        test_reflect_saves_summary_as_reflection_memory,
        test_reflect_saves_artifact,
        test_reflect_short_history_skips,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
            passed += 1
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
