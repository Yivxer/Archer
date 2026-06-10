"""动态对话姿态选择 core/stance.py 的单元测试。"""
from __future__ import annotations

import unittest

from core.stance import select_stance, resolve_active_stance, available_modes

# 模拟项目实际可用的 12 个模式
ALL = {
    "coach", "mirror", "listener", "questioner", "philosopher", "writer",
    "therapist", "witness", "ritualist", "critic", "builder", "operator",
}


def pick(text, intent="chat", prev=None):
    stance, _ = select_stance(
        text, intent=intent, available=ALL, default_mode="listener", prev_stance=prev,
    )
    return stance


class TestSignalRouting(unittest.TestCase):
    def test_emotional_to_listener(self):
        self.assertEqual(pick("今天好累，不想说话", intent="emotional"), "listener")

    def test_dont_want_advice_to_listener(self):
        self.assertEqual(pick("你别给方案，我只是想说说", intent="chat"), "listener")

    def test_decision_to_questioner(self):
        self.assertEqual(pick("我到底该不该离职，帮我分析", intent="decision"), "questioner")

    def test_reflection_to_witness(self):
        self.assertEqual(pick("帮我复盘一下这几个月", intent="reflection"), "witness")

    def test_writing_to_writer(self):
        self.assertEqual(pick("帮我写一段独白", intent="task"), "writer")

    def test_code_to_builder(self):
        self.assertEqual(pick("这段代码报错了，帮我修 bug", intent="task"), "builder")

    def test_ritual_to_ritualist(self):
        self.assertEqual(pick("我想给这段感情设计一个告别仪式", intent="chat"), "ritualist")

    def test_critic_when_asked_to_challenge(self):
        self.assertEqual(pick("挑战我这个方案，找漏洞", intent="decision"), "critic")

    def test_philosophy_to_philosopher(self):
        self.assertEqual(pick("活着到底有什么意义", intent="emotional"), "philosopher")

    def test_task_baseline_to_operator(self):
        self.assertEqual(pick("帮我整理一下这些文件并导出", intent="task"), "operator")


class TestFallbackAndContinuation(unittest.TestCase):
    def test_plain_chat_falls_back_to_default(self):
        self.assertEqual(pick("在吗", intent="chat"), "listener")

    def test_continuation_keeps_prev(self):
        self.assertEqual(pick("继续", intent="chat", prev="philosopher"), "philosopher")

    def test_short_chat_keeps_prev(self):
        self.assertEqual(pick("嗯", intent="chat", prev="witness"), "witness")

    def test_strong_signal_overrides_continuation(self):
        # 即便很短，命中强信号也应切走
        self.assertEqual(pick("帮我修bug", intent="task", prev="listener"), "builder")

    def test_unavailable_stance_falls_back(self):
        stance, _ = select_stance(
            "帮我写一段独白", intent="task",
            available={"listener", "coach"}, default_mode="listener",
        )
        self.assertEqual(stance, "listener")


class TestResolveLock(unittest.TestCase):
    def _cfg(self, **persona):
        base = {"default_mode": "listener", "modes_dir": ""}
        base.update(persona)
        return {"persona": base}

    def test_auto_on_by_default(self):
        cfg = self._cfg()
        stance, reason = resolve_active_stance(
            cfg, "今天好累", "emotional", available=ALL,
        )
        self.assertEqual(stance, "listener")
        self.assertNotEqual(reason, "锁定")

    def test_lock_overrides_dynamic(self):
        cfg = self._cfg(mode_auto=False, current_mode="critic")
        stance, reason = resolve_active_stance(
            cfg, "今天好累", "emotional", available=ALL,
        )
        self.assertEqual(stance, "critic")
        self.assertEqual(reason, "锁定")

    def test_available_modes_from_toml(self):
        cfg = {"persona": {"modes": {"coach": {}, "mirror": {}}, "modes_dir": ""}}
        self.assertEqual(available_modes(cfg), {"coach", "mirror"})


if __name__ == "__main__":
    unittest.main()
