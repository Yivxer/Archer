from pathlib import Path

from core.job_result_evidence import build_legacy_job_result_artifact

ROOT = Path(__file__).resolve().parents[1]
TASKS_PAGE = ROOT / "client/desktop/src/renderer/src/pages/TasksPage.tsx"
CHAT_PAGE = ROOT / "client/desktop/src/renderer/src/pages/ChatPage.tsx"


def _verified_child(job: dict) -> dict:
    artifact = build_legacy_job_result_artifact(
        job,
        str(job["result"]),
        created_at=str(job["updatedAt"]),
    )
    job["resultArtifact"] = artifact
    job["resultVerification"] = {
        "id": f"verification-{job['id']}",
        "artifactId": artifact["id"],
        "status": "verified",
    }
    return job


def test_tasks_page_uses_server_authoritative_job_store():
    source = TASKS_PAGE.read_text()
    chat_source = CHAT_PAGE.read_text()

    assert "from '../lib/jobStore'" in source
    assert "useJobStore" in source
    assert "loadJobList" in source
    assert "loadJobDetail" in source
    assert "setTimeout(() => void refreshJobs" not in source
    assert "mergeJobEvent" in chat_source
    assert "useJobStore" in chat_source
    assert "loadJobList" in chat_source
    assert "listBackgroundJobs" not in chat_source


def test_tasks_and_chat_project_non_terminal_runtime_runs():
    tasks_source = TASKS_PAGE.read_text()
    chat_source = CHAT_PAGE.read_text()
    panel_source = (
        ROOT
        / "client/desktop/src/renderer/src/components/WorkspaceContextPanel.tsx"
    ).read_text()

    assert "from '../lib/runtimeRunStore'" in tasks_source
    assert "loadRuntimeRuns()" in tasks_source
    assert "运行中的 Run" in tasks_source
    assert "runtimeRunStateLabel" in tasks_source
    assert "useRuntimeRunStore" in chat_source
    assert "runtimeRuns.length > 0 || runtimePlans.length > 0" in chat_source
    assert "runtimeRuns={runtimeRuns}" in chat_source
    assert "workspaceRunStateLabel" in panel_source


def test_tasks_page_retries_only_uncertain_runtime_verification():
    source = TASKS_PAGE.read_text()
    adapter_source = (
        ROOT
        / "client/desktop/src/renderer/src/adapters/runtimeRunsAdapter.ts"
    ).read_text()

    assert "retryRuntimeRun" in source
    assert "run.state === 'uncertain'" in source
    assert "重新验证" in source
    assert "未重复写入 Obsidian" in source
    assert "/resume" in adapter_source
    assert "cancelRuntimeRun" in source
    assert "canCancelRuntimeRun" in source
    assert "正在抑制迟到结果" in source
    assert "/cancel" in adapter_source


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
    assert "loadJobDetail" in source


def test_tasks_page_has_manual_child_job_entry():
    source = TASKS_PAGE.read_text()

    assert "spawnChildren" in source
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
        BACKGROUND_JOB_LOCK,
        BACKGROUND_JOBS,
        _try_rollup_parent_result,
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
        BACKGROUND_JOBS[child1_id] = _verified_child({
            "id": child1_id,
            "title": "[子] 步骤一",
            "status": "complete",
            "kind": "chat",
            "prompt": "child1",
            "parentJobId": parent_id,
            "result": "步骤一完成",
            "createdAt": "...",
            "updatedAt": "...",
        })
        BACKGROUND_JOBS[child2_id] = _verified_child({
            "id": child2_id,
            "title": "[子] 步骤二",
            "status": "complete",
            "kind": "chat",
            "prompt": "child2",
            "parentJobId": parent_id,
            "result": "步骤二完成",
            "createdAt": "...",
            "updatedAt": "...",
        })

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
        BACKGROUND_JOB_LOCK,
        BACKGROUND_JOBS,
        _try_rollup_parent_result,
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


def test_rollup_failed_child_fails_parent_conservatively():
    """A failed child cannot be aggregated into a successful parent result."""
    from terminal.api.job_routes import (
        BACKGROUND_JOB_LOCK,
        BACKGROUND_JOBS,
        _try_rollup_parent_result,
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
    assert parent["status"] == "failed"
    assert parent["result"] == ""
    assert parent["failureKeyword"] == "child_rollup_child_not_complete"
    assert parent["terminalFinalizations"][0]["source"] == "child_rollup"


def test_rollup_no_children_returns_false():
    """Parent without children returns False."""
    from terminal.api.job_routes import (
        BACKGROUND_JOB_LOCK,
        BACKGROUND_JOBS,
        _try_rollup_parent_result,
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
