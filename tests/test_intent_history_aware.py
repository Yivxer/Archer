"""历史感知意图分类 + 检索词改写（core/intent.py）的单元测试。"""
from __future__ import annotations

import unittest

from core.intent import classify_query_intent, augment_retrieval_query, should_clarify


def hist(*pairs):
    """便捷构造 history：传入 (role, text) 序列。"""
    return [{"role": r, "content": t} for r, t in pairs]


class TestHistoryAwareIntent(unittest.TestCase):
    def test_followup_inherits_decision(self):
        h = hist(("user", "我到底该不该离职"), ("assistant", "……"))
        r = classify_query_intent("那这个呢", history=h)
        self.assertEqual(r["intent"], "decision")
        self.assertTrue(r["needs_memory"])

    def test_bare_question_inherits(self):
        h = hist(("user", "帮我复盘这几个月的状态"), ("assistant", "……"))
        r = classify_query_intent("为什么？", history=h)
        self.assertEqual(r["intent"], "reflection")

    def test_continuation_inherits(self):
        h = hist(("user", "这个项目的发布路线图怎么安排"), ("assistant", "……"))
        r = classify_query_intent("继续", history=h)
        self.assertEqual(r["intent"], "project")

    def test_no_history_stays_chat(self):
        r = classify_query_intent("那这个呢")
        self.assertEqual(r["intent"], "chat")

    def test_strong_signal_not_overridden_by_history(self):
        h = hist(("user", "我该不该离职"), ("assistant", "……"))
        r = classify_query_intent("帮我写一段代码", history=h)
        self.assertEqual(r["intent"], "task")

    def test_greeting_does_not_inherit(self):
        h = hist(("user", "今天好焦虑好难受"), ("assistant", "……"))
        r = classify_query_intent("在吗", history=h)
        self.assertEqual(r["intent"], "chat")

    def test_prev_chat_does_not_force_intent(self):
        h = hist(("user", "随便聊聊"), ("assistant", "……"))
        r = classify_query_intent("那这个呢", history=h)
        self.assertEqual(r["intent"], "chat")

    def test_multimodal_prev_content(self):
        h = [
            {"role": "user", "content": [{"type": "text", "text": "我该不该接这个项目"}]},
            {"role": "assistant", "content": "……"},
        ]
        r = classify_query_intent("那这个呢", history=h)
        self.assertEqual(r["intent"], "decision")


class TestAugmentRetrievalQuery(unittest.TestCase):
    def test_followup_augmented(self):
        h = hist(("user", "我到底该不该离职"), ("assistant", "……"))
        q = augment_retrieval_query("那这个呢", history=h)
        self.assertIn("该不该离职", q)
        self.assertIn("那这个呢", q)

    def test_non_followup_unchanged(self):
        h = hist(("user", "我该不该离职"), ("assistant", "……"))
        q = augment_retrieval_query("帮我写一篇周报", history=h)
        self.assertEqual(q, "帮我写一篇周报")

    def test_no_history_unchanged(self):
        self.assertEqual(augment_retrieval_query("那这个呢"), "那这个呢")

    def test_length_capped(self):
        long_prev = "决策" * 200
        h = hist(("user", long_prev), ("assistant", "……"))
        q = augment_retrieval_query("那这个呢", history=h)
        self.assertLessEqual(len(q), 200)

    def test_backref_short_augmented(self):
        h = hist(("user", "Archer 的发布路线图怎么安排"), ("assistant", "……"))
        q = augment_retrieval_query("这个怎么推进", history=h)
        self.assertIn("发布路线图", q)

    def test_memory_recall_short_augmented(self):
        h = hist(("user", "我们聊过离职的事"), ("assistant", "……"))
        q = augment_retrieval_query("还记得吗", history=h)
        self.assertIn("离职", q)

    def test_ellipsis_augmented(self):
        h = hist(("user", "这个项目卡住了"), ("assistant", "……"))
        q = augment_retrieval_query("……", history=h)
        self.assertIn("卡住", q)


class TestShouldClarify(unittest.TestCase):
    """关键词反问直出已关闭，一律交 LLM。"""

    def test_never_short_circuits(self):
        for text in ("帮我", "写一个", "帮我写一段关于焦虑的日记"):
            self.assertIsNone(should_clarify(text))


if __name__ == "__main__":
    unittest.main()
