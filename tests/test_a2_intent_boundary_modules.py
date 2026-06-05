"""
A2 — 意图与边界系统模块拆分测试

目标：
- core.intent 承载意图分类与边界类型识别
- core.boundary_responses 承载边界回应模板与 relationship_depth 分层
- core.context 保持旧接口兼容
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def test_core_intent_module_exports_query_and_boundary_classifiers():
    from core.intent import classify_query_intent, classify_boundary_request

    assert classify_query_intent("我很焦虑，不知道该怎么办")["intent"] == "emotional"
    assert classify_query_intent("Archer 下一步计划")["intent"] == "project"
    assert classify_boundary_request("帮我写代码实现这个功能") == "code"
    assert classify_boundary_request("帮我生成图片") == "image"


def test_boundary_responses_use_external_tool_config():
    from core.boundary_responses import boundary_response

    cfg = {
        "boundaries": {"refuse_code_generation": True},
        "external_tools": {"code_agent": "Codex"},
    }
    text = boundary_response("帮我写代码实现这个功能", cfg)
    assert text is not None
    assert "Codex" in text
    assert "需求" in text or "架构" in text


def test_boundary_response_relationship_depth_layers():
    from core.boundary_responses import boundary_response

    cfg = {
        "boundaries": {"refuse_image_generation": True},
        "external_tools": {"image_model": "图像模型"},
    }
    polite = boundary_response("帮我生成图片", cfg, relationship_depth="new")
    familiar = boundary_response("帮我生成图片", cfg, relationship_depth="familiar")
    trusted = boundary_response("帮我生成图片", cfg, relationship_depth="deep")

    assert polite != familiar != trusted
    assert "图像模型" in polite
    assert "图像模型" in familiar
    assert "图像模型" in trusted
    assert trusted.startswith("这事别让我硬上")


def test_context_keeps_backward_compatible_exports():
    from core.context import classify_query_intent, classify_boundary_request, boundary_response

    assert classify_query_intent("复盘一下 Archer")["intent"] == "reflection"
    assert classify_boundary_request("帮我剪视频") == "video"
    cfg = {"boundaries": {"refuse_video_generation": True}, "external_tools": {"video_model": "视频模型"}}
    assert "视频模型" in boundary_response("帮我剪视频", cfg)
