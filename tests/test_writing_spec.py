"""文章输出规范：profile 选择 + prompt 注入。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


class TestWritingProfile(unittest.TestCase):
    def _cfg(self):
        return {"writing": {"spec_dir": str(ROOT / "writing"), "auto_profile": True}}

    def test_revise_profile_on_polish_request(self):
        from core.writing import resolve_writing_profile

        self.assertEqual(
            resolve_writing_profile("帮我检查语病，不要多加句子", self._cfg()),
            "revise",
        )

    def test_blog_profile(self):
        from core.writing import resolve_writing_profile

        self.assertEqual(resolve_writing_profile("写一篇博客札记", self._cfg()), "blog")

    def test_writer_mode_defaults_to_draft(self):
        from core.writing import resolve_writing_profile

        self.assertEqual(
            resolve_writing_profile("继续", self._cfg(), mode="writer"),
            "draft",
        )

    def test_no_match_returns_none(self):
        from core.writing import resolve_writing_profile

        self.assertIsNone(resolve_writing_profile("你好", self._cfg()))


class TestWritingPromptInjection(unittest.TestCase):
    def test_global_markdown_in_runtime_safety(self):
        from core.context import build_system_prompt

        cfg = {"persona": {"default_mode": "coach", "modes": {}}}
        prompt = build_system_prompt(cfg, heavy=False, intent="chat")
        self.assertIn("Markdown", prompt)
        self.assertNotIn("纯文本，不使用任何 Markdown", prompt)

    def test_revise_profile_injected(self):
        from core.context import build_system_prompt

        cfg = {
            "persona": {"default_mode": "coach", "modes": {}},
            "writing": {"spec_dir": str(ROOT / "writing"), "auto_profile": True},
        }
        prompt = build_system_prompt(
            cfg,
            heavy=False,
            intent="task",
            user_input="帮我润色这段，列出改动",
            writing_query="帮我润色这段，列出改动",
        )
        self.assertIn("[文章输出规范]", prompt)
        self.assertIn("[写作任务：修订 Revise]", prompt)
        self.assertIn("## 改动列表", prompt)

    def test_article_spec_always_injected(self):
        from core.context import build_system_prompt

        cfg = {
            "persona": {"default_mode": "coach", "modes": {}},
            "writing": {"spec_dir": str(ROOT / "writing"), "auto_profile": True},
        }
        prompt = build_system_prompt(cfg, heavy=False, intent="chat", user_input="你好")
        self.assertIn("[文章输出规范]", prompt)
        self.assertNotIn("[写作任务：修订 Revise]", prompt)


if __name__ == "__main__":
    unittest.main()
