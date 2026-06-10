"""终端主循环与桌面共用的技能意图过滤。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.desktop_tool_router import filter_skills_for_intent
from core.skill_router import select_skills


class TestTerminalSkillIntentFilter(unittest.TestCase):
    def test_plain_article_strips_tools_after_router(self):
        skills = {
            "web_search": object(),
            "file_ops": object(),
            "shell": object(),
        }
        raw = select_skills("按照这个逻辑，帮我生成一篇大概500字的文章", skills)
        filtered = filter_skills_for_intent(
            "按照这个逻辑，帮我生成一篇大概500字的文章",
            raw,
            intent="chat",
        )
        self.assertEqual(filtered, {})

    def test_emotional_query_strips_web_search(self):
        raw = {"web_search": object(), "shell": object()}
        filtered = filter_skills_for_intent("为什么我会这么焦虑", raw, intent="emotional")
        self.assertNotIn("web_search", filtered)

    def test_terminal_imports_filter_in_turn_path(self):
        import terminal.archer as archer_mod

        source = open(archer_mod.__file__, encoding="utf-8").read()
        self.assertIn("filter_skills_for_intent", source)


if __name__ == "__main__":
    unittest.main()
