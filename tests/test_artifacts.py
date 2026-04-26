"""
Step 4 — Artifact Storage Tests
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _patch_dir(tmp: str):
    import core.artifacts as art
    art.ARTIFACTS_DIR = Path(tmp) / ".artifacts"
    return art


def test_save_tool_result():
    with tempfile.TemporaryDirectory() as tmp:
        art = _patch_dir(tmp)
        path = art.save_tool_result("web_fetch", "页面正文内容")
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "页面正文内容"
        assert "tool_results" in str(path)
        assert "web_fetch_" in path.name


def test_save_reflection():
    with tempfile.TemporaryDirectory() as tmp:
        art = _patch_dir(tmp)
        path = art.save_reflection('{"insights": ["洞察一"]}', label="reflect")
        assert path.exists()
        assert "reflections" in str(path)
        assert "reflect_" in path.name


def test_save_custom_type():
    with tempfile.TemporaryDirectory() as tmp:
        art = _patch_dir(tmp)
        path = art.save("摘要内容", artifact_type="summaries", prefix="compress")
        assert "summaries" in str(path)
        assert path.exists()


def test_save_invalid_type_fallback():
    """非法 artifact_type 回退到 tool_results。"""
    with tempfile.TemporaryDirectory() as tmp:
        art = _patch_dir(tmp)
        path = art.save("内容", artifact_type="nonexistent", prefix="x")
        assert "tool_results" in str(path)


def test_dir_size_empty():
    with tempfile.TemporaryDirectory() as tmp:
        art = _patch_dir(tmp)
        assert art.dir_size() == 0


def test_dir_size_after_write():
    with tempfile.TemporaryDirectory() as tmp:
        art = _patch_dir(tmp)
        content = "x" * 1000
        art.save_tool_result("skill", content)
        size = art.dir_size()
        assert size >= 1000


def test_fmt_size_bytes():
    import core.artifacts as art
    assert "B" in art.fmt_size(500)


def test_fmt_size_kb():
    import core.artifacts as art
    assert "KB" in art.fmt_size(2048)


def test_fmt_size_mb():
    import core.artifacts as art
    assert "MB" in art.fmt_size(2 * 1024 * 1024)


def test_multiple_saves_accumulate():
    with tempfile.TemporaryDirectory() as tmp:
        art = _patch_dir(tmp)
        art.save_tool_result("a", "x" * 500)
        art.save_tool_result("b", "y" * 500)
        assert art.dir_size() >= 1000


if __name__ == "__main__":
    tests = [
        test_save_tool_result,
        test_save_reflection,
        test_save_custom_type,
        test_save_invalid_type_fallback,
        test_dir_size_empty,
        test_dir_size_after_write,
        test_fmt_size_bytes,
        test_fmt_size_kb,
        test_fmt_size_mb,
        test_multiple_saves_accumulate,
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
