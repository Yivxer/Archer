"""P4: Orchestrator 每轮前置判断。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.orchestrator import (
    build_memory_candidate_policy,
    build_task_plan,
    format_memory_candidate_reason,
    format_mode_constraints_for_prompt,
    format_task_plan_for_prompt,
    has_actionable_side_effect,
    keyword_is_negated,
    orchestrate_user_input,
    orchestration_status_labels,
)


class TestOrchestratorSnapshot(unittest.TestCase):
    def test_project_planning_uses_builder_and_project_context(self):
        result = orchestrate_user_input("按照昨天的成长计划，开始优化 Archer 的 Orchestrator")

        self.assertEqual(result.intent, "project")
        self.assertEqual(result.sub_intent, "project_planning")
        self.assertEqual(result.mode, "builder")
        self.assertEqual(result.depth, "deep")
        self.assertTrue(result.needs_memory)
        self.assertTrue(result.needs_project_context)
        self.assertIn("project", result.memory_scope)
        self.assertIn("work", result.memory_scope)

    def test_manual_mode_has_priority_but_keeps_other_signals(self):
        result = orchestrate_user_input(
            "帮我润色这篇文章，减少 AI 味",
            manual_mode="critic",
        )

        self.assertEqual(result.mode, "critic")
        self.assertEqual(result.sub_intent, "writing_assistance")
        self.assertTrue(result.needs_memory)
        self.assertIn("writing_style", result.memory_scope)

    def test_emotional_reflection_does_not_need_tools_or_job(self):
        result = orchestrate_user_input("我最近很焦虑，很内耗，不知道怎么办")

        self.assertEqual(result.intent, "emotional")
        self.assertEqual(result.sub_intent, "emotional_reflection")
        self.assertIn(result.mode, {"listener", "therapist"})
        self.assertEqual(result.depth, "deep")
        self.assertTrue(result.needs_memory)
        self.assertFalse(result.needs_tools)
        self.assertFalse(result.needs_job)
        self.assertIn("soul", result.memory_scope)
        self.assertIn("emotion", result.memory_scope)

    def test_due_hypothesis_signal_marks_soul_insight_context(self):
        result = orchestrate_user_input(
            "我最近又开始焦虑了，想复盘一下",
            soul_insight={
                "due_hypotheses": [
                    {
                        "id": 7,
                        "title": "运动后情绪更稳定",
                        "statement": "连续三天力量训练后，晚间焦虑会下降。",
                    }
                ]
            },
        )

        self.assertIn("hypothesis", result.memory_scope)
        self.assertIn("soul_insight:due_hypotheses:1", result.reasons)
        self.assertEqual(result.soul_insight["due_hypotheses"][0]["id"], 7)
        self.assertIn("验证假设", orchestration_status_labels(result))

    def test_orchestration_event_includes_soul_insight_due_hypotheses(self):
        from core.orchestrator import orchestration_to_event_dict

        result = orchestrate_user_input(
            "我想复盘一下最近的状态",
            soul_insight={
                "due_hypotheses": [
                    {
                        "id": 7,
                        "title": "运动后情绪更稳定",
                        "statement": "连续三天力量训练后，晚间焦虑会下降。",
                    }
                ]
            },
        )

        event = orchestration_to_event_dict(result)

        self.assertEqual(event["soulInsight"]["dueHypotheses"][0]["id"], 7)
        self.assertIn("验证假设", event["labels"])

    def test_task_route_snapshot_is_authoritative_for_background_work(self):
        from core.orchestrator import OrchestrationResult, task_route_snapshot

        result = OrchestrationResult(
            intent="project",
            sub_intent="code_task",
            mode="builder",
            depth="deep",
            needs_job=True,
            side_effect_level="none",
        )

        self.assertEqual(task_route_snapshot(result), {
            "mode": "background",
            "reason": "python orchestrator requires background job",
            "title": "代码任务",
            "timeoutSeconds": 300,
        })

    def test_task_route_snapshot_keeps_approval_work_foreground(self):
        from core.orchestrator import OrchestrationResult, task_route_snapshot

        result = OrchestrationResult(
            intent="task",
            sub_intent="tool_task",
            mode="operator",
            depth="normal",
            needs_job=True,
            side_effect_level="approval_required",
        )

        self.assertEqual(task_route_snapshot(result)["mode"], "foreground")
        self.assertEqual(
            task_route_snapshot(result)["reason"],
            "approval-required task stays in foreground",
        )

    def test_task_route_snapshot_keeps_hugo_workflow_foreground(self):
        from core.orchestrator import OrchestrationResult, task_route_snapshot

        result = OrchestrationResult(
            intent="task",
            sub_intent="tool_task",
            mode="operator",
            depth="normal",
            needs_job=True,
            matched_skills=["hugo_blog"],
            side_effect_level="none",
        )

        self.assertEqual(task_route_snapshot(result)["mode"], "foreground")
        self.assertEqual(
            task_route_snapshot(result)["reason"],
            "hugo workflow stays in foreground",
        )

    def test_orchestration_event_includes_task_route_snapshot(self):
        from core.orchestrator import orchestration_to_event_dict

        result = orchestrate_user_input(
            "按照成长计划开始执行 Archer 路由重构",
        )

        event = orchestration_to_event_dict(result)

        self.assertEqual(event["taskRoute"]["timeoutSeconds"], 300)
        self.assertIn(event["taskRoute"]["mode"], {"foreground", "background"})

    def test_short_chat_stays_light_without_memory(self):
        result = orchestrate_user_input("在吗")

        self.assertEqual(result.intent, "chat")
        self.assertEqual(result.sub_intent, "casual_chat")
        self.assertEqual(result.mode, "coach")
        self.assertEqual(result.depth, "light")
        self.assertFalse(result.needs_memory)
        self.assertFalse(result.needs_tools)
        self.assertFalse(result.needs_job)

    def test_multi_step_obsidian_write_needs_job_and_approval(self):
        result = orchestrate_user_input("帮我把这篇文章提炼成方法论，并写入 Obsidian")

        self.assertEqual(result.sub_intent, "knowledge_summary")
        self.assertEqual(result.mode, "operator")
        self.assertEqual(result.depth, "deep")
        self.assertTrue(result.needs_memory)
        self.assertTrue(result.needs_tools)
        self.assertTrue(result.needs_job)
        self.assertEqual(result.side_effect_level, "approval_required")
        self.assertIn("obsidian", result.memory_scope)

    def test_builds_plan_for_obsidian_write_task(self):
        text = "帮我把这篇文章提炼成方法论，并写入 Obsidian"
        result = orchestrate_user_input(text)

        plan = build_task_plan(text, result)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("Obsidian", plan.task_title)
        actions = [step.action for step in plan.steps]
        self.assertEqual(actions, ["read_source", "summarize", "format_note", "write_obsidian"])
        self.assertTrue(plan.steps[-1].requires_approval)
        self.assertEqual(plan.steps[-1].tool, "obsidian_write")

    def test_no_plan_for_short_chat(self):
        result = orchestrate_user_input("在吗")

        self.assertIsNone(build_task_plan("在吗", result))

    def test_hugo_publish_from_obsidian_path_does_not_create_obsidian_write_plan(self):
        text = (
            "/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/"
            "个人知识管理系统/当训练变成习惯以后，人会对疲劳变得迟钝.md部署这一篇文章"
        )
        result = orchestrate_user_input(text)

        self.assertIsNone(build_task_plan(text, result))

    def test_readonly_writing_feedback_from_obsidian_path_does_not_create_write_plan(self):
        text = (
            "/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/"
            "个人知识管理系统/40创作输出/401文字/AI 心得/AI 算不出命，但能找见你.md"
            "这是 ChatGPT 写出来的初稿，我觉得 AI 味道太重，而且字数有点多，"
            "我需要你先用写作技能优化处理一下，先不要更改原文件，说说你的想法，我看看"
        )
        result = orchestrate_user_input(text)

        self.assertIsNone(build_task_plan(text, result))

    def test_article_review_from_obsidian_path_does_not_create_write_plan(self):
        text = (
            "/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/"
            "个人知识管理系统/40创作输出/401文字/AI 心得/AI 算不出命，但能照见你.md"
            "这厮最后的精修版本，你觉得怎么样？如果要调整的话还有哪些可以调整的地方？"
        )
        result = orchestrate_user_input(text)

        self.assertEqual(result.sub_intent, "writing_assistance")
        self.assertEqual(result.mode, "writer")
        self.assertEqual(result.side_effect_level, "none")
        self.assertFalse(result.needs_job)
        self.assertFalse(has_actionable_side_effect(text))
        self.assertIsNone(build_task_plan(text, result))

    def test_formats_plan_for_prompt_with_approval_marker(self):
        text = "帮我把这篇文章提炼成方法论，并写入 Obsidian"
        result = orchestrate_user_input(text)
        plan = build_task_plan(text, result)

        block = format_task_plan_for_prompt(plan)

        self.assertIn("[任务计划]", block)
        self.assertIn("write_obsidian", block)
        self.assertIn("需要确认", block)

    def test_memory_candidate_policy_skips_casual_chat(self):
        result = orchestrate_user_input("在吗")

        policy = build_memory_candidate_policy(result)

        self.assertFalse(policy.should_extract)
        self.assertEqual(policy.candidate_types, [])

    def test_memory_candidate_policy_for_project_update(self):
        result = orchestrate_user_input("Archer 下一阶段决定先做 Orchestrator 编排闭环")

        policy = build_memory_candidate_policy(result)

        self.assertTrue(policy.should_extract)
        self.assertIn("project_update", policy.candidate_types)
        self.assertTrue(policy.requires_review)

    def test_memory_candidate_policy_for_writing_preference(self):
        result = orchestrate_user_input("以后帮我改文章时，减少 AI 味，不要一句话一段")

        policy = build_memory_candidate_policy(result)

        self.assertTrue(policy.should_extract)
        self.assertIn("writing_preference", policy.candidate_types)

    def test_memory_candidate_policy_for_emotional_pattern_is_sensitive(self):
        result = orchestrate_user_input("我最近总是焦虑和内耗，反复卡在同一个地方")

        policy = build_memory_candidate_policy(result)

        self.assertTrue(policy.should_extract)
        self.assertIn("emotional_pattern", policy.candidate_types)
        self.assertTrue(policy.sensitive)
        self.assertTrue(policy.requires_review)


class TestContextMemoryScope(unittest.TestCase):
    def _cfg(self, memory_path: str) -> dict:
        return {
            "persona": {
                "memory_path": memory_path,
                "default_mode": "coach",
                "modes": {"coach": {"prompt": "教练模式"}},
            }
        }

    def test_memory_scope_can_skip_full_memory_md_for_writing(self):
        import os
        import tempfile

        from core.context import build_system_prompt

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("FULL_MEMORY_MARKER")
            memory_path = f.name
        try:
            prompt = build_system_prompt(
                self._cfg(memory_path),
                heavy=True,
                intent="task",
                memory_scope=["writing_style", "preferences"],
            )
            self.assertNotIn("FULL_MEMORY_MARKER", prompt)
        finally:
            os.unlink(memory_path)

    def test_memory_scope_includes_memory_md_for_project_work(self):
        import os
        import tempfile

        from core.context import build_system_prompt

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("FULL_MEMORY_MARKER")
            memory_path = f.name
        try:
            prompt = build_system_prompt(
                self._cfg(memory_path),
                heavy=False,
                intent="project",
                memory_scope=["project", "work"],
            )
            self.assertIn("FULL_MEMORY_MARKER", prompt)
        finally:
            os.unlink(memory_path)

    def test_task_plan_block_is_injected(self):
        from core.context import build_system_prompt

        prompt = build_system_prompt(
            self._cfg(""),
            heavy=False,
            intent="task",
            task_plan_block="[任务计划]\n1. read_source",
        )

        self.assertIn("[任务计划]", prompt)
        self.assertIn("read_source", prompt)

    def test_mode_constraint_block_is_injected(self):
        from core.context import build_system_prompt

        prompt = build_system_prompt(
            self._cfg(""),
            heavy=False,
            intent="emotional",
            mode_constraint_block="[回应约束]\n先复述",
        )

        self.assertIn("[回应约束]", prompt)
        self.assertIn("先复述", prompt)


class TestDesktopMemoryExtractionPolicy(unittest.TestCase):
    def test_desktop_extract_skips_casual_chat(self):
        from terminal.api._tools import _do_extract_api

        history = [
            {"role": "user", "content": "在吗"},
            {"role": "assistant", "content": "在。"},
        ]
        with patch("memory.extract.extract") as mock_extract:
            _do_extract_api(history)

        mock_extract.assert_not_called()

    def test_desktop_stream_emits_plan_event_for_obsidian_write(self):
        from terminal.api._tools import _iter_chat_chunks

        messages = [
            {"role": "user", "content": "帮我把这篇文章提炼成方法论，并写入 Obsidian"}
        ]
        chunks = []
        for chunk in _iter_chat_chunks(messages, memory_mode="off", obsidian_mode="off"):
            chunks.append(chunk)
            if chunk.get("type") == "ready":
                break

        plan_events = [chunk.get("planEvent") for chunk in chunks if chunk.get("type") == "planEvent"]
        self.assertEqual(len(plan_events), 1)
        self.assertEqual(plan_events[0]["steps"][-1]["tool"], "obsidian_write")
        self.assertIn("写入 Obsidian", plan_events[0]["prompt"])

    def test_desktop_stream_skips_plan_event_for_chat(self):
        from terminal.api._tools import _iter_chat_chunks

        messages = [{"role": "user", "content": "在吗"}]
        chunks = []
        for chunk in _iter_chat_chunks(messages, memory_mode="off", obsidian_mode="off"):
            chunks.append(chunk)
            if chunk.get("type") == "ready":
                break

        self.assertFalse(any(chunk.get("type") == "planEvent" for chunk in chunks))

    def test_desktop_stream_emits_orchestration_event(self):
        from terminal.api._tools import _iter_chat_chunks

        messages = [
            {"role": "user", "content": "按照成长计划，继续优化 Archer Orchestrator"}
        ]
        chunks = []
        for chunk in _iter_chat_chunks(messages, memory_mode="off", obsidian_mode="off"):
            chunks.append(chunk)
            if chunk.get("type") == "ready":
                break

        orch_events = [
            chunk.get("orchestrationEvent")
            for chunk in chunks
            if chunk.get("type") == "orchestrationEvent"
        ]
        self.assertEqual(len(orch_events), 1)
        self.assertEqual(orch_events[0]["subIntent"], "project_planning")
        self.assertIn("项目规划", orch_events[0]["labels"])

    def test_desktop_stream_orchestration_event_includes_due_hypothesis(self):
        import tempfile
        from datetime import datetime, timedelta
        from pathlib import Path

        import memory.store as store
        from memory.hypothesis_tracker import create_hypothesis
        from terminal.api._tools import _iter_chat_chunks

        original_db_path = store.DB_PATH
        with tempfile.TemporaryDirectory() as tmp:
            store.DB_PATH = Path(tmp) / "archer.db"
            try:
                store.init_db()
                create_hypothesis(
                    "运动后情绪更稳定",
                    "连续三天力量训练后，晚间焦虑会下降。",
                    validate_after_days=1,
                    now=datetime.now() - timedelta(days=3),
                )
                messages = [{"role": "user", "content": "我想复盘一下最近的焦虑"}]

                chunks = []
                for chunk in _iter_chat_chunks(messages, memory_mode="off", obsidian_mode="off"):
                    chunks.append(chunk)
                    if chunk.get("type") == "orchestrationEvent":
                        break

                event = next(chunk["orchestrationEvent"] for chunk in chunks if chunk.get("type") == "orchestrationEvent")
                self.assertIn("验证假设", event["labels"])
                self.assertEqual(event["soulInsight"]["dueHypotheses"][0]["title"], "运动后情绪更稳定")
            finally:
                store.DB_PATH = original_db_path


class TestModeConstraints(unittest.TestCase):
    def test_emotional_reflection_gets_listener_constraints(self):
        result = orchestrate_user_input("我最近很焦虑，很内耗，不知道怎么办")
        block = format_mode_constraints_for_prompt(result)

        self.assertIn("先复述", block)
        self.assertIn("不要急于给建议", block)

    def test_writing_assistance_gets_writer_constraints(self):
        result = orchestrate_user_input("帮我润色这篇文章，减少 AI 味")
        block = format_mode_constraints_for_prompt(result)

        self.assertIn("减少 AI 味", block)
        self.assertIn("不是博客发布", block)

    def test_project_planning_gets_minimal_loop_constraints(self):
        result = orchestrate_user_input("Archer 下一阶段先做 Orchestrator，怎么收口？")
        block = format_mode_constraints_for_prompt(result)

        self.assertIn("最小可验证闭环", block)


class TestNegatedSideEffects(unittest.TestCase):
    def test_negated_publish_does_not_trigger_side_effect(self):
        text = "请帮我润色下面这段，减少 AI 味，不要发布也不要保存文件。"
        result = orchestrate_user_input(text)

        self.assertEqual(result.sub_intent, "writing_assistance")
        self.assertEqual(result.side_effect_level, "none")
        self.assertFalse(result.needs_job)
        self.assertFalse(has_actionable_side_effect(text))
        self.assertTrue(keyword_is_negated(text, "发布"))

    def test_obsidian_path_with_readonly_writing_feedback_has_no_side_effect(self):
        text = (
            "/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/"
            "个人知识管理系统/40创作输出/401文字/AI 心得/AI 算不出命，但能找见你.md"
            "这是初稿，AI 味太重，先不要更改原文件，说说你的想法"
        )
        result = orchestrate_user_input(text)

        self.assertEqual(result.sub_intent, "writing_assistance")
        self.assertEqual(result.side_effect_level, "none")
        self.assertFalse(result.needs_job)
        self.assertFalse(has_actionable_side_effect(text))

    def test_actionable_publish_still_requires_approval(self):
        text = "帮我把这篇文章发布到 Obsidian"
        result = orchestrate_user_input(text)

        self.assertEqual(result.side_effect_level, "approval_required")
        self.assertTrue(has_actionable_side_effect(text))


class TestMemoryCandidateReason(unittest.TestCase):
    def test_format_memory_candidate_reason_includes_snippet(self):
        result = orchestrate_user_input("Archer 下一阶段决定先做 Orchestrator 编排闭环")
        policy = build_memory_candidate_policy(result)
        reason = format_memory_candidate_reason(policy, "Archer 下一阶段决定先做 Orchestrator 编排闭环")

        self.assertIn("项目进展", reason)
        self.assertIn("来自：", reason)

    def test_pending_memory_stores_suggest_reason(self):
        import tempfile
        import memory.store as store_mod

        tmp = tempfile.mkdtemp()
        store_mod.DB_PATH = store_mod.Path(tmp) / "test.db"
        store_mod.init_db()
        pid = store_mod.add_pending(
            "用户决定先做 Orchestrator 闭环",
            type="project",
            source="desktop",
            suggest_reason="项目进展 · 来自：Archer 下一阶段",
        )
        pending = store_mod.list_pending()
        self.assertEqual(pending[0]["id"], pid)
        self.assertEqual(pending[0]["suggest_reason"], "项目进展 · 来自：Archer 下一阶段")

    def test_desktop_project_update_high_confidence_auto_saves(self):
        import tempfile
        import memory.store as store_mod
        from terminal.api._tools import _do_extract_api

        old_db = store_mod.DB_PATH
        tmp = tempfile.mkdtemp()
        store_mod.DB_PATH = store_mod.Path(tmp) / "test.db"
        store_mod.init_db()
        history = [
            {"role": "user", "content": "Archer P4 这批已经完成 Electron 计划卡冒烟，下一步继续收口记忆候选。"},
            {"role": "assistant", "content": "已记录为待确认的项目进展候选。"},
        ]
        try:
            with patch("memory.extract.extract") as mock_extract:
                mock_extract.return_value = ([
                    {
                        "content": "Archer P4 已完成 Electron 计划卡冒烟，下一步收口记忆候选。",
                        "type": "project",
                        "importance": 4,
                        "tags": "Archer,P4",
                        "confidence": 0.82,
                        "depth": 3,
                    }
                ], [])
                _do_extract_api(history)
            pending = store_mod.list_pending()
            confirmed = store_mod.list_all()
        finally:
            store_mod.DB_PATH = old_db

        mock_extract.assert_called_once()
        _, kwargs = mock_extract.call_args
        self.assertIn("project_update", kwargs.get("candidate_types", []))
        self.assertEqual(len(pending), 0)
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0]["type"], "project")

    def test_desktop_sensitive_memory_stays_pending(self):
        import tempfile
        import memory.store as store_mod
        from terminal.api._tools import _do_extract_api

        old_db = store_mod.DB_PATH
        tmp = tempfile.mkdtemp()
        store_mod.DB_PATH = store_mod.Path(tmp) / "test.db"
        store_mod.init_db()
        history = [
            {"role": "user", "content": "我最近总是焦虑和内耗，反复卡在同一个地方"},
            {"role": "assistant", "content": "听起来这个循环已经持续一段时间了。"},
        ]
        try:
            with patch("memory.extract.extract") as mock_extract:
                mock_extract.return_value = ([
                    {
                        "content": "用户最近反复感到焦虑和内耗。",
                        "type": "emotion_pattern",
                        "importance": 3,
                        "tags": "emotion",
                        "confidence": 0.9,
                        "depth": 3,
                    }
                ], [])
                _do_extract_api(history)
            pending = store_mod.list_pending()
            confirmed = store_mod.list_all()
        finally:
            store_mod.DB_PATH = old_db

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["type"], "emotion_pattern")
        self.assertEqual(len(confirmed), 0)


class TestSceneOneProjectPlanningClosedLoop(unittest.TestCase):
    def test_project_planning_with_obsidian_update_request(self):
        text = "帮我判断这段规划是否值得做，并更新 Obsidian 成长计划"
        result = orchestrate_user_input(text)
        policy = build_memory_candidate_policy(result)
        labels = orchestration_status_labels(result)
        constraints = format_mode_constraints_for_prompt(result)
        plan = build_task_plan(text, result)

        self.assertEqual(result.sub_intent, "project_planning")
        self.assertIn(result.mode, {"builder", "operator"})
        self.assertTrue(result.needs_project_context)
        self.assertIn("project", result.memory_scope)
        self.assertTrue(policy.should_extract)
        self.assertIn("project_update", policy.candidate_types)
        self.assertIn("项目规划", labels)
        self.assertIn("最小可验证闭环", constraints)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.steps[-1].tool, "obsidian_write")
        self.assertTrue(plan.steps[-1].requires_approval)


class TestSceneTwoWritingRevisionClosedLoop(unittest.TestCase):
    def test_writing_revision_stays_in_writer_lane(self):
        text = (
            "下面是我写的一段，请帮我减少 AI 味，不要一句话一段，"
            "保留我的语气：最近我在做 Archer，越来越觉得工具链比模型本身更决定体验。"
        )
        result = orchestrate_user_input(text)
        policy = build_memory_candidate_policy(result)
        labels = orchestration_status_labels(result)
        constraints = format_mode_constraints_for_prompt(result)
        plan = build_task_plan(text, result)

        self.assertEqual(result.sub_intent, "writing_assistance")
        self.assertEqual(result.mode, "writer")
        self.assertFalse(result.needs_job)
        self.assertEqual(result.side_effect_level, "none")
        self.assertIn("writing_style", result.memory_scope)
        self.assertNotIn("obsidian", result.memory_scope)
        self.assertFalse(policy.sensitive)
        self.assertIn("减少 AI 味", constraints)
        self.assertIn("写作协助", labels)
        self.assertIsNone(plan)

    def test_writing_outline_summary_stays_in_writer_lane(self):
        text = (
            "帮我分析一下写作的大纲：我想用“六月：悬置·好一点，再好一点”"
            "作为月度总结主题。"
        )
        result = orchestrate_user_input(text)

        self.assertEqual(result.sub_intent, "writing_assistance")
        self.assertEqual(result.mode, "writer")
        self.assertFalse(result.needs_tools)
        self.assertIn("writing_style", result.memory_scope)

    def test_desktop_stream_scene_two_orchestration(self):
        messages = [{
            "role": "user",
            "content": "请帮我润色下面这段，减少 AI 味，不要发布也不要保存文件。",
        }]
        chunks = _collect_until_orchestration(messages)
        orch = _single_orchestration(chunks)

        self.assertEqual(orch["subIntent"], "writing_assistance")
        self.assertEqual(orch["mode"], "writer")
        self.assertFalse(orch["needsJob"])
        self.assertFalse(any(c.get("type") == "planEvent" for c in chunks))

    def test_desktop_scene_two_filters_side_effect_tools(self):
        from terminal.api import _tools as tools

        query = "请帮我润色下面这段，减少 AI 味，不要一句话一段。"
        selected = tools._select_api_skills(query)
        filtered = tools._filter_api_skills_for_intent(query, selected)

        self.assertEqual(filtered, {})

    def test_desktop_extract_runs_for_writing_preference(self):
        from terminal.api._tools import _do_extract_api

        history = [
            {"role": "user", "content": "以后帮我改文章时，减少 AI 味，不要一句话一段"},
            {"role": "assistant", "content": "好，我会按这个风格来改。"},
        ]
        with patch("memory.extract.extract") as mock_extract:
            mock_extract.return_value = ([], [])
            _do_extract_api(history)
        mock_extract.assert_called_once()
        _, kwargs = mock_extract.call_args
        self.assertIn("writing_preference", kwargs.get("candidate_types", []))
        self.assertFalse(kwargs.get("sensitive"))


class TestSceneThreeEmotionalReflectionClosedLoop(unittest.TestCase):
    def test_emotional_reflection_stays_listener_without_tools(self):
        text = "我最近很焦虑，内耗严重，觉得做什么都没意义"
        result = orchestrate_user_input(text)
        policy = build_memory_candidate_policy(result)
        labels = orchestration_status_labels(result)
        constraints = format_mode_constraints_for_prompt(result)
        plan = build_task_plan(text, result)

        self.assertEqual(result.intent, "emotional")
        self.assertEqual(result.sub_intent, "emotional_reflection")
        self.assertIn(result.mode, {"listener", "therapist"})
        self.assertFalse(result.needs_tools)
        self.assertFalse(result.needs_job)
        self.assertIn("emotion", result.memory_scope)
        self.assertTrue(policy.should_extract)
        self.assertIn("emotional_pattern", policy.candidate_types)
        self.assertTrue(policy.sensitive)
        self.assertIn("先复述", constraints)
        self.assertIn("情绪反思", labels)
        self.assertIsNone(plan)

    def test_desktop_stream_scene_three_orchestration(self):
        messages = [{"role": "user", "content": "我最近很焦虑，内耗，不知道怎么办"}]
        chunks = _collect_until_orchestration(messages)
        orch = _single_orchestration(chunks)

        self.assertEqual(orch["subIntent"], "emotional_reflection")
        self.assertIn(orch["mode"], {"listener", "therapist"})
        self.assertFalse(orch["needsJob"])
        self.assertTrue(orch["needsMemory"])
        self.assertFalse(any(c.get("type") == "planEvent" for c in chunks))

    def test_desktop_scene_three_filters_side_effect_tools(self):
        from terminal.api import _tools as tools

        query = "我最近很焦虑，内耗，不知道怎么办"
        selected = tools._select_api_skills(query)
        filtered = tools._filter_api_skills_for_intent(query, selected)

        self.assertEqual(filtered, {})

    def test_desktop_extract_runs_for_emotional_reflection(self):
        from terminal.api._tools import _do_extract_api

        history = [
            {"role": "user", "content": "我最近总是焦虑和内耗，反复卡在同一个地方"},
            {"role": "assistant", "content": "听起来这个循环已经持续一段时间了。"},
        ]
        with patch("memory.extract.extract") as mock_extract:
            mock_extract.return_value = ([], "")
            _do_extract_api(history)
        mock_extract.assert_called_once()


def _collect_until_orchestration(messages: list[dict]) -> list[dict]:
    from terminal.api._tools import _iter_chat_chunks

    chunks: list[dict] = []
    for chunk in _iter_chat_chunks(messages, memory_mode="off", obsidian_mode="off"):
        chunks.append(chunk)
        if chunk.get("type") == "orchestrationEvent":
            break
    return chunks


def _single_orchestration(chunks: list[dict]) -> dict:
    events = [chunk.get("orchestrationEvent") for chunk in chunks if chunk.get("type") == "orchestrationEvent"]
    if len(events) != 1:
        raise AssertionError(f"expected 1 orchestration event, got {len(events)}")
    return events[0]


if __name__ == "__main__":
    unittest.main()
