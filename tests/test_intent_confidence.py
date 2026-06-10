"""意图分类置信度 + 弱关键词护栏（core/intent.py）。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.intent import classify_query_intent, _classify_single


def hist(*pairs):
    return [{"role": r, "content": t} for r, t in pairs]


class TestWeakKeywordGuard(unittest.TestCase):
    def test_lone_why_low_confidence(self):
        r = _classify_single("为什么？")
        self.assertEqual(r["intent"], "reflection")
        self.assertLess(r["confidence"], 0.65)

    def test_lone_gai_low_confidence(self):
        r = _classify_single("该")
        self.assertLess(r["confidence"], 0.65)

    def test_project_beats_weak_gai(self):
        r = _classify_single("这个项目的发布路线图该怎么安排")
        self.assertEqual(r["intent"], "project")
        self.assertGreaterEqual(r["confidence"], 0.65)

    def test_why_inherits_decision_with_history(self):
        h = hist(("user", "我到底该不该离职"), ("assistant", "……"))
        r = classify_query_intent("为什么？", history=h)
        self.assertEqual(r["intent"], "decision")
        self.assertEqual(r["source"], "inherit")

    def test_strong_decision_high_confidence(self):
        r = _classify_single("我该不该离职")
        self.assertEqual(r["intent"], "decision")
        self.assertGreaterEqual(r["confidence"], 0.65)

    def test_multimodal_prev_inherits_despite_score_tie(self):
        h = [
            {"role": "user", "content": [{"type": "text", "text": "我该不该接这个项目"}]},
            {"role": "assistant", "content": "……"},
        ]
        r = classify_query_intent("那这个呢", history=h)
        self.assertEqual(r["intent"], "decision")
        self.assertEqual(r["source"], "inherit")


class TestLlmFallback(unittest.TestCase):
    def test_llm_fallback_used_when_low_confidence(self):
        fake = {
            "intent": "chat",
            "confidence": 0.82,
            "source": "llm",
            "needs_memory": False,
            "needs_project": False,
            "needs_soul": False,
            "needs_tools": False,
        }
        with patch("core.intent._llm_classify_intent", return_value=fake):
            r = classify_query_intent("该", llm_fallback=True)
        self.assertEqual(r["source"], "llm")
        self.assertEqual(r["intent"], "chat")

    def test_llm_fallback_skipped_when_high_confidence(self):
        with patch("core.intent._llm_classify_intent") as mock_llm:
            r = classify_query_intent("我很焦虑", llm_fallback=True)
        mock_llm.assert_not_called()
        self.assertEqual(r["source"], "rules")
        self.assertEqual(r["intent"], "emotional")


if __name__ == "__main__":
    unittest.main()
