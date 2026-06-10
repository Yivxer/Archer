"""话题线程 core/thread.py 的单元测试。"""
from __future__ import annotations

import unittest

from core.thread import resolve_topic_thread


def hist(*pairs):
    return [{"role": r, "content": t} for r, t in pairs]


class TestTopicThread(unittest.TestCase):
    def test_new_topic(self):
        r = resolve_topic_thread("Archer 发布路线图怎么安排")
        self.assertIsNotNone(r)
        self.assertIn("发布路线图", r["topic"])
        self.assertEqual(r["turns"], 1)

    def test_followup_inherits_anchor(self):
        h = hist(
            ("user", "我到底该不该离职"),
            ("assistant", "……"),
            ("user", "为什么"),
            ("assistant", "……"),
        )
        r = resolve_topic_thread("然后呢", history=h)
        self.assertIsNotNone(r)
        self.assertIn("离职", r["topic"])
        self.assertGreaterEqual(r["turns"], 2)

    def test_too_short_returns_none(self):
        self.assertIsNone(resolve_topic_thread("嗯"))


if __name__ == "__main__":
    unittest.main()
