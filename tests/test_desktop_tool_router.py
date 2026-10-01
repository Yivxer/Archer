"""桌面工具预检路由 core/desktop_tool_router.py 单元测试。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.desktop_tool_router import (
    HUGO_INTENT_ASK_CAPABILITY,
    HUGO_INTENT_CONTENT_REVIEW,
    HUGO_INTENT_DELETE_OR_UNPUBLISH,
    HUGO_INTENT_EXECUTE_PUBLISH,
    classify_hugo_intent,
    filter_skills_for_intent,
    is_hugo_capability_question,
    is_hugo_content_review_request,
    is_plain_content_request,
    parse_obsidian_write_request,
    plan_desktop_tools,
    plan_desktop_turn,
    score_github_intent,
    score_obsidian_write,
    score_shell_intent,
    should_trigger_github,
    should_trigger_shell,
    wants_hugo_publish,
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

    def test_obsidian_write_parser_feeds_score_args(self):
        query = "把这段写入「日记.md」：追加的新内容"
        parsed = parse_obsidian_write_request(query)
        conf, args = score_obsidian_write(query)

        self.assertGreaterEqual(conf, 0.55)
        self.assertEqual(parsed.path, "日记.md")
        self.assertEqual(parsed.mode, "append")
        self.assertEqual(parsed.body, "追加的新内容")
        self.assertEqual(args, {"path": parsed.path, "mode": parsed.mode, "body": parsed.body})

    def test_obsidian_edit_path_uses_overwrite_preview(self):
        query = "帮我润色一下/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/文章 初稿.md"
        parsed = parse_obsidian_write_request(query)
        conf, args = score_obsidian_write(query)

        self.assertGreaterEqual(conf, 0.55)
        self.assertEqual(parsed.mode, "overwrite")
        self.assertEqual(args["mode"], "overwrite")
        self.assertTrue(parsed.path.endswith("文章 初稿.md"))

    def test_hugo_capability_question_does_not_publish(self):
        query = "现在可以部署博客了吗？"
        self.assertTrue(is_hugo_capability_question(query))
        self.assertEqual(classify_hugo_intent(query), HUGO_INTENT_ASK_CAPABILITY)
        self.assertFalse(wants_hugo_publish(query))

    def test_local_article_revision_does_not_publish(self):
        for action in ("润色", "改写", "扩写", "缩写"):
            with self.subTest(action=action):
                query = f"帮我{action}一下/Users/test/vault/文章 初稿.md"
                self.assertEqual(classify_hugo_intent(query), HUGO_INTENT_CONTENT_REVIEW)
                self.assertFalse(wants_hugo_publish(query))

    def test_local_article_edit_keeps_existing_overwrite_preview(self):
        for action in ("润色", "改写"):
            with self.subTest(action=action):
                query = f"帮我{action}一下/Users/test/vault/文章 初稿.md"
                plan = plan_desktop_tools(query, {}, llm_fallback=False)
                self.assertTrue(plan.obsidian_write)
                self.assertEqual(parse_obsidian_write_request(query).mode, "overwrite")

    def test_revision_with_explicit_publish_command_still_publishes(self):
        query = "帮我润色后发布到博客 /Users/test/vault/文章 初稿.md"
        self.assertEqual(classify_hugo_intent(query), HUGO_INTENT_EXECUTE_PUBLISH)
        self.assertTrue(wants_hugo_publish(query))

    def test_hugo_image_capability_question_does_not_publish(self):
        query = "枫弋札记里好像没有办法部署图片你这边可以部署图片么？"
        self.assertTrue(is_hugo_capability_question(query))
        self.assertEqual(classify_hugo_intent(query), HUGO_INTENT_ASK_CAPABILITY)
        self.assertFalse(wants_hugo_publish(query))

    def test_explicit_hugo_deploy_still_publishes(self):
        self.assertEqual(classify_hugo_intent("帮我部署枫弋札记"), HUGO_INTENT_EXECUTE_PUBLISH)
        self.assertTrue(wants_hugo_publish("帮我部署枫弋札记"))

    def test_hugo_publish_path_with_spaces_still_publishes(self):
        query = (
            "帮我部署一篇文章到枫弋札记上"
            "/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/Archer 初衍的诞生日记·第一篇.md"
        )
        self.assertEqual(classify_hugo_intent(query), HUGO_INTENT_EXECUTE_PUBLISH)
        self.assertTrue(wants_hugo_publish(query))

    def test_hugo_delete_request_uses_hugo_workflow(self):
        self.assertEqual(classify_hugo_intent("把枫弋札记里的测试发布文章删除"), HUGO_INTENT_DELETE_OR_UNPUBLISH)
        self.assertTrue(wants_hugo_publish("把枫弋札记里的测试发布文章删除"))

    def test_hugo_content_review_with_past_deploy_mention_does_not_publish(self):
        query = (
            "我今天刚写完而妙的读后感，/Users/Yivxer/Library/Mobile Documents/"
            "iCloud~md~obsidian/Documents/个人知识管理系统/40创作输出/401文字/"
            "读书笔记/不存在另一半的灵魂，只有慢慢看清的自己.md，"
            "但是让你部署有点太慢了，我让 Codex 帮我部署了，你可以看看这一篇读后感如何"
        )
        self.assertTrue(is_hugo_content_review_request(query))
        self.assertEqual(classify_hugo_intent(query), HUGO_INTENT_CONTENT_REVIEW)
        self.assertFalse(wants_hugo_publish(query))


class TestTurnPlanIntegration(unittest.TestCase):
    def test_plain_article_filters_all_tools(self):
        query = "按照这个逻辑，帮我生成一篇大概500字的文章"
        turn = plan_desktop_turn(query, llm_fallback=False)
        self.assertTrue(turn.raw_selected)
        self.assertEqual(turn.filtered_skills, {})

    def test_writing_outline_analysis_filters_all_tools(self):
        query = "帮我分析一下写作的大纲：六月：悬置，好一点，再好一点。"
        self.assertTrue(is_plain_content_request(query))
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

    def test_hugo_upload_remains_candidate_when_intent_classifier_misses_tools(self):
        query = (
            "你好啊，帮我上传一篇文章到枫弋札记上，要保留原来的格式，标签是复盘；"
            "不用带里面的双链"
            "/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/"
            "个人知识管理系统/40创作输出/401文字/月度复盘/六月：悬置·好一点，再好一点.md"
        )
        skills = {
            "hugo_blog": object(),
            "obsidian_search": object(),
            "obsidian_write": object(),
            "file_ops": object(),
        }

        turn = plan_desktop_turn(query, skills, intent="writing", needs_tools=False, llm_fallback=False)

        self.assertIn("hugo_blog", turn.raw_selected)
        self.assertEqual(turn.filtered_skills, {})
        self.assertFalse(turn.tool_plan.obsidian_write)

    def test_hugo_image_capability_question_filters_hugo_tool(self):
        query = "枫弋札记里好像没有办法部署图片你这边可以部署图片么？"
        skills = {"hugo_blog": object(), "web_search": object()}

        turn = plan_desktop_turn(query, skills, intent="chat", needs_tools=True, llm_fallback=False)

        self.assertNotIn("hugo_blog", turn.filtered_skills)

    def test_hugo_content_review_filters_hugo_tool(self):
        query = (
            "我让 Codex 帮我部署了，/Users/Yivxer/Library/Mobile Documents/"
            "iCloud~md~obsidian/Documents/读书笔记/不存在另一半的灵魂.md，"
            "你可以看看这一篇读后感如何"
        )
        skills = {"hugo_blog": object(), "obsidian_search": object()}

        turn = plan_desktop_turn(query, skills, intent="writing", needs_tools=True, llm_fallback=False)

        self.assertNotIn("hugo_blog", turn.filtered_skills)


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
