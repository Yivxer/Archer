"""
Step 8 — Event-triggered Extraction Tests

测试重点：
1. _bg_extract 在独立线程中运行，不阻塞调用方
2. _wait_for_extract 等待后台线程结束
3. 并发保护：若后台线程还在运行，_bg_extract 不重复启动
4. _auto_extract 正确调用 extract() 并走 _stage_memories 路径
"""
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _setup_tmp_db(tmp: str):
    import memory.store as store_mod
    store_mod.DB_PATH = Path(tmp) / "test.db"
    store_mod.init_db()
    return store_mod


_SAMPLE_HISTORY = [
    {"role": "user",      "content": "我决定把所有精力放在 Archer 项目上"},
    {"role": "assistant", "content": "明白，这是个重大决策。"},
    {"role": "user",      "content": "未来三个月全力投入"},
    {"role": "assistant", "content": "好的，我会记录这个方向。"},
]


# ── _bg_extract 后台线程 ───────────────────────────────────────────────────────

def test_bg_extract_runs_in_background():
    """_bg_extract 应在非主线程中运行。"""
    import archer
    archer._extract_thread = None

    called_in_thread = []

    def fake_auto_extract(history, silent=False):
        called_in_thread.append(threading.current_thread() is not threading.main_thread())
        time.sleep(0.05)

    with patch.object(archer, "_auto_extract", fake_auto_extract):
        archer._bg_extract(_SAMPLE_HISTORY)
        # 调用方立即返回，后台线程还在
        archer._wait_for_extract(timeout=2.0)

    assert called_in_thread, "_auto_extract 未被调用"
    assert called_in_thread[0], "_auto_extract 应在非主线程中运行"


def test_bg_extract_skips_if_already_running():
    """后台线程仍在运行时，再次调用 _bg_extract 应跳过。"""
    import archer
    archer._extract_thread = None

    call_count = []

    def slow_auto_extract(history, silent=False):
        call_count.append(1)
        time.sleep(0.15)

    with patch.object(archer, "_auto_extract", slow_auto_extract):
        archer._bg_extract(_SAMPLE_HISTORY)
        time.sleep(0.02)  # 确保线程已启动
        archer._bg_extract(_SAMPLE_HISTORY)  # 应跳过
        archer._wait_for_extract(timeout=2.0)

    assert len(call_count) == 1, f"_auto_extract 被调用 {len(call_count)} 次，应只调用 1 次"


def test_wait_for_extract_blocks_until_done():
    """_wait_for_extract 应等待线程结束后才返回。"""
    import archer
    archer._extract_thread = None

    finished = []

    def slow_auto_extract(history, silent=False):
        time.sleep(0.1)
        finished.append(True)

    with patch.object(archer, "_auto_extract", slow_auto_extract):
        archer._bg_extract(_SAMPLE_HISTORY)
        archer._wait_for_extract(timeout=2.0)

    assert finished, "wait_for_extract 返回时后台线程应已完成"


def test_wait_for_extract_noop_when_no_thread():
    """没有后台线程时 _wait_for_extract 应无副作用地返回。"""
    import archer
    archer._extract_thread = None
    archer._wait_for_extract(timeout=1.0)  # 不应抛出异常


# ── _auto_extract 行为 ─────────────────────────────────────────────────────────

def test_auto_extract_calls_stage_memories():
    """_auto_extract 提炼到记忆时应调用 _stage_memories。"""
    import archer

    staged = []

    def fake_extract(history):
        return [
            {"content": "枫弋决定全力投入Archer", "type": "decision", "importance": 4,
             "tags": "archer", "confidence": 0.7, "obsidian_hint": ""}
        ], []

    def fake_stage(mems, source="auto", silent=False):
        staged.extend(mems)

    with patch("archer.extract", fake_extract), patch.object(archer, "_stage_memories", fake_stage):
        archer._auto_extract(_SAMPLE_HISTORY, silent=True)

    assert len(staged) == 1
    assert staged[0]["content"] == "枫弋决定全力投入Archer"


def test_auto_extract_skips_empty_history():
    """历史为空时 _auto_extract 应直接返回，不调用 extract。"""
    import archer

    called = []

    def fake_extract(history):
        called.append(True)
        return [], []

    with patch("archer.extract", fake_extract):
        archer._auto_extract([], silent=True)

    assert not called, "空历史时不应调用 extract"


def test_auto_extract_handles_no_memories():
    """extract 返回空列表时不应报错。"""
    import archer

    def fake_extract(history):
        return [], []

    with patch("archer.extract", fake_extract):
        archer._auto_extract(_SAMPLE_HISTORY, silent=True)  # should not raise


def test_auto_extract_handles_exception():
    """extract 抛出异常时 _auto_extract 应静默处理。"""
    import archer

    def bad_extract(history):
        raise RuntimeError("模拟 LLM 调用失败")

    with patch("archer.extract", bad_extract):
        archer._auto_extract(_SAMPLE_HISTORY, silent=True)  # should not raise


# ── 每 6 轮触发，不再每 3 轮同步 ────────────────────────────────────────────────

def test_six_turn_trigger_uses_bg_extract():
    """每 6 轮应使用 _bg_extract（后台），而非 _auto_extract（同步）。"""
    import ast, inspect
    import archer

    src = inspect.getsource(archer.run)
    # 确认 turn_count % 6 存在
    assert "turn_count % 6" in src, "应改为每 6 轮触发"
    # 确认调用的是 _bg_extract 而非 _auto_extract
    tree = ast.parse(src)
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in ("_auto_extract", "_bg_extract")
    ]
    bg_calls = [c for c in calls if c == "_bg_extract"]
    sync_calls = [c for c in calls if c == "_auto_extract"]
    # _bg_extract 至少 1 次（每 6 轮），_auto_extract 可出现在 exit 路径
    assert bg_calls, "run() 中应存在 _bg_extract 调用"
    # 直接的 turn_count 触发不应是同步的
    assert "turn_count % 3" not in src, "旧的每 3 轮同步调用应已移除"


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_bg_extract_runs_in_background,
        test_bg_extract_skips_if_already_running,
        test_wait_for_extract_blocks_until_done,
        test_wait_for_extract_noop_when_no_thread,
        test_auto_extract_calls_stage_memories,
        test_auto_extract_skips_empty_history,
        test_auto_extract_handles_no_memories,
        test_auto_extract_handles_exception,
        test_six_turn_trigger_uses_bg_extract,
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
