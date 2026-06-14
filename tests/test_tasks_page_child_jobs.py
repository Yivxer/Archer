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
