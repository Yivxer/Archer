"""每轮模型选择 core/model_select.py 单元测试。"""
from __future__ import annotations

import unittest

from core.model_select import resolve_active_model, status_model_label
from core.model_profiles import active_api_config, active_model_profile_id


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

    def test_default_profile_keeps_lite_deepseek(self):
        api = active_api_config({"api": {"api_key": "sk-test"}})
        self.assertEqual(active_model_profile_id({"api": {}}), "lite")
        self.assertEqual(api["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(api["model"], "deepseek-chat")

    def test_active_profile_uses_configured_profile(self):
        api = active_api_config({
            "api": {"active_profile": "pro"},
            "model_profiles": {
                "pro": {
                    "provider": "Kimi",
                    "base_url": "https://kimi.example/v1",
                    "api_key": "kimi-key",
                    "model": "kimi-model",
                    "models": ["kimi-model"],
                }
            },
        })
        self.assertEqual(api["active_profile"], "pro")
        self.assertEqual(api["base_url"], "https://kimi.example/v1")
        self.assertEqual(api["api_key"], "kimi-key")
        self.assertEqual(api["model"], "kimi-model")

    def test_top_level_kimi_does_not_leak_into_lite_profile(self):
        api = active_api_config({
            "api": {
                "active_profile": "lite",
                "base_url": "https://api.moonshot.cn/v1",
                "model": "kimi-k2.6",
                "api_key": "kimi-key",
            },
            "model_profiles": {
                "lite": {
                    "provider": "DeepSeek",
                    "base_url": "https://api.deepseek.com/v1",
                    "model": "deepseek-chat",
                    "models": ["deepseek-chat", "deepseek-reasoner"],
                },
                "pro": {
                    "provider": "Kimi",
                    "base_url": "https://api.moonshot.cn/v1",
                    "api_key": "kimi-key",
                    "model": "kimi-k2.6",
                },
            },
        })

        self.assertEqual(api["active_profile"], "lite")
        self.assertEqual(api["provider"], "DeepSeek")
        self.assertEqual(api["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(api["model"], "deepseek-chat")

    def test_top_level_credential_does_not_leak_into_explicit_profile(self):
        api = active_api_config({
            "api": {"active_profile": "pro", "api_key": "stale-lite-key"},
            "model_profiles": {"pro": {"base_url": "https://kimi.example/v1", "model": "kimi"}},
        })
        self.assertFalse(api.get("api_key"))


if __name__ == "__main__":
    unittest.main()
