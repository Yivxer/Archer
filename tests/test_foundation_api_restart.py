"""Exercise persisted REST decisions across two fresh, synthetic API processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOKEN = "foundation-offline-token"
CONTENT = "青禾项目先核对备份，再安装。"
REJECTED = "未经确认的虚构习惯，不应成为有效记忆。"
MESSAGES = [
    {"role": "user", "content": "目标：验证青禾项目的安装恢复"},
    {"role": "assistant", "content": "决定：先核对备份，再安装"},
    {"role": "user", "content": "不对，纠正为只核对本地备份"},
    {"role": "assistant", "content": "已确认只核对本地备份"},
    {"role": "user", "content": "接下来继续恢复检查，尚未完成"},
]
JOB = {
    "title": "脱敏取消检查", "kind": "analysis", "prompt": "先不要执行",
    "autoStart": False, "commandId": "foundation-offline-create-once",
}


def _configure_process(state: Path) -> Any:
    """Inject local paths, retaining the actual REST and persistence code."""
    from core import session, thread_store
    from core.runtime_context import create_runtime_context
    from memory import store, thread_context
    from terminal.api import _config, job_routes, tool_approval_routes
    from terminal.api.fastapi_app import create_app

    db = state / "archer.db"
    store.DB_PATH = db
    store._try_embed = lambda *args: None
    store.init_db()
    thread_context.memory_db_path = lambda: db
    thread_store.THREADS_PATH = state / "threads.json"
    thread_store.DEFAULT_THREADS_PATH = thread_store.THREADS_PATH
    session.SESSIONS_DIR = state / "sessions"
    job_routes.BACKGROUND_JOBS_PATH = state / "jobs.json"
    _config.TOOL_DRAFTS_DIR = state / "drafts"
    _config.TOOL_APPROVAL_AUDIT_LOG_PATH = state / "approval-audit.jsonl"

    def forbidden_execution(*args: Any, **kwargs: Any) -> None:
        (state / "unexpected-side-effect").write_text("executor called")
        raise AssertionError("denied or queued fixture must never execute")

    tool_approval_routes._run_approved_draft = forbidden_execution
    job_routes._run_job_chat_with_tools = forbidden_execution
    return create_app(TOKEN, runtime_context=create_runtime_context(db_path=db))


def _request(client: Any, path: str, payload: dict | None = None) -> dict:
    response = (
        client.get(path) if payload is None else client.post(path, json=payload)
    )
    assert response.status_code == 200, (path, response.status_code, response.text)
    return response.json()


def _deny(client: Any, state: Path) -> dict:
    from terminal.api._config import set_tool_draft

    draft = {
        "kind": "tool_request", "eventId": "foundation-denied-write",
        "skillName": "obsidian_write",
        "args": {"path": str(state / "original.md"), "content": "不应写入", "mode": "overwrite"},
    }
    set_tool_draft(draft["eventId"], draft)
    result = _request(client, "/tool-approvals", {
        "eventId": draft["eventId"], "decision": "denied",
    })
    assert result["executed"] is False
    assert result["outbox"]["status"] == "cancelled"
    assert (state / "original.md").read_text() == "必须保留的脱敏原文"
    assert not (state / "unexpected-side-effect").exists()
    return result


def _seed(client: Any, state: Path) -> dict:
    saved = _request(client, "/sessions", {"messages": MESSAGES})
    accepted = _request(client, "/memory/remember", {"content": CONTENT})
    rejected = _request(client, "/memory/remember", {"content": REJECTED})
    assert accepted["status"] == rejected["status"] == "pending"
    assert accepted["requiresReview"] and rejected["requiresReview"]
    resolution = _request(client, f"/memory/pending/{accepted['id']}/accept", {})
    assert resolution["ok"] and len(resolution["writtenIds"]) == 1
    repeated = _request(client, f"/memory/pending/{accepted['id']}/accept", {})
    assert repeated["writtenIds"] == []
    assert _request(client, f"/memory/pending/{rejected['id']}/reject", {})["ok"]
    denied = _deny(client, state)
    repeated_deny = _request(client, "/tool-approvals", {
        "eventId": "foundation-denied-write", "decision": "denied",
    })
    assert not repeated_deny["executed"]
    assert repeated_deny["outbox"]["id"] == denied["outbox"]["id"]
    created = _request(client, "/jobs", JOB)
    replay = _request(client, "/jobs", JOB)
    assert replay["replayed"] and replay["job"]["id"] == created["job"]["id"]
    cancelled = _request(client, f"/jobs/{created['job']['id']}/cancel", {})
    assert cancelled["job"]["status"] == "cancelled"
    return {
        "sessionId": saved["id"], "threadId": saved["threadId"],
        "acceptedId": accepted["id"], "rejectedId": rejected["id"],
        "writtenId": resolution["writtenIds"][0], "jobId": created["job"]["id"],
        "outboxId": denied["outbox"]["id"], "processId": os.getpid(),
    }


def _resume(client: Any, state: Path, before: dict) -> dict:
    session = _request(client, f"/sessions/{before['sessionId']}")
    assert [item["text"] for item in session["messages"]] == [item["content"] for item in MESSAGES]
    assert session["threadId"] == before["threadId"]
    thread = _request(client, f"/threads/{before['threadId']}")
    capsule = thread["contextState"]
    assert capsule["goal"] == MESSAGES[0]["content"]
    assert MESSAGES[1]["content"] in capsule["decisions"]
    assert MESSAGES[2]["content"] in capsule["corrections"]
    assert MESSAGES[-1]["content"] in capsule["pending"]
    assert thread["lastStop"] == MESSAGES[-1]["content"]
    memory = _request(client, "/memory?include_rejected=true")["data"]
    confirmed = [item for item in memory if item["status"] == "confirmed"]
    assert [(item["id"], item["content"]) for item in confirmed] == [(before["writtenId"], CONTENT)]
    assert any(item["id"] == before["rejectedId"] and item["status"] == "rejected" for item in memory)
    assert not _request(client, f"/memory/pending/{before['acceptedId']}/accept", {})["ok"]
    _request(client, f"/memory/pending/{before['rejectedId']}/reject", {})
    replay = _request(client, "/jobs", JOB)
    assert replay["replayed"] and replay["job"]["id"] == before["jobId"]
    assert replay["job"]["status"] == "cancelled"
    assert len(_request(client, "/jobs")["jobs"]) == 1
    denied = _deny(client, state)
    assert denied["outbox"]["id"] == before["outboxId"]
    window = _request(client, "/runtime/authority/background-job/evidence-window")["evidenceWindow"]
    assert window["migrationMode"] == "shadow" and not window["authorityEnabled"]
    return {"processId": os.getpid(), "restored": True, "sideEffects": 0}


def _phase(phase: str, state: Path) -> None:
    from fastapi.testclient import TestClient

    with TestClient(_configure_process(state)) as client:
        assert client.get("/sessions").status_code == 401
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        if phase == "seed":
            (state / "original.md").write_text("必须保留的脱敏原文")
            result = _seed(client, state)
        else:
            result = _resume(client, state, json.loads((state / "seed.json").read_text()))
        assert not (state / "unexpected-side-effect").exists()
        (state / f"{phase}.json").write_text(json.dumps(result))


def test_rest_decisions_and_stopping_point_survive_fresh_api_process(tmp_path: Path) -> None:
    if "ARCHER_OFFLINE_PROTECTED_ROOTS" not in os.environ:
        pytest.skip("requires run_tests.sh synthetic checkout and user-state guard")
    for phase in ("seed", "resume"):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), phase, str(tmp_path)],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
        )
        assert result.returncode == 0, result.stdout[-1000:] + result.stderr[-5000:]
    seeded = json.loads((tmp_path / "seed.json").read_text())
    restored = json.loads((tmp_path / "resume.json").read_text())
    assert seeded["processId"] != restored["processId"]
    assert restored["restored"] and restored["sideEffects"] == 0


if __name__ == "__main__":
    _phase(sys.argv[1], Path(sys.argv[2]))
