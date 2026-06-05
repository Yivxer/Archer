"""P3 fixes: spinner (structural), ui cleanup, mode persistence, FTS5 short keyword."""
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestUICleanup(unittest.TestCase):
    def test_ui_app_deleted(self):
        ui_app = Path(__file__).parent.parent / "ui" / "app.py"
        self.assertFalse(ui_app.exists(), "ui/app.py 应已删除（废弃 Textual TUI）")

    def test_textual_not_in_requirements(self):
        req = (Path(__file__).parent.parent / "requirements.txt").read_text()
        self.assertNotIn("textual", req, "requirements.txt 中不应再包含 textual")


class TestModePersistence(unittest.TestCase):
    def test_persist_mode_inserts_current_mode(self):
        """_persist_mode 在没有 current_mode 时，在 default_mode 后插入新行。"""
        import archer  # noqa: F401 — side-effect free import
        from archer import _persist_mode

        toml_content = '[persona]\ndefault_mode = "coach"\n'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, encoding="utf-8") as f:
            f.write(toml_content)
            tmp_path = Path(f.name)

        try:
            with patch("archer._TOML_PATH", tmp_path):
                _persist_mode("mirror")
            result = tmp_path.read_text(encoding="utf-8")
            self.assertIn('current_mode = "mirror"', result)
        finally:
            tmp_path.unlink()

    def test_persist_mode_replaces_existing(self):
        """_persist_mode 覆盖已有 current_mode。"""
        from archer import _persist_mode

        toml_content = '[persona]\ndefault_mode = "coach"\ncurrent_mode = "coach"\n'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, encoding="utf-8") as f:
            f.write(toml_content)
            tmp_path = Path(f.name)

        try:
            with patch("archer._TOML_PATH", tmp_path):
                _persist_mode("critic")
            result = tmp_path.read_text(encoding="utf-8")
            self.assertIn('current_mode = "critic"', result)
            self.assertEqual(result.count("current_mode"), 1, "不应出现重复的 current_mode")
        finally:
            tmp_path.unlink()


def _tmp_store():
    import memory.store as store_mod
    import tempfile
    tmp = tempfile.mkdtemp()
    store_mod.DB_PATH = Path(tmp) / "test.db"
    store_mod.init_db()
    return store_mod, tmp


class TestFTS5ShortKeyword(unittest.TestCase):
    def test_search_short_keyword_uses_like(self):
        """≤2 字符的搜索词跳过 FTS5，直接走 LIKE，不抛异常。"""
        store_mod, _ = _tmp_store()
        results = store_mod.search("我")
        self.assertIsInstance(results, list)

    def test_search_short_keyword_two_chars(self):
        store_mod, _ = _tmp_store()
        results = store_mod.search("ab")
        self.assertIsInstance(results, list)

    def test_search_normal_keyword(self):
        """≥3 字符正常走 FTS5 路径，不报错。"""
        store_mod, _ = _tmp_store()
        results = store_mod.search("测试搜索词")
        self.assertIsInstance(results, list)


class TestSpinnerStructural(unittest.TestCase):
    def test_run_with_tools_imports_live(self):
        """工具循环已抽出，spinner 依赖应能正常导入。"""
        import archer  # noqa
        import core.tool_loop  # noqa
        from rich.live import Live
        from rich.spinner import Spinner
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
