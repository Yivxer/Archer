"""
tests/test_workflow_automation.py
测试 workflow_automation 的模板列表、schema 和参数校验。
不依赖 LLM 连接。
"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import importlib
mod = importlib.import_module("skills.workflow_automation")


# ── 1. _list_templates 输出格式 ─────────────────────────────────────────

def test_list_templates_output():
    """_list_templates 返回非空字符串，包含触发和动作说明。"""
    result = mod._list_templates()
    assert isinstance(result, str)
    assert len(result) > 20
    assert "触发" in result or "trigger" in result.lower() or "TRIGGER" in result


def test_list_templates_contains_trigger_types():
    for k in mod._TRIGGER_TEMPLATES:
        out = mod._list_templates()
        assert k in out or k.upper() in out or k.capitalize() in out


def test_list_templates_contains_action_types():
    for k in mod._ACTION_TEMPLATES:
        out = mod._list_templates()
        # 至少包含 key 本身或中文描述
        assert k in out or any(k in line for line in out.splitlines())


# ── 2. _TRIGGER_TEMPLATES / _ACTION_TEMPLATES 完整性 ───────

def test_trigger_templates_all_non_empty():
    for k, vs in mod._TRIGGER_TEMPLATES.items():
        assert isinstance(vs, list) and len(vs) > 0, f"trigger {k} 为空"


def test_action_templates_all_non_empty():
    for k, vs in mod._ACTION_TEMPLATES.items():
        assert isinstance(vs, list) and len(vs) > 0, f"action {k} 为空"


def test_trigger_template_values_are_strings():
    for k, vs in mod._TRIGGER_TEMPLATES.items():
        for v in vs:
            assert isinstance(v, str), f"trigger {k} 值类型错误：{type(v)}"


def test_action_template_values_are_strings():
    for k, vs in mod._ACTION_TEMPLATES.items():
        for v in vs:
            assert isinstance(v, str), f"action {k} 值类型错误：{type(v)}"


# ── 3. schema() ────────────────────────────────────────────────────────

def test_schema_structure():
    s = mod.schema()
    assert s["type"] == "function"
    f = s["function"]
    assert f["name"] == "workflow_automation"
    assert "action" in f["parameters"]["properties"]
    assert f["parameters"]["required"] == ["action"]


def test_schema_action_enum():
    s = mod.schema()
    f = s["function"]
    assert "design" in f["parameters"]["properties"]["action"]["enum"]
    assert "list_templates" in f["parameters"]["properties"]["action"]["enum"]


def test_schema_trigger_type_enum():
    s = mod.schema()
    f = s["function"]
    assert "auto" in f["parameters"]["properties"]["trigger_type"]["enum"]


def test_schema_target_platform_enum():
    s = mod.schema()
    f = s["function"]
    assert "zapier" in f["parameters"]["properties"]["target_platform"]["enum"]
    assert "n8n" in f["parameters"]["properties"]["target_platform"]["enum"]


# ── 4. run() 参数校验 ─────────────────────────────────────────────────

def test_run_no_args():
    result = mod.run({})
    assert "未知" in result or "错误" in result


def test_run_design_no_description():
    result = mod.run({"action": "design"})
    assert "description" in result and ("需要" in result or "参数" in result)


def test_run_list_templates():
    result = mod.run({"action": "list_templates"})
    assert "触发" in result or "TRIGGER" in result.upper() or "模板" in result


def test_run_design_valid_mock_llm():
    with patch("skills.workflow_automation._llm_stream", return_value="# 工作流设计\n内容"):
        result = mod.run({"action": "design", "description": "表单提交后发邮件"})
    assert "完成" in result or "✅" in result or "工作流" in result


def test_run_with_trigger_type():
    with patch("skills.workflow_automation._llm_stream", return_value="# 设计"):
        result = mod.run({"action": "design", "description": "测试", "trigger_type": "webhook"})
    assert "完成" in result or "✅" in result or "设计" in result


def test_run_save_path(tmp_path):
    save_file = tmp_path / "workflow.md"
    with patch("skills.workflow_automation._llm_stream", return_value="# 工作流"):
        result = mod.run({
            "action": "design",
            "description": "测试",
            "save_path": str(save_file),
        })
    assert save_file.exists(), f"文件应已保存：{save_file}"


# ── 5. _design prompt 构造（通过 mock 验证） ────────────────────────

def test_design_prompt_contains_description():
    with patch("skills.workflow_automation._llm_stream", return_value="r") as mock_llm:
        mod.run({"action": "design", "description": "ABC测试需求123"})
        prompt = mock_llm.call_args[0][0]
        assert "ABC测试需求123" in prompt


def test_design_prompt_trigger_hint():
    with patch("skills.workflow_automation._llm_stream", return_value="r") as mock_llm:
        mod.run({"action": "design", "description": "测试", "trigger_type": "schedule"})
        prompt = mock_llm.call_args[0][0]
        assert "schedule" in prompt


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
