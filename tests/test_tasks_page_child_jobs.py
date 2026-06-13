from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASKS_PAGE = ROOT / "client/desktop/src/renderer/src/pages/TasksPage.tsx"


def test_tasks_page_shows_child_job_summaries():
    source = TASKS_PAGE.read_text()

    assert "job.children" in source
    assert "子任务" in source
    assert "task-child-list" in source
    assert "jobStatusLabel(child.status)" in source


def test_tasks_page_has_manual_child_job_entry():
    source = TASKS_PAGE.read_text()

    assert "spawnChildJobs" in source
    assert "拆分子任务" in source
    assert "childTitle" in source
    assert "childPrompt" in source
    assert "handleSpawnChild" in source
    assert "await onSpawnChild" in source
