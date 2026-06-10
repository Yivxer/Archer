"""当轮情绪读数 memory/emotion.py infer_turn_emotion_hint 的单元测试。"""
from __future__ import annotations

import unittest

from memory.emotion import infer_turn_emotion_hint


class TestTurnEmotionHint(unittest.TestCase):
    def test_anxiety_fatigue_detected(self):
        hint = infer_turn_emotion_hint("今天好累，好焦虑")
        self.assertIsNotNone(hint)
        self.assertIn("情绪读数", hint)
        self.assertTrue("焦虑" in hint or "疲惫" in hint)

    def test_neutral_returns_none_or_db(self):
        hint = infer_turn_emotion_hint("帮我列一下今天的待办")
        # 无情绪词时通常 None（除非 DB 有近几天高分情绪）
        if hint:
            self.assertIn("情绪读数", hint)

    def test_history_contributes(self):
        h = [{"role": "user", "content": "最近很沮丧"}]
        hint = infer_turn_emotion_hint("继续", history=h)
        self.assertIsNotNone(hint)
        self.assertIn("沮丧", hint)


if __name__ == "__main__":
    unittest.main()
