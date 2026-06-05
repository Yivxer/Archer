"""
tests/test_frontend_dev.py
测试 frontend_dev 技能的 _extract_code 辅助函数和参数校验。
不依赖 LLM 连接。
"""
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import importlib
mod = importlib.import_module("skills.frontend_dev")


# ── 1. _extract_code ─────────────────────────────────────────────────────

def test_extract_code_html():
    """从 LLM 输出中提取 HTML 代码块。"""
    text = "这是说明：\n```html\n<div>Hello</div>\n```\n结束。"
    code = mod._extract_code(text)
    assert code == "<div>Hello</div>"


def test_extract_code_jsx():
    """提取 JSX 代码块。"""
    text = "```jsx\nconst App = () => <div/>;\n```"
    code = mod._extract_code(text)
    assert "App" in code


def test_extract_code_typescript():
    """提取 TypeScript 代码块。"""
    text = "```typescript\nconst x: number = 1;\n```"
    code = mod._extract_code(text)
    assert "number" in code


def test_extract_code_vue():
    """提取 Vue 代码块。"""
    text = "```vue\n<template><div></div></template>\n```"
    code = mod._extract_code(text)
    assert "template" in code


def test_extract_code_svelte():
    """提取 Svelte 代码块。"""
    text = "```svelte\n<script>let x = 1;</script>\n```"
    code = mod._extract_code(text)
    assert "script" in code


def test_extract_code_no_block():
    """没有代码块时返回空字符串。"""
    text = "这只是普通文字，没有代码块。"
    code = mod._extract_code(text)
    assert code == ""


def test_extract_code_empty_block():
    """代码块为空时返回空字符串。"""
    text = "```html\n```"
    code = mod._extract_code(text)
    assert code == ""


def test_extract_code_preserves_newlines():
    """代码块内的换行被保留。"""
    text = "```html\nline1\nline2\nline3\n```"
    code = mod._extract_code(text)
    assert code == "line1\nline2\nline3"


# ── 2. schema() ───────────────────────────────────────────────────────────

def test_schema_structure():
    s = mod.schema()
    assert s["type"] == "function"
    f = s["function"]
    assert f["name"] == "frontend_dev"
    assert "action" in f["parameters"]["properties"]
    assert "description" in f["parameters"]["properties"]


def test_schema_action_enum():
    s = mod.schema()
    f = s["function"]
    assert "generate" in f["parameters"]["properties"]["action"]["enum"]
    assert "improve" in f["parameters"]["properties"]["action"]["enum"]


def test_schema_required():
    s = mod.schema()
    assert s["function"]["parameters"]["required"] == ["action"]


# ── 3. run() 参数校验 ──────────────────────────────────────────────────

def test_run_no_action():
    """无参数时返回错误。"""
    result = mod.run({})
    assert "未知 action" in result or "错误" in result


def test_run_generate_no_description():
    """generate 缺 description 时返回错误。"""
    result = mod.run({"action": "generate"})
    assert "description" in result and ("需要" in result or "参数" in result)


def test_run_improve_no_existing_code():
    """improve 缺 existing_code 时返回错误。"""
    result = mod.run({"action": "improve", "improvement_notes": "改一下"})
    assert "existing_code" in result and ("需要" in result or "参数" in result)


def test_run_improve_no_notes():
    """improve 缺 improvement_notes 时返回错误。"""
    result = mod.run({"action": "improve", "existing_code": "<div></div>"})
    assert "improvement_notes" in result and ("需要" in result or "参数" in result)


def test_run_invalid_action():
    """非法 action 返回错误。"""
    result = mod.run({"action": "foobar"})
    assert "未知" in result or "错误" in result


# ── 4. run() 集成（mock LLM）───────────────────────────────────────────

def test_run_generate_success(tmp_path):
    """generate 成功时返回代码和保存路径（mock LLM）。"""
    html = "<!DOCTYPE html>\n<html><body>Hello</body></html>"
    with patch("skills.frontend_dev._llm_stream", return_value=f"```html\n{html}\n```"):
        save = tmp_path / "out.html"
        result = mod.run({"action": "generate", "description": "一个欢迎页", "save_path": str(save)})
    assert "已生成" in result or "✅" in result
    assert save.exists()


def test_run_improve_success(tmp_path):
    """improve 成功时返回改进代码（mock LLM）。"""
    html = "<!DOCTYPE html>\n<html><body>Improved</body></html>"
    with patch("skills.frontend_dev._llm_stream", return_value=f"```\n{html}\n```"):
        save = tmp_path / "improved.html"
        result = mod.run({
            "action": "improve",
            "existing_code": "<html><body>Old</body></html>",
            "improvement_notes": "改得现代化一点",
            "save_path": str(save),
        })
    assert "已改进" in result or "✅" in result
    assert save.exists()


def test_run_generate_no_code_block():
    """LLM 返回不含代码块时给出提示（mock LLM）。"""
    with patch("skills.frontend_dev._llm_stream", return_value="这只是文字说明，没有代码块"):
        result = mod.run({"action": "generate", "description": "一个页面"})
    assert "未包含代码块" in result or "⚠️" in result


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
