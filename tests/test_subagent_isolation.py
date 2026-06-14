"""P5.4 — Subagent context isolation tests."""
from __future__ import annotations

from core.policy import Decision, SUBTASK_DENY_LIST, check_subtask
from core.subagent_context import (
    MAX_PARALLEL_CHILD_JOBS,
    SUBTASK_ALLOW_LIST,
    build_subagent_system_prompt,
    filter_subagent_skills,
    is_isolated_job,
    select_subagent_enrichment_skills,
)
from core.subtask_runner import _AGENT_SKILLS_FILTER, _filter_skills


def test_build_subagent_system_prompt_omits_memory_and_soul_layers():
    prompt = build_subagent_system_prompt(
        {},
        task_title="检查计划",
        task_prompt="列出 growth plan 未完成项",
        agent_type="explore",
    )

    assert "子任务隔离模式" in prompt
    assert "不访问主对话历史" in prompt
    assert "长期记忆检索" in prompt
    assert "以下是 Archer 本地记忆检索结果" not in prompt
    assert "matched_skills" not in prompt.lower()


def test_filter_subagent_skills_only_allows_readonly_set():
    skills = {
        "web_search": object(),
        "shell": object(),
        "obsidian_write": object(),
        "file_ops": object(),
    }
    filtered = filter_subagent_skills(skills)

    assert set(filtered) <= set(SUBTASK_ALLOW_LIST)
    assert "shell" not in filtered
    assert "obsidian_write" not in filtered
    assert "web_search" in filtered


def test_check_subtask_denies_side_effect_tools():
    for skill in ("shell", "obsidian_write", "github_ops"):
        assert skill in SUBTASK_DENY_LIST
        result = check_subtask(skill, {})
        assert result.decision == Decision.DENY


def test_check_subtask_denies_file_ops_write():
    result = check_subtask("file_ops", {"action": "write", "path": "x.txt"})
    assert result.decision == Decision.DENY
    assert "写入" in result.reason


def test_check_subtask_allows_file_ops_read():
    result = check_subtask("file_ops", {"action": "read", "path": "README.md"})
    assert result.decision == Decision.ALLOW


def test_subtask_runner_work_agent_uses_allow_list_not_full_skills():
    assert _AGENT_SKILLS_FILTER["work"] == list(SUBTASK_ALLOW_LIST)
    skills = {"web_search": 1, "shell": 2, "file_ops": 3}
    filtered = _filter_skills(skills, _AGENT_SKILLS_FILTER["work"])
    assert "shell" not in filtered
    assert "web_search" in filtered


def test_is_isolated_job_detects_parent_and_flag():
    assert is_isolated_job({"parentJobId": "job-parent"})
    assert is_isolated_job({"isolated": True})
    assert not is_isolated_job({"id": "job-root"})


def test_select_subagent_enrichment_skills_is_subset_of_allow_list():
    selected = select_subagent_enrichment_skills("请搜索 Archer P5.4 设计文档 https://example.com")
    assert selected <= set(SUBTASK_ALLOW_LIST)


def test_child_job_concurrency_limit_constant():
    assert MAX_PARALLEL_CHILD_JOBS == 3


def test_isolated_child_job_skips_memory(monkeypatch, tmp_path):
    import time
    from terminal.api import _routes as routes

    memory_called = {"value": False}

    def fake_for_context(*args, **kwargs):
        memory_called["value"] = True
        return [], []

    monkeypatch.setattr("memory.retrieve.for_context", fake_for_context)

    jobs_path = tmp_path / "background_jobs.json"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    routes.BACKGROUND_JOBS.clear()
    routes.BACKGROUND_JOBS_LOADED = False
    routes.BACKGROUND_JOBS_PATH = jobs_path

    def fake_isolated(prompt, job):
        return {"role": "assistant", "text": "isolated ok"}

    monkeypatch.setattr(routes, "_run_isolated_child_job_chat", fake_isolated)

    _, created = routes.payload_post("/jobs", {
        "title": "父",
        "kind": "analysis",
        "prompt": "parent",
        "autoStart": False,
    })
    parent_id = created["job"]["id"]

    _, spawn_payload = routes.payload_post(f"/jobs/{parent_id}/spawn", {
        "children": [{
            "title": "子",
            "kind": "analysis",
            "prompt": "child task",
            "autoStart": True,
        }],
    })
    child_id = spawn_payload["children"][0]["id"]

    detail_payload = {}
    for _ in range(50):
        _, detail_payload = routes.payload_get(f"/jobs/{child_id}")
        if detail_payload["job"]["status"] == "complete":
            break
        time.sleep(0.01)

    assert detail_payload["job"]["status"] == "complete"
    assert detail_payload["job"]["result"] == "isolated ok"
    assert memory_called["value"] is False
