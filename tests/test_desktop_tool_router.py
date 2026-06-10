"""桌面工具预检路由 core/desktop_tool_router.py 单元测试。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.desktop_tool_router import (
    filter_skills_for_intent,
    plan_desktop_tools,
    plan_desktop_turn,
    score_github_intent,
    score_shell_intent,
    should_trigger_github,
    should_trigger_shell,
)


class TestToolRouterScoring(unittest.TestCase):
    def test_shell_high_confidence_with_command(self):
        conf, args = score_shell_intent("执行 ls -la")
        self.assertGreaterEqual(conf, 0.65)
        self.assertIn("ls", args.get("command", ""))

    def test_shell_weak_without_command(self):
        conf, _ = score_shell_intent("帮我执行这个命令")
        self.assertGreaterEqual(conf, 0.55)
        self.assertTrue(should_trigger_shell("帮我执行这个命令"))

    def test_github_issue_list(self):
        self.assertTrue(should_trigger_github("列出 issue"))
        conf, args = score_github_intent("列出 issue")
        self.assertGreaterEqual(conf, 0.65)
        self.assertEqual(args["action"], "list_issues")

    def test_plain_chat_no_tools(self):
        plan = plan_desktop_tools("今天天气怎么样", {"shell": object(), "github_ops": object()})
        self.assertFalse(plan.should_run("shell"))
        self.assertFalse(plan.should_run("github_ops"))


class TestTurnPlanIntegration(unittest.TestCase):
    def test_plain_article_filters_all_tools(self):
        query = "按照这个逻辑，帮我生成一篇大概500字的文章"
        turn = plan_desktop_turn(query, llm_fallback=False)
        self.assertTrue(turn.raw_selected)
        self.assertEqual(turn.filtered_skills, {})

    def test_emotional_why_strips_web_search(self):
        raw = {"web_search": object(), "shell": object()}
        filtered = filter_skills_for_intent("为什么我会这么焦虑", raw, intent="emotional")
        self.assertNotIn("web_search", filtered)

    def test_turn_plan_single_pass(self):
        turn = plan_desktop_turn("执行 ls -la", intent="task", needs_tools=True, llm_fallback=False)
        self.assertIn("shell", turn.filtered_skills)
        self.assertTrue(turn.tool_plan.should_run("shell"))


class TestToolPlanLlmFallback(unittest.TestCase):
    def test_llm_plan_when_low_conf_and_needs_tools(self):
        with patch("core.desktop_tool_router._llm_plan_tools") as mock_plan:
            from core.desktop_tool_router import DesktopToolPlan, PreflightTool
            mock_plan.return_value = DesktopToolPlan(
                tools=[PreflightTool("shell", 0.8, {"command": "npm test"}, source="llm")],
            )
            plan = plan_desktop_tools(
                "帮我把这个跑一下",
                {"shell": object()},
                intent="task",
                needs_tools=True,
                llm_fallback=True,
            )
        self.assertTrue(plan.should_run("shell"))
        self.assertEqual(plan.get("shell").source, "llm")


if __name__ == "__main__":
    unittest.main()
