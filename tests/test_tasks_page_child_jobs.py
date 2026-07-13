from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_PAGE = ROOT / "client/desktop/src/renderer/src/pages/TasksPage.tsx"


def test_tasks_page_shows_child_job_summaries():
    source = TASKS_PAGE.read_text()

    assert "job.children" in source
    assert "子任务" in source
    assert "task-child-list" in source
    assert "jobStatusLabel(child.status)" in source
    assert "task-child-isolated" in source
    assert "task-child-row-head" in source
    assert "childStatusIcon" in source
    assert "子任务汇总" in source
    assert "buildChildJobsSummary" in source
    assert "fetchBackgroundJob" in source


def test_tasks_page_has_manual_child_job_entry():
    source = TASKS_PAGE.read_text()

    assert "spawnChildJobs" in source
    assert "拆分子任务" in source
    assert "childDrafts" in source
    assert "handleSpawnChildren" in source
    assert "onSpawnChildren" in source
    assert "添加一行" in source
    assert "批量创建子任务" in source


def test_build_child_jobs_summary_format():
    source = TASKS_PAGE.read_text()
    assert "summarizeChildProgress" in source
    assert "childProgress.complete" in source
    assert "复制汇总" in source


# ── P5.19 auto rollup tests ──────────────────────────────────────────────────


def test_auto_rollup_parent_result():
    """When all child jobs complete, parent result is auto-aggregated."""
    from terminal.api.job_routes import (
        _try_rollup_parent_result,
        BACKGROUND_JOBS,
        BACKGROUND_JOB_LOCK,
    )

    parent_id = "job-auto-rollup-parent"
    child1_id = "job-auto-rollup-c1"
    child2_id = "job-auto-rollup-c2"

    with BACKGROUND_JOB_LOCK:
        BACKGROUND_JOBS[parent_id] = {
            "id": parent_id,
            "title": "测试父任务",
            "status": "running",
            "kind": "chat",
            "prompt": "parent prompt",
            "childJobIds": [child1_id, child2_id],
            "result": "",
            "createdAt": "2026-06-15T00:00:00",
            "updatedAt": "2026-06-15T00:00:00",
        }
        BACKGROUND_JOBS[child1_id] = {
            "id": child1_id,
            "title": "[子] 步骤一",
            "status": "complete",
            "kind": "chat",
            "prompt": "child1",
            "parentJobId": parent_id,
            "result": "步骤一完成",
            "createdAt": "...",
            "updatedAt": "...",
        }
        BACKGROUND_JOBS[child2_id] = {
            "id": child2_id,
            "title": "[子] 步骤二",
            "status": "complete",
            "kind": "chat",
            "prompt": "child2",
            "parentJobId": parent_id,
            "result": "步骤二完成",
            "createdAt": "...",
            "updatedAt": "...",
        }

    result = _try_rollup_parent_result(parent_id)

    with BACKGROUND_JOB_LOCK:
        parent = BACKGROUND_JOBS.get(parent_id)

    assert result is True
    assert parent is not None
    assert parent["status"] == "complete"
    assert "步骤一" in parent["result"]
    assert "步骤二" in parent["result"]
    assert "[complete]" in parent["result"]


def test_rollup_skips_when_children_running():
    """Do NOT rollup if any child is still running."""
    from terminal.api.job_routes import (
        _try_rollup_parent_result,
        BACKGROUND_JOBS,
        BACKGROUND_JOB_LOCK,
    )

    parent_id = "job-skip-parent"
    child_id = "job-skip-c1"

    with BACKGROUND_JOB_LOCK:
        BACKGROUND_JOBS[parent_id] = {
            "id": parent_id,
            "title": "父任务",
            "status": "running",
            "kind": "chat",
            "prompt": "p",
            "childJobIds": [child_id],
            "result": "",
            "createdAt": "...",
            "updatedAt": "...",
        }
        BACKGROUND_JOBS[child_id] = {
            "id": child_id,
            "title": "[子] 运行中",
            "status": "running",
            "kind": "chat",
            "prompt": "c",
            "parentJobId": parent_id,
            "result": "",
            "createdAt": "...",
            "updatedAt": "...",
        }

    result = _try_rollup_parent_result(parent_id)
    assert result is False


def test_rollup_handles_failed_child():
    """Failed child results are included in rollup with error info."""
    from terminal.api.job_routes import (
        _try_rollup_parent_result,
        BACKGROUND_JOBS,
        BACKGROUND_JOB_LOCK,
    )

    parent_id = "job-fail-parent"
    child_id = "job-fail-c1"

    with BACKGROUND_JOB_LOCK:
        BACKGROUND_JOBS[parent_id] = {
            "id": parent_id,
            "title": "父任务",
            "status": "running",
            "kind": "chat",
            "prompt": "p",
            "childJobIds": [child_id],
            "result": "",
            "createdAt": "...",
            "updatedAt": "...",
        }
        BACKGROUND_JOBS[child_id] = {
            "id": child_id,
            "title": "[子] 失败子任务",
            "status": "failed",
            "kind": "chat",
            "prompt": "c",
            "parentJobId": parent_id,
            "result": "",
            "error": "子任务执行超时",
            "createdAt": "...",
            "updatedAt": "...",
        }

    result = _try_rollup_parent_result(parent_id)

    with BACKGROUND_JOB_LOCK:
        parent = BACKGROUND_JOBS.get(parent_id)

    assert result is True
    assert parent is not None
    assert parent["status"] == "complete"
    assert "失败子任务" in parent["result"]
    assert "子任务执行超时" in parent["result"]
    assert "[failed]" in parent["result"]


def test_rollup_no_children_returns_false():
    """Parent without children returns False."""
    from terminal.api.job_routes import (
        _try_rollup_parent_result,
        BACKGROUND_JOBS,
        BACKGROUND_JOB_LOCK,
    )

    parent_id = "job-no-children"

    with BACKGROUND_JOB_LOCK:
        BACKGROUND_JOBS[parent_id] = {
            "id": parent_id,
            "title": "无子任务",
            "status": "running",
            "kind": "chat",
            "prompt": "p",
            "childJobIds": [],
            "result": "",
            "createdAt": "...",
            "updatedAt": "...",
        }

    result = _try_rollup_parent_result(parent_id)
    assert result is False
