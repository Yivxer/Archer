"""
tests/test_video_script.py
测试 video_script 的 platform hints、schema 和参数校验。
不依赖 LLM 连接。
"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import importlib
mod = importlib.import_module("skills.video_script")


# ── 1. _PLATFORM_HINTS 完整性 ────────────────────────────────────────────

def test_platform_hints_all_keys():
    """所有 enum 值在 hints 中都有对应。"""
    schema = mod.schema()
    enum_values = schema["function"]["parameters"]["properties"]["platform"]["enum"]
    for v in enum_values:
        assert v in mod._PLATFORM_HINTS, f"platform={v} 缺少 hint"


def test_platform_hints_non_empty():
    """每条 hint 非空。"""
    for k, v in mod._PLATFORM_HINTS.items():
        assert isinstance(v, str) and len(v) > 5, f"hint={k} 内容过短"


def test_platform_hints_douyin():
    """抖音 hint 提到完播率或钩子。"""
    hint = mod._PLATFORM_HINTS["douyin"]
    assert "完播" in hint or "钩" in hint


def test_platform_hints_youtube():
    """YouTube Shorts hint 提到字幕或订阅。"""
    hint = mod._PLATFORM_HINTS["youtube_shorts"]
    assert "字幕" in hint or "订阅" in hint


# ── 2. schema() ─────────────────────────────────────────────────────────

def test_schema_structure():
    s = mod.schema()
    assert s["type"] == "function"
    f = s["function"]
    assert f["name"] == "video_script"
    assert "topic" in f["parameters"]["properties"]
    assert f["parameters"]["required"] == ["topic"]


def test_schema_platform_enum():
    s = mod.schema()
    f = s["function"]
    assert "douyin" in f["parameters"]["properties"]["platform"]["enum"]
    assert "auto" in f["parameters"]["properties"]["platform"]["enum"]


def test_schema_style_enum():
    s = mod.schema()
    f = s["function"]
    assert "knowledge" in f["parameters"]["properties"]["style"]["enum"]
    assert "tutorial" in f["parameters"]["properties"]["style"]["enum"]


def test_schema_duration_optional():
    s = mod.schema()
    props = s["function"]["parameters"]["properties"]
    assert "duration" in props
    assert "save_path" in props


# ── 3. run() 参数校验 ──────────────────────────────────────────────────

def test_run_no_args():
    result = mod.run({})
    assert "错误" in result or "topic" in result


def test_run_empty_topic():
    result = mod.run({"topic": ""})
    assert "不能为空" in result or "错误" in result


def test_run_valid_topic_mock_llm():
    """topic 合法时走到 LLM 调用（mock）。"""
    with patch("skills.video_script._llm_stream", return_value="# 脚本\n分镜内容"):
        result = mod.run({"topic": "俯卧撑教学"})
    assert "已生成" in result or "✅" in result or "脚本" in result


def test_run_with_platform():
    with patch("skills.video_script._llm_stream", return_value="# 脚本"):
        result = mod.run({"topic": "测评", "platform": "bilibili"})
    assert "已生成" in result or "脚本" in result


def test_run_with_has_product():
    with patch("skills.video_script._llm_stream", return_value="# 脚本\nCTA"):
        result = mod.run({"topic": "种草", "has_product": True})
    assert "已生成" in result or "脚本" in result


def test_run_save_path(tmp_path):
    save_file = tmp_path / "script.md"
    with patch("skills.video_script._llm_stream", return_value="# 短视频脚本\n内容"):
        result = mod.run({"topic": "教程", "save_path": str(save_file)})
    assert save_file.exists(), f"文件应已保存：{save_file}"


# ── 4. platform_hint 选择逻辑 ──────────────────────────────────────────

def test_run_auto_platform_hint():
    """platform=auto 时 hint 取 auto 的值。"""
    with patch("skills.video_script._llm_stream", return_value="# 脚本") as mock_llm:
        mod.run({"topic": "测试"})
        prompt = mock_llm.call_args[0][0]
        assert "通用优化" in prompt


def test_run_specific_platform_hint():
    """指定 platform 时 hint 是对应的。"""
    with patch("skills.video_script._llm_stream", return_value="# 脚本") as mock_llm:
        mod.run({"topic": "测试", "platform": "douyin"})
        prompt = mock_llm.call_args[0][0]
        assert "抖音" in prompt


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
