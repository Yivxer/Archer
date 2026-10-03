"""Keep task HTTP operations behind one projection without reading user state."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "client/desktop/src/renderer/src"


def test_jobs_transport_and_page_projection_have_one_owner():
    local = (ROOT / "adapters/localArcher.ts").read_text()
    for operation in ("createBackgroundJob", "listBackgroundJobs", "fetchBackgroundJob", "cancelBackgroundJob", "retryBackgroundJob", "approveJobTool", "spawnChildJobs", "pollBackgroundJobEvents"):
        assert f"function {operation}(" not in local
    store = (ROOT / "lib/jobStore.ts").read_text()
    assert "from '../adapters/jobAdapter'" in store
    tasks = (ROOT / "pages/TasksPage.tsx").read_text()
    assert "ArcherAdapter" not in tasks
    assert "canAct=" in tasks
    assert "busyIds" in tasks
    chat = (ROOT / "pages/ChatPage.tsx").read_text()
    assert "from '../adapters/jobAdapter'" not in chat
    assert "pollBackgroundJobEvents" in chat
    assert "useJobStore" in chat
    main = (ROOT / "main.tsx").read_text()
    assert "void loadJobList({ force: true })" in main


def test_job_adapter_preserves_existing_http_boundary():
    adapter = (ROOT / "adapters/jobAdapter.ts").read_text()
    assert "getJson, postJson" in adapter
    assert "'/jobs'" in adapter
    assert "jobSnapshotToAgentEvent" not in adapter
    assert "localStorage" not in adapter
    assert "sqlite" not in adapter
