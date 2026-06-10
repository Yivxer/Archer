"""每轮模型选择 core/model_select.py 单元测试。"""
from __future__ import annotations

import unittest

from core.model_select import resolve_active_model, status_model_label


def cfg(models=None, *, model_auto=True, model="fast-model", vision="vision-model"):
    api = {
        "model": model,
        "model_auto": model_auto,
        "vision_model": vision,
    }
    if models is not None:
        api["models"] = models
    return {"api": api}


class TestResolveActiveModel(unittest.TestCase):
    def test_locked_returns_primary(self):
        m, reason = resolve_active_model(
            cfg(["fast-model", "heavy-model"], model_auto=False),
            intent="task",
            needs_tools=True,
        )
        self.assertEqual(m, "fast-model")
        self.assertEqual(reason, "locked")

    def test_task_uses_heavy_model(self):
        m, reason = resolve_active_model(
            cfg(["fast-model", "heavy-model"]),
            user_text="帮我执行部署",
            intent="task",
            needs_tools=True,
        )
        self.assertEqual(m, "heavy-model")
        self.assertEqual(reason, "task")

    def test_chat_uses_fast_model(self):
        m, reason = resolve_active_model(
            cfg(["fast-model", "heavy-model"]),
            user_text="今天有点累",
            intent="emotional",
        )
        self.assertEqual(m, "fast-model")
        self.assertEqual(reason, "emotional")

    def test_images_use_vision(self):
        m, reason = resolve_active_model(
            cfg(["fast-model", "heavy-model"]),
            has_images=True,
        )
        self.assertEqual(m, "vision-model")
        self.assertEqual(reason, "vision")

    def test_status_label_auto(self):
        self.assertEqual(status_model_label(cfg(model_auto=True)), "auto")

    def test_status_label_locked(self):
        self.assertEqual(
            status_model_label(cfg(model_auto=False, model="heavy-model")),
            "heavy-model",
        )


if __name__ == "__main__":
    unittest.main()
