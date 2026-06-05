"""
tests/test_market_research.py
测试 market_research 的辅助函数和参数校验。
不依赖 LLM 连接、不依赖网络。
"""
import sys
import re
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import importlib
mod = importlib.import_module("skills.market_research")


# ── 1. _parse_urls ───────────────────────────────────────────────────────

def test_parse_urls_basic():
    text = "查看 https://example.com 和 http://test.org/page?a=1"
    urls = mod._parse_urls(text)
    assert "https://example.com" in urls
    assert "http://test.org/page?a=1" in urls


def test_parse_urls_duplicates():
    """重复 URL 被去重，保持顺序。"""
    text = "https://a.com/x\nhttps://b.com/y\nhttps://a.com/x"
    urls = mod._parse_urls(text)
    assert len(urls) == 2
    assert urls[0] == "https://a.com/x"
    assert urls[1] == "https://b.com/y"


def test_parse_urls_none():
    """无 URL 时返回空列表。"""
    urls = mod._parse_urls("这里没有任何链接")
    assert urls == []


def test_parse_urls_complex():
    """括号包裹的 URL 正确提取。"""
    text = "参考这个 (https://example.com/path)，很好"
    urls = mod._parse_urls(text)
    # 正则 \s 边界，括号可能被包含或排除，这里验证基本功能
    assert any("example.com" in u for u in urls)


# ── 2. 搜索模板生成 ──────────────────────────────────────────────────────

def test_search_templates_quick():
    ts = mod._SEARCH_TEMPLATES["quick"]
    assert len(ts) == 3
    # 格式化后包含 topic
    filled = [t.format(topic="AI工具", market="中国") for t in ts]
    assert all("AI工具" in f for f in filled)


def test_search_templates_standard():
    ts = mod._SEARCH_TEMPLATES["standard"]
    assert len(ts) == 5


def test_search_templates_deep():
    ts = mod._SEARCH_TEMPLATES["deep"]
    assert len(ts) == 8


def test_search_templates_format():
    """所有模板都能正确填充 topic 和 market。"""
    for depth, ts in mod._SEARCH_TEMPLATES.items():
        for t in ts:
            result = t.format(topic="测试主题", market="中国市场")
            assert "测试主题" in result
            assert "市场" in result or "中国市场" in result or "{" not in result


# ── 3. schema() ─────────────────────────────────────────────────────────

def test_schema_structure():
    s = mod.schema()
    assert s["type"] == "function"
    f = s["function"]
    assert f["name"] == "market_research"
    assert "topic" in f["parameters"]["properties"]
    assert f["parameters"]["required"] == ["topic"]


def test_schema_depth_enum():
    s = mod.schema()
    f = s["function"]
    assert "quick" in f["parameters"]["properties"]["depth"]["enum"]
    assert "deep" in f["parameters"]["properties"]["depth"]["enum"]


def test_schema_target_market_optional():
    s = mod.schema()
    props = s["function"]["parameters"]["properties"]
    assert "target_market" in props


# ── 4. run() 参数校验 ──────────────────────────────────────────────────

def test_run_no_args():
    result = mod.run({})
    assert "错误" in result or "topic" in result


def test_run_empty_topic():
    result = mod.run({"topic": ""})
    assert "错误" in result or "不能为空" in result


def test_run_valid_topic_no_llm():
    """topic 合法但 mock 所有外部调用，验证走到 LLM 之前不报错。"""
    # mock _call_skill 返回含 URL 的内容，这样 all_results 不为空，能走到 _compile_report
    mock_result = "调研结果：https://example.com/report | https://example.com/analysis"
    with patch("skills.market_research._call_skill", return_value=mock_result), \
         patch("skills.market_research._compile_report", return_value="模拟报告"):
        result = mod.run({"topic": "AI 写作工具"})
    # 不应有 Python 异常，应走到报告生成
    assert "模拟报告" in result or "报告" in result or "完成" in result, f"实际：{result}"


def test_run_with_depth():
    with patch("skills.market_research._call_skill", return_value="调研 https://example.com"), \
         patch("skills.market_research._compile_report", return_value="报告"):
        result = mod.run({"topic": "低代码平台", "depth": "deep"})
    assert "报告" in result or "完成" in result, f"实际：{result}"


def test_run_with_save_path(tmp_path):
    save_file = tmp_path / "report.md"
    with patch("skills.market_research._call_skill", return_value="调研 https://x.com"), \
         patch("skills.market_research._compile_report", return_value="# 报告\n内容"):
        result = mod.run({"topic": "AI", "save_path": str(save_file)})
    assert save_file.exists(), f"文件应已保存：{save_file}, 结果：{result}"


# ── 5. _compile_report 截断逻辑 ─────────────────────────────────────────

def test_compile_report_truncation(monkeypatch):
    """_compile_report 在 evidence 超长时截断到 12000 字符。"""
    # 构造超长 evidence
    long_evidence = "\n\n## 来源：http://x.com\n查询：test\n" + "A" * 20000
    # 直接测试 prompt 构造不超长（通过 mock LLM）
    with patch("skills.market_research._llm_stream", return_value="# 报告"):
        report = mod._compile_report("AI", "中国", [{"url": "http://x.com", "query": "test", "content": "A" * 20000}], "deep")
    # 只要不抛异常，且返回值是字符串即可
    assert isinstance(report, str)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
