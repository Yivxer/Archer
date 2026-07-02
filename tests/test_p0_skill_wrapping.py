"""B3.1 P0 critical skill 包装验证。

覆盖：
- core.permission_levels.is_p0_critical_skill 标识
- core.tool_runtime.invoke 在 P0 skill 失败/超时时的日志路径不抛异常
- skills.hugo_blog.run / run_structured 顶层 try/except 兜底
"""
from __future__ import annotations

from core.permission_levels import P0_CRITICAL_SKILLS, is_p0_critical_skill
from core.tool_runtime import ToolResult, invoke


def test_p0_critical_skills_contains_expected_members():
    expected = {
        "hugo_blog", "obsidian_write", "file_ops",
        "shell", "shell_execute", "run_shell",
        "github", "git_ops",
    }
    assert expected.issubset(P0_CRITICAL_SKILLS)


def test_is_p0_critical_skill_handles_edge_cases():
    assert is_p0_critical_skill("hugo_blog") is True
    assert is_p0_critical_skill("web_search") is False
    assert is_p0_critical_skill("") is False
    assert is_p0_critical_skill(None) is False  # type: ignore[arg-type]
    assert is_p0_critical_skill("  hugo_blog  ") is True


def test_invoke_missing_skill_returns_tool_result_not_raise():
    """invoke 找不到 skill 时应返回 ToolResult，不应抛异常。"""
    result = invoke("nonexistent_skill_xyz", {"action": "noop"}, skills={})
    assert isinstance(result, ToolResult)
    assert result.ok is False
    assert result.error is not None
    assert result.error["type"] == "SkillNotFound"


def test_invoke_p0_skill_timeout_logged_not_raised(caplog):
    """P0 skill 超时应返回 ToolResult，并记 warning 日志，不向上抛。"""
    import logging
    from skills import hugo_blog

    def slow_run(args):  # 模拟超时
        import time as _t
        _t.sleep(5)
        return "should not reach"

    # 替换 runner 为慢函数，timeout 设极短
    original = hugo_blog.run
    hugo_blog.run = slow_run  # type: ignore[assignment]
    try:
        with caplog.at_level(logging.WARNING, logger="core.tool_runtime"):
            result = invoke("hugo_blog", {"action": "list"}, skills={"hugo_blog": hugo_blog}, timeout=1)
        assert isinstance(result, ToolResult)
        assert result.ok is False
        assert result.error is not None
        assert result.error["type"] == "TimeoutError"
        # P0 skill 失败应记日志
        assert any("P0 skill" in rec.message and "hugo_blog" in rec.message for rec in caplog.records)
    finally:
        hugo_blog.run = original  # type: ignore[assignment]


def test_invoke_p0_skill_exception_logged_not_raised(caplog):
    """P0 skill 抛异常时应返回 ToolResult，并记 warning 日志。

    invoke 优先用 run_structured，所以 patch run_structured 让它直接抛异常，
    验证 tool_runtime 的 except Exception 分支 + P0 日志路径。
    """
    import logging
    from skills import hugo_blog

    def boom_structured(args):
        raise RuntimeError("boom")

    original = hugo_blog.run_structured
    hugo_blog.run_structured = boom_structured  # type: ignore[assignment]
    try:
        with caplog.at_level(logging.WARNING, logger="core.tool_runtime"):
            result = invoke("hugo_blog", {"action": "list"}, skills={"hugo_blog": hugo_blog})
        assert isinstance(result, ToolResult)
        assert result.ok is False
        assert result.error is not None
        assert result.error["type"] == "RuntimeError"
        assert any("P0 skill" in rec.message and "failed" in rec.message for rec in caplog.records)
    finally:
        hugo_blog.run_structured = original  # type: ignore[assignment]


def test_hugo_blog_run_structured_catches_top_level_exception():
    """hugo_blog.run_structured 顶层 try/except 应捕获 run() 抛出的异常返回 ok=False。"""
    from skills import hugo_blog

    def boom_run(args):
        raise RuntimeError("run boom")

    original = hugo_blog.run
    hugo_blog.run = boom_run  # type: ignore[assignment]
    try:
        # list action 走 else 分支调 run()，run 抛异常被顶层 try/except 捕获
        result = hugo_blog.run_structured({"action": "list"})
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert "异常" in result["summary"]
        assert "run boom" in result["output"]
    finally:
        hugo_blog.run = original  # type: ignore[assignment]
