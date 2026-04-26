"""
Step 1 — ToolRuntime Tests
验证 timeout / 异常 / 截断 / 不存在技能 四类边界。
"""
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _make_skill(name: str, run_fn, timeout: int = 30):
    mod = types.ModuleType(name)
    mod.SKILL = {"name": name, "default_timeout": timeout}
    mod.schema = lambda: {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}
    mod.run = run_fn
    return mod


# ─── 1. 正常短结果 ─────────────────────────────────────────────────────────────

def test_runtime_success_short():
    """短结果直接内联，不写 artifact。"""
    import core.artifacts as art_mod
    with tempfile.TemporaryDirectory() as tmp:
        art_mod.ARTIFACTS_DIR = Path(tmp)
        from core.tool_runtime import invoke

        skill = _make_skill("echo", lambda args: "hello world")
        skills = {"echo": skill}
        tr = invoke("echo", {}, skills)

        assert tr.ok
        assert tr.skill == "echo"
        assert tr.truncated is False
        assert tr.artifact_path is None
        assert "hello world" in tr.content_preview
        assert tr.meta.get("duration_ms") is not None


# ─── 2. 超时 ──────────────────────────────────────────────────────────────────

def test_runtime_timeout():
    """技能超时时返回 ok=False，error.type == TimeoutError，REPL 不卡死。"""
    import core.artifacts as art_mod
    with tempfile.TemporaryDirectory() as tmp:
        art_mod.ARTIFACTS_DIR = Path(tmp)
        from core.tool_runtime import invoke

        def slow(_): time.sleep(60)
        skill = _make_skill("slow_skill", slow, timeout=1)
        skills = {"slow_skill": skill}

        start = time.time()
        tr = invoke("slow_skill", {}, skills)
        elapsed = time.time() - start

        assert not tr.ok
        assert tr.error["type"] == "TimeoutError"
        assert tr.error["retryable"] is True
        assert elapsed < 5, f"超时保护失效，等待了 {elapsed:.1f}s"


# ─── 3. 技能内部异常 ───────────────────────────────────────────────────────────

def test_runtime_exception():
    """技能内部抛异常，返回 ok=False，异常类型被保留，主循环不崩溃。"""
    import core.artifacts as art_mod
    with tempfile.TemporaryDirectory() as tmp:
        art_mod.ARTIFACTS_DIR = Path(tmp)
        from core.tool_runtime import invoke

        def broken(_): raise ValueError("something went wrong")
        skill = _make_skill("broken", broken)
        skills = {"broken": skill}
        tr = invoke("broken", {}, skills)

        assert not tr.ok
        assert tr.error["type"] == "ValueError"
        assert "something went wrong" in tr.error["message"]
        assert tr.error["retryable"] is False


# ─── 4. 超长结果截断 ───────────────────────────────────────────────────────────

def test_runtime_truncation():
    """超过 MAX_INLINE_CHARS 的结果存 artifact，messages 只收到预览。"""
    import core.artifacts as art_mod
    import core.tool_runtime as rt_mod
    with tempfile.TemporaryDirectory() as tmp:
        art_mod.ARTIFACTS_DIR = Path(tmp)
        from core.tool_runtime import invoke, MAX_INLINE_CHARS, PREVIEW_CHARS

        long_content = "x" * (MAX_INLINE_CHARS + 1000)
        skill = _make_skill("big", lambda _: long_content)
        skills = {"big": skill}
        tr = invoke("big", {}, skills)

        assert tr.ok
        assert tr.truncated is True
        assert tr.artifact_path is not None
        assert tr.artifact_path.exists()
        assert tr.artifact_path.read_text(encoding="utf-8") == long_content

        msg = tr.to_message_content()
        assert len(msg) < MAX_INLINE_CHARS, "截断后 message 仍然过长"
        assert "artifact" in msg


# ─── 5. 技能不存在 ─────────────────────────────────────────────────────────────

def test_runtime_skill_not_found():
    """调用不存在的技能返回 ok=False，error.type == SkillNotFound。"""
    from core.tool_runtime import invoke
    tr = invoke("ghost_skill", {}, {})
    assert not tr.ok
    assert tr.error["type"] == "SkillNotFound"
    assert tr.error["retryable"] is False


# ─── 6. to_message_content 格式 ────────────────────────────────────────────────

def test_message_content_error_format():
    """错误结果的 message 包含 type 和 retryable 字段。"""
    from core.tool_runtime import ToolResult
    tr = ToolResult(
        ok=False, skill="s", summary="失败",
        error={"type": "TimeoutError", "message": "...", "retryable": True},
    )
    msg = tr.to_message_content()
    assert "TimeoutError" in msg
    assert "retryable: True" in msg


# ─── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_runtime_success_short,
        test_runtime_timeout,
        test_runtime_exception,
        test_runtime_truncation,
        test_runtime_skill_not_found,
        test_message_content_error_format,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
