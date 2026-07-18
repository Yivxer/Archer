"""test_api_tool_helpers.py — api_tool_helpers.py 安全敏感 helper 直接单元测试。

补齐 `_execute_shell_command` / `_tool_event_from_request` /
`_tool_event_from_result` / `_obsidian_work_intent` / `_select_api_skills` /
`_make_api_tool_request` 等此前只能被集成测试间接覆盖的 helper 的直接单元测试。

已由其他 test 模块直接覆盖的 helper（不在此重复）：
- `_is_dangerous_shell`         → test_desktop_api.py
- `_obsidian_write_draft`       → test_obsidian_write_preview.py
- `_tool_event`                 → test_desktop_contract.py
- `_expert_scoped_skills`       → test_desktop_api.py
- `_filter_api_skills_for_intent` → test_p4_orchestrator.py
- `_execute_api_tool_preview`   → test_desktop_api.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from terminal.api import api_tool_helpers as helpers


# ---------------------------------------------------------------------------
# _execute_shell_command
# ---------------------------------------------------------------------------

def test_execute_shell_command_blocks_dangerous_command():
    """危险命令必须被立即拦截，不进入 subprocess.run。"""
    result = helpers._execute_shell_command("rm -rf /")
    assert result["ok"] is False
    assert "拒绝" in result["output"]
    assert "rm -rf /" in result["output"]
    # 没有退出码字段，说明根本没跑过子进程
    assert "exitCode" not in result


def test_execute_shell_command_runs_safe_command_and_returns_exit_code():
    """安全命令应实际执行并返回 exitCode。"""
    result = helpers._execute_shell_command("echo archer-test")
    assert result["ok"] is True
    assert result["exitCode"] == 0
    assert "archer-test" in result["output"]


def test_execute_shell_command_returns_no_output_placeholder_when_empty():
    """无输出的命令应回退到「(无输出)」，避免返回空串。"""
    result = helpers._execute_shell_command("true")
    assert result["ok"] is True
    assert result["output"] == "(无输出)"


def test_execute_shell_command_handles_timeout(monkeypatch):
    """超时应返回 ok=False 且不抛异常。"""
    import subprocess

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="sleep 999", timeout=0.01)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    result = helpers._execute_shell_command("sleep 999")
    assert result["ok"] is False
    assert "超时" in result["output"]


def test_execute_shell_command_handles_generic_exception(monkeypatch):
    """subprocess 抛其他异常时应被吞掉并返回错误信息。"""
    import subprocess

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(subprocess, "run", _raise)
    result = helpers._execute_shell_command("whatever")
    assert result["ok"] is False
    assert "错误" in result["output"]
    assert "boom" in result["output"]


# ---------------------------------------------------------------------------
# _tool_event_from_request
# ---------------------------------------------------------------------------

def test_tool_event_from_request_marks_waiting_when_not_blocked():
    request = {
        "eventId": "evt-1",
        "skillName": "obsidian_write",
        "displayName": "Obsidian 写入",
        "policy": {"decision": "confirm", "risk": "medium", "reason": "需要写入文件"},
        "requiresApproval": True,
        "blocked": False,
    }
    event = helpers._tool_event_from_request(request, summary="写入日记.md")
    tool = event["toolEvent"]
    assert tool["status"] == "waiting"
    assert tool["risk"] == "medium"
    assert tool["requiresApproval"] is True
    assert tool["summary"] == "写入日记.md"
    assert "evt-1" in tool["detail"]
    assert "obsidian_write" in tool["detail"]
    assert "confirm" in tool["detail"]
    assert "需要写入文件" in tool["detail"]


def test_tool_event_from_request_marks_blocked_and_disables_approval():
    request = {
        "eventId": "evt-2",
        "skillName": "shell",
        "displayName": "shell",
        "policy": {"decision": "deny", "risk": "critical", "reason": "危险命令"},
        "requiresApproval": True,  # 即使这里为 True，blocked 时也应被覆盖为 False
        "blocked": True,
    }
    event = helpers._tool_event_from_request(request, summary="执行 shell")
    tool = event["toolEvent"]
    assert tool["status"] == "blocked"
    assert tool["requiresApproval"] is False
    assert "策略阻止" in tool["summary"] or "阻止" in tool["summary"]


def test_tool_event_from_request_appends_detail_prefix_when_provided():
    request = {
        "eventId": "evt-3",
        "skillName": "hugo_blog",
        "displayName": "hugo_blog",
        "policy": {"decision": "confirm", "risk": "high", "reason": ""},
        "requiresApproval": True,
        "blocked": False,
    }
    event = helpers._tool_event_from_request(
        request, summary="部署枫弋札记", detail_prefix="来自桌面端确认",
    )
    assert "来自桌面端确认" in event["toolEvent"]["detail"]


def test_tool_event_from_request_truncates_long_reason():
    long_reason = "x" * 500
    request = {
        "eventId": "evt-4",
        "skillName": "shell",
        "displayName": "shell",
        "policy": {"decision": "confirm", "risk": "high", "reason": long_reason},
        "requiresApproval": True,
        "blocked": False,
    }
    event = helpers._tool_event_from_request(request, summary="shell")
    # reason 字段被截断到 240 字符
    assert long_reason not in event["toolEvent"]["detail"]
    assert "x" * 240 in event["toolEvent"]["detail"]


def test_tool_event_from_request_falls_back_to_skill_name_when_no_display_name():
    request = {
        "eventId": "evt-5",
        "skillName": "obsidian_search",
        "policy": {"decision": "allow", "risk": "low", "reason": ""},
        "requiresApproval": False,
        "blocked": False,
    }
    event = helpers._tool_event_from_request(request, summary="搜索")
    assert event["toolEvent"]["name"] == "obsidian_search"


# ---------------------------------------------------------------------------
# _tool_event_from_result
# ---------------------------------------------------------------------------

def test_tool_event_from_result_marks_complete_when_ok():
    result = {
        "ok": True,
        "output": "写入成功",
        "policy": {"decision": "allow", "risk": "low", "reason": ""},
    }
    event = helpers._tool_event_from_result(
        "evt-ok", "obsidian_write", result, summary="写入完成",
    )
    tool = event["toolEvent"]
    assert tool["status"] == "complete"
    assert tool["risk"] == "low"
    assert tool["requiresApproval"] is False
    assert tool["summary"] == "写入完成"
    assert "写入成功" in tool["detail"]


def test_tool_event_from_result_marks_blocked_when_failed():
    result = {
        "ok": False,
        "output": "策略拒绝：危险路径",
        "policy": {"decision": "deny", "risk": "high", "reason": "危险路径"},
    }
    event = helpers._tool_event_from_result(
        "evt-fail", "shell", result, summary="执行 shell",
    )
    tool = event["toolEvent"]
    assert tool["status"] == "blocked"
    assert tool["risk"] == "high"
    assert "失败" in tool["summary"]
    assert "策略拒绝" in tool["detail"]


def test_tool_event_from_result_truncates_detail_to_300_chars():
    long_output = "y" * 1000
    result = {
        "ok": True,
        "output": long_output,
        "policy": {"decision": "allow", "risk": "low", "reason": ""},
    }
    event = helpers._tool_event_from_result(
        "evt-long", "shell", result, summary="shell",
    )
    detail = event["toolEvent"]["detail"]
    assert len(detail) <= 300
    assert long_output not in detail


def test_tool_event_from_result_falls_back_to_summary_when_no_output():
    result = {
        "ok": True,
        "summary": "执行成功但无输出",
        "policy": {"decision": "allow", "risk": "low", "reason": ""},
    }
    event = helpers._tool_event_from_result(
        "evt-no-out", "shell", result, summary="shell",
    )
    assert "执行成功但无输出" in event["toolEvent"]["detail"]


def test_tool_event_from_result_uses_default_low_risk_when_policy_missing():
    result = {"ok": True, "output": "done"}
    event = helpers._tool_event_from_result(
        "evt-default", "shell", result, summary="shell",
    )
    assert event["toolEvent"]["risk"] == "low"


# ---------------------------------------------------------------------------
# _obsidian_work_intent
# ---------------------------------------------------------------------------

def test_obsidian_work_intent_returns_expected_structure():
    intent = helpers._obsidian_work_intent(
        "日记/今天.md", "append", before_text="# 标题\n\n第一段内容",
    )
    assert intent["workflowName"] == "Obsidian 写入"
    assert intent["action"] == "append"
    assert intent["targets"] == [{"label": "目标笔记", "path": "日记/今天.md"}]
    # 四步工作流
    assert intent["steps"] == ["读取当前文件状态", "校验文件指纹", "写入内容", "返回写入回执"]
    # before_text `# 标题\n\n第一段内容` splitlines 得 3 行
    assert "3" in intent["verifyPlan"]
    assert "expected_fingerprint" in intent["rollbackPlan"]


def test_obsidian_work_intent_counts_before_text_lines():
    before = "\n".join([f"行 {i}" for i in range(10)])
    intent = helpers._obsidian_work_intent("p.md", "overwrite", before_text=before)
    assert "10" in intent["verifyPlan"]


def test_obsidian_work_intent_handles_empty_before_text():
    intent = helpers._obsidian_work_intent("p.md", "overwrite")
    assert "0" in intent["verifyPlan"]


# ---------------------------------------------------------------------------
# _select_api_skills
# ---------------------------------------------------------------------------

def test_select_api_skills_uses_expert_scoped_skills_when_all_skills_missing(monkeypatch):
    """all_skills 为 None 时应回退到 _expert_scoped_skills，并把它的返回值喂给 plan_desktop_turn。"""
    captured: dict = {}

    def fake_plan(query, all_skills, llm_fallback=False):
        captured["query"] = query
        captured["all_skills"] = all_skills
        captured["llm_fallback"] = llm_fallback
        # 直接把传入的 all_skills 作为 raw_selected 返回，便于断言来源
        ns = type("NS", (), {"raw_selected": all_skills})()
        return ns

    scoped_skills = {"shell": "skill-obj"}
    monkeypatch.setattr(helpers, "_plan_desktop_turn", fake_plan)
    monkeypatch.setattr(helpers, "_expert_scoped_skills", lambda cfg=None: scoped_skills)

    result = helpers._select_api_skills("执行 ls -la")
    assert result is scoped_skills
    assert captured["query"] == "执行 ls -la"
    assert captured["all_skills"] is scoped_skills
    assert captured["llm_fallback"] is False


def test_select_api_skills_uses_provided_all_skills(monkeypatch):
    """显式传入 all_skills 时不应调用 _expert_scoped_skills。"""
    def fake_expert(cfg=None):
        raise AssertionError("不应调用 _expert_scoped_skills")

    def fake_plan(query, all_skills, llm_fallback=False):
        return type("NS", (), {"raw_selected": all_skills})()

    monkeypatch.setattr(helpers, "_expert_scoped_skills", fake_expert)
    monkeypatch.setattr(helpers, "_plan_desktop_turn", fake_plan)

    provided = {"obsidian_read": "skill"}
    result = helpers._select_api_skills("查询笔记", all_skills=provided)
    assert result is provided


# ---------------------------------------------------------------------------
# _make_api_tool_request
# ---------------------------------------------------------------------------

def test_make_api_tool_request_delegates_to_core_service(monkeypatch):
    """_make_api_tool_request 应转发到 core.api_tool_service.make_tool_request 并透传 cfg。"""
    captured: dict = {}

    def fake_make_tool_request(skill_name, args, skills, cfg=None, *,
                               event_id=None, display_name=None,
                               extra=None, force_approval=False):
        captured.update(
            skill_name=skill_name, args=args, skills=skills, cfg=cfg,
            event_id=event_id, display_name=display_name,
            extra=extra, force_approval=force_approval,
        )
        return {"kind": "tool_request", "eventId": event_id, "blocked": False}

    fake_cfg = {"model": "test"}
    monkeypatch.setattr(helpers, "_load_config", lambda: fake_cfg)
    monkeypatch.setattr("core.api_tool_service.make_tool_request", fake_make_tool_request)
    monkeypatch.setattr("skills.loader.load_skills", lambda: {"shell": object()})

    request = helpers._make_api_tool_request(
        "shell", {"command": "ls"}, event_id="evt-1",
        display_name="shell", extra={"k": "v"}, force_approval=True,
    )
    assert request["eventId"] == "evt-1"
    assert captured["skill_name"] == "shell"
    assert captured["args"] == {"command": "ls"}
    assert captured["cfg"] is fake_cfg
    assert captured["event_id"] == "evt-1"
    assert captured["display_name"] == "shell"
    assert captured["extra"] == {"k": "v"}
    assert captured["force_approval"] is True


def test_make_api_tool_request_defaults_force_approval_to_true(monkeypatch):
    """force_approval 默认为 True（安全保守策略）。"""
    captured: dict = {}

    def fake_make_tool_request(skill_name, args, skills, cfg=None, *,
                               event_id=None, display_name=None,
                               extra=None, force_approval=False):
        captured["force_approval"] = force_approval
        return {"eventId": event_id}

    monkeypatch.setattr(helpers, "_load_config", lambda: {})
    monkeypatch.setattr("core.api_tool_service.make_tool_request", fake_make_tool_request)
    monkeypatch.setattr("skills.loader.load_skills", lambda: {})

    helpers._make_api_tool_request(
        "shell", {}, event_id="evt-2", display_name="shell",
    )
    assert captured["force_approval"] is True
