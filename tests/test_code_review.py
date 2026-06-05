"""
tests/test_code_review.py
测试 code_review 技能的静态分析函数和参数校验。
不依赖 LLM 连接。
"""
import sys
import ast
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest


# ── 辅助：直接导入静态分析函数 ─────────────────────────────────────────────
# code_review.py 顶层没有 export，但函数都是独立的，可以直接 import
import importlib
mod = importlib.import_module("skills.code_review")


# ── 1. _static_analysis_python ─────────────────────────────────────────────

def test_static_analysis_syntax_error():
    """语法错误的代码返回语法错误提示。"""
    code = "def foo(" + chr(10) + "  # 未闭合的括号" + chr(10) + ")"
    issues = mod._static_analysis_python(code)
    assert any("语法错误" in i for i in issues), f"应检测到语法错误，实际：{issues}"


def test_static_analysis_bare_except():
    """bare except 被检测到。"""
    code = """
try:
    x = 1 / 0
except:
    pass
"""
    issues = mod._static_analysis_python(code)
    assert any("bare except" in i for i in issues), f"应检测到 bare except，实际：{issues}"


def test_static_analysis_eval():
    """eval() 调用被标记为注入风险。"""
    code = "result = eval(user_input)\n"
    issues = mod._static_analysis_python(code)
    assert any("eval()" in i for i in issues), f"应检测到 eval()，实际：{issues}"


def test_static_analysis_exec():
    """exec() 调用被标记为注入风险。"""
    code = "exec(malicious_code)\n"
    issues = mod._static_analysis_python(code)
    assert any("exec()" in i for i in issues), f"应检测到 exec()，实际：{issues}"


def test_static_analysis_todo_comment():
    """TODO 注释被检测到。"""
    code = "def foo():\n    # TODO: 需要处理边界情况\n    pass\n"
    issues = mod._static_analysis_python(code)
    assert any("TODO" in i or "FIXME" in i for i in issues), f"应检测到 TODO，实际：{issues}"


def test_static_analysis_clean_code():
    """干净代码不产生问题。"""
    code = """
import os

def add(a, b):
    \"\"\"加法。\"\"\"
    return a + b

try:
    result = add(1, 2)
except ValueError as e:
    print(e)
"""
    issues = mod._static_analysis_python(code)
    assert len(issues) == 0, f"干净代码不应有问题，实际：{issues}"


# ── 2. _static_analysis_generic ───────────────────────────────────────────

def test_static_generic_eval():
    """通用分析检测到 eval()。"""
    code = "eval(input())\n"
    issues = mod._static_analysis_generic(code, "python")
    assert any("执行" in i or "注入" in i for i in issues), f"应检测到 eval()，实际：{issues}"


def test_static_generic_hardcoded_password():
    """检测到硬编码密码。"""
    code = 'password = "secret123"\n'
    issues = mod._static_analysis_generic(code, "python")
    assert any("密码" in i or "硬编码" in i for i in issues), f"应检测到密码，实际：{issues}"


def test_static_generic_hardcoded_api_key():
    """检测到硬编码 API Key。"""
    code = 'api_key = "sk-abc123"\n'
    issues = mod._static_analysis_generic(code, "python")
    assert any("api" in i.lower() or "key" in i.lower() for i in issues), f"应检测到 api_key，实际：{issues}"


def test_static_generic_xss_script():
    """检测到可能的 XSS（<script 标签）。"""
    code = "html = '<script>alert(1)</script>'\n"
    issues = mod._static_analysis_generic(code, "python")
    assert any("script" in i.lower() or "xss" in i.lower() for i in issues), f"应检测到 script，实际：{issues}"


def test_static_generic_todo():
    """通用分析也检测到 TODO。"""
    code = "def foo():\n    # FIXME: 这里有问题\n    pass\n"
    issues = mod._static_analysis_generic(code, "python")
    assert any("TODO" in i or "FIXME" in i or "未完成" in i for i in issues), f"应检测到 TODO，实际：{issues}"


def test_static_generic_clean():
    """干净代码不产问题（通用分析）。"""
    code = "x = 1 + 2\nprint(x)\n"
    issues = mod._static_analysis_generic(code, "python")
    assert len(issues) == 0, f"干净代码不应有问题，实际：{issues}"


def test_static_generic_limits_to_20():
    """问题数最多返回 20 条。"""
    # 生成 30 行带 TODO 的代码
    code = "\n".join(f"# TODO: item {i}" for i in range(30))
    issues = mod._static_analysis_generic(code, "python")
    assert len(issues) <= 20, f"应最多返回 20 条，实际：{len(issues)}"


# ── 3. schema() ───────────────────────────────────────────────────────────

def test_schema_structure():
    """schema() 返回合法 OpenAI function schema。"""
    s = mod.schema()
    assert s["type"] == "function"
    f = s["function"]
    assert f["name"] == "code_review"
    assert "file_path" in f["parameters"]["properties"]
    assert "code" in f["parameters"]["properties"]
    assert f["parameters"]["required"] == []


def test_schema_optional_params():
    """language / focus / save_path 都是可选的。"""
    s = mod.schema()
    props = s["function"]["parameters"]["properties"]
    assert "language" in props
    assert "focus" in props
    assert "save_path" in props


# ── 4. run() 参数校验 ──────────────────────────────────────────────────

def test_run_no_args():
    """无参数时返回错误提示。"""
    result = mod.run({})
    assert "错误" in result or "错误" in result


def test_run_only_file_path_missing():
    """只传不存在的文件路径时返回错误。"""
    result = mod.run({"file_path": "/tmp/nonexistent_xyz_12345.py"})
    assert "不存在" in result or "错误" in result


def test_run_code_only():
    """直接传 code 参数可以正常走通（mock LLM）。"""
    with patch("skills.code_review._llm_stream", return_value="## 综合评分\n7/10\n## 评价\n代码整体不错。"):
        result = mod.run({"code": "def add(a, b):\n    return a + b\n"})
    assert "完成" in result or "评分" in result


def test_run_file_path_with_mock():
    """file_path 存在时正常读取并审查（mock LLM + 临时文件）。"""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write("def foo():\n    return 1\n")
        tmp_path = f.name
    try:
        with patch("skills.code_review._llm_stream", return_value="## 综合评分\n8/10"):
            result = mod.run({"file_path": tmp_path})
        assert "完成" in result or "评分" in result
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_run_with_focus():
    """focus 参数正确传递（mock LLM）。"""
    with patch("skills.code_review._llm_stream", return_value="## 综合评分\n7/10") as mock_llm:
        mod.run({"code": "x = 1", "focus": ["security", "performance"]})
        mock_llm.assert_called_once()
        prompt = mock_llm.call_args[0][0]
        assert "security" in prompt or "performance" in prompt


# ── 5. run() 集成：静态分析 + LLM ─────────────────────────────────────

def test_run_includes_static_issues_in_report(tmp_path):
    """报告里包含静态分析发现的问题。"""
    code = "eval('1+1')\n"
    with patch("skills.code_review._llm_stream", return_value="## 综合评分\n5/10\n## 重大问题\neval 使用"):
        result = mod.run({"code": code})
    assert "静态分析" in result


def test_run_save_path(tmp_path):
    """传入 save_path 时保存文件。"""
    save_file = tmp_path / "review.md"
    with patch("skills.code_review._llm_stream", return_value="## 综合评分\n7/10"):
        result = mod.run({"code": "x=1", "save_path": str(save_file)})
    assert save_file.exists(), f"文件应已保存：{save_file}"
    content = save_file.read_text(encoding="utf-8")
    assert "综合评分" in content or "Code Review" in content


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
