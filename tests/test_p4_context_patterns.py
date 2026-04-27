"""P4: Context Builder 三层上下文 + Pattern 质量约束"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── helpers ───────────────────────────────────────────────────────────────────

def _tmp_store():
    import memory.store as store_mod
    tmp = tempfile.mkdtemp()
    store_mod.DB_PATH = Path(tmp) / "test.db"
    store_mod.init_db()
    return store_mod, Path(tmp)


def _set_date(db_path, mem_id: int, date_str: str):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE memories SET created_at = ? WHERE id = ?", (date_str, mem_id))
    conn.commit()
    conn.close()


# ── is_heavy_query ─────────────────────────────────────────────────────────────

class TestIsHeavyQuery(unittest.TestCase):
    def setUp(self):
        from core.context import is_heavy_query
        self.heavy = is_heavy_query

    def test_long_input_is_heavy(self):
        self.assertTrue(self.heavy("这是一个超过五十个字符的长输入，通常代表着复杂的问题和深度的思考，不是简单打招呼"))

    def test_decision_keyword_is_heavy(self):
        for kw in ["建议", "该不该", "怎么办", "规划", "复盘"]:
            self.assertTrue(self.heavy(kw), f"关键词 {kw!r} 应触发 heavy")

    def test_greeting_is_not_heavy(self):
        for text in ["你好", "hi", "在吗", "ok"]:
            self.assertFalse(self.heavy(text), f"{text!r} 不应触发 heavy")

    def test_short_neutral_is_not_heavy(self):
        self.assertFalse(self.heavy("今天天气不错"))
        self.assertFalse(self.heavy("最近在读什么书"))


# ── Context Builder 三层 ───────────────────────────────────────────────────────

class TestContextBuilder(unittest.TestCase):
    def _make_cfg(self, soul_path="", memory_path=""):
        return {
            "persona": {
                "soul_path": soul_path,
                "memory_path": memory_path,
                "default_mode": "coach",
                "modes": {"coach": {"name": "教练", "prompt": "教练模式"}},
            }
        }

    def test_heavy_false_skips_memory_md(self):
        from core.context import build_system_prompt
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("MEMORY_CONTENT_MARKER")
            mem_path = f.name
        try:
            cfg = self._make_cfg(memory_path=mem_path)
            prompt = build_system_prompt(cfg, heavy=False)
            self.assertNotIn("MEMORY_CONTENT_MARKER", prompt)
        finally:
            os.unlink(mem_path)

    def test_heavy_true_includes_memory_md(self):
        from core.context import build_system_prompt
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("MEMORY_CONTENT_MARKER")
            mem_path = f.name
        try:
            cfg = self._make_cfg(memory_path=mem_path)
            prompt = build_system_prompt(cfg, heavy=True)
            self.assertIn("MEMORY_CONTENT_MARKER", prompt)
        finally:
            os.unlink(mem_path)

    def test_project_context_injected(self):
        from core.context import build_system_prompt
        cfg = self._make_cfg()
        project = {"name": "Archer", "description": "个人 AI 终端", "status": "active"}
        events = [{"event_type": "reflect", "content": "P3完成", "created_at": "2026-04-27T10:00:00"}]
        prompt = build_system_prompt(cfg, project=project, project_events=events)
        self.assertIn("Archer", prompt)
        self.assertIn("P3完成", prompt)

    def test_no_project_no_project_section(self):
        from core.context import build_system_prompt
        cfg = self._make_cfg()
        prompt = build_system_prompt(cfg, project=None)
        self.assertNotIn("当前项目", prompt)

    def test_db_memories_always_injected(self):
        from core.context import build_system_prompt
        cfg = self._make_cfg()
        prompt = build_system_prompt(cfg, db_memories="DB_MEM_MARKER", heavy=False)
        self.assertIn("DB_MEM_MARKER", prompt)


# ── Pattern 质量约束 ───────────────────────────────────────────────────────────

class TestPatternQualityConstraints(unittest.TestCase):
    def _run_detect(self, store_mod, response_json: str) -> list:
        import memory.store as orig_store
        orig_db = orig_store.DB_PATH
        orig_store.DB_PATH = store_mod.DB_PATH
        try:
            import memory.patterns as pat_mod
            def _mock(*a, **kw):
                yield response_json
            with patch("memory.patterns.stream_chat", _mock):
                return pat_mod.detect_and_save()
        finally:
            orig_store.DB_PATH = orig_db

    def test_rejects_theme_with_long_name(self):
        """名称超过12字的主题被拒绝。"""
        store_mod, tmp = _tmp_store()
        m1 = store_mod.save("记忆一内容测试", type="insight", importance=4)
        m2 = store_mod.save("记忆二内容测试", type="insight", importance=4)
        _set_date(store_mod.DB_PATH, m1, "2026-04-01T10:00:00")
        _set_date(store_mod.DB_PATH, m2, "2026-04-02T10:00:00")
        for _ in range(2):
            store_mod.save("填充记忆", type="insight", importance=4)

        response = f'{{"themes":[{{"name":"这个名称超过了十二个字符的限制","description":"测试","category":"behavior","links":[{{"memory_id":{m1},"strength":0.9}},{{"memory_id":{m2},"strength":0.7}}]}}]}}'
        saved = self._run_detect(store_mod, response)
        self.assertEqual(len(saved), 0)

    def test_rejects_theme_with_single_evidence(self):
        """只有1条证据的主题被拒绝。"""
        store_mod, tmp = _tmp_store()
        m1 = store_mod.save("唯一记忆内容", type="insight", importance=4)
        for _ in range(3):
            store_mod.save("填充记忆内容", type="insight", importance=4)

        response = f'{{"themes":[{{"name":"单证据主题","description":"测试","category":"behavior","links":[{{"memory_id":{m1},"strength":0.9}}]}}]}}'
        saved = self._run_detect(store_mod, response)
        self.assertEqual(len(saved), 0)

    def test_rejects_theme_without_cross_date_span(self):
        """所有证据在同一天创建的主题被拒绝。"""
        store_mod, tmp = _tmp_store()
        m1 = store_mod.save("同日记忆甲", type="insight", importance=4)
        m2 = store_mod.save("同日记忆乙", type="insight", importance=4)
        # 同日期 → 应被拒绝
        _set_date(store_mod.DB_PATH, m1, "2026-04-01T09:00:00")
        _set_date(store_mod.DB_PATH, m2, "2026-04-01T15:00:00")
        for _ in range(2):
            store_mod.save("填充记忆", type="insight", importance=4)

        response = f'{{"themes":[{{"name":"同日主题测试","description":"测试","category":"behavior","links":[{{"memory_id":{m1},"strength":0.9}},{{"memory_id":{m2},"strength":0.7}}]}}]}}'
        saved = self._run_detect(store_mod, response)
        self.assertEqual(len(saved), 0)

    def test_accepts_valid_theme(self):
        """满足所有约束的主题正常保存。"""
        store_mod, tmp = _tmp_store()
        m1 = store_mod.save("跨日记忆甲内容", type="insight", importance=4)
        m2 = store_mod.save("跨日记忆乙内容", type="insight", importance=4)
        _set_date(store_mod.DB_PATH, m1, "2026-04-01T10:00:00")
        _set_date(store_mod.DB_PATH, m2, "2026-04-03T10:00:00")
        for _ in range(2):
            store_mod.save("填充记忆内容", type="insight", importance=4)

        response = f'{{"themes":[{{"name":"工具研究模式","description":"模式描述","category":"behavior","links":[{{"memory_id":{m1},"strength":0.9}},{{"memory_id":{m2},"strength":0.7}}]}}]}}'
        saved = self._run_detect(store_mod, response)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["name"], "工具研究模式")


if __name__ == "__main__":
    unittest.main()
