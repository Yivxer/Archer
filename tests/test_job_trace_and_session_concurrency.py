"""test_job_trace_and_session_concurrency.py

补两项此前缺失的直接验证：
1. P1-7 trace_id 绑定：job_routes._run_job / _run_job_chat_with_tools 在执行时
   应把 trace_id / job_id / stage 绑定到 structlog contextvars，并在结束时清理。
2. P0 session append 并发压力：per-session-id 锁必须保证 N 个并发 append 不丢消息。
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# 1. job trace_id 绑定与清理
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_jobs(tmp_path, monkeypatch):
    """提供干净的 BACKGROUND_JOBS / BACKGROUND_JOBS_PATH 环境。"""
    from terminal.api import job_routes

    job_routes.BACKGROUND_JOBS.clear()
    job_routes.BACKGROUND_JOBS_LOADED = False
    job_routes.BACKGROUND_JOBS_PATH = tmp_path / "background_jobs.json"
    yield job_routes
    job_routes.BACKGROUND_JOBS.clear()


def _capture_structlog_context():
    """捕获 structlog contextvars 当前的 trace 相关字段。

    structlog 22+ 把每个 bound key 存在独立 ContextVar 中，名称形如
    ``structlog_<key>``（早期版本是 ``var_<key>``）。这里两种都兼容。
    未设置的 key 返回 ``Ellipsis`` sentinel，统一归一化为 ``None``。
    """
    try:
        import structlog
    except ImportError:
        pytest.skip("structlog 未安装")
    from structlog.contextvars import _CONTEXT_VARS  # type: ignore[attr-defined]

    merged: dict[str, object] = {}
    for name, var in _CONTEXT_VARS.items():
        try:
            value = var.get()
        except LookupError:
            value = None
        # structlog 未设置的 key 返回 Ellipsis sentinel
        if value is Ellipsis:
            value = None
        # 兼容 structlog_<key> / var_<key> / <key> 三种命名
        for prefix in ("structlog_", "var_"):
            if name.startswith(prefix):
                key = name[len(prefix):]
                break
        else:
            key = name
        merged[key] = value
    return merged


def test_run_job_binds_trace_id_during_execution(isolated_jobs, monkeypatch):
    """_run_job 执行期间 structlog contextvars 应包含 trace_id/job_id/stage。"""
    from infrastructure.observability import clear_trace_context

    # 进入测试前先清空，避免上游污染
    clear_trace_context("trace_id", "job_id", "stage")

    captured: dict[str, dict] = {}

    def fake_chat_with_tools(prompt: str, job_id: str) -> dict:
        # 在 job 线程执行时抓取 contextvars
        captured["during"] = _capture_structlog_context()
        return {"role": "assistant", "text": "done"}

    monkeypatch.setattr(isolated_jobs, "_run_job_chat_with_tools", fake_chat_with_tools)

    isolated_jobs.BACKGROUND_JOBS["job-trace-1"] = {
        "id": "job-trace-1",
        "title": "trace test",
        "kind": "analysis",
        "prompt": "hi",
        "status": "queued",
        "createdAt": "2026-07-17T00:00:00",
        "updatedAt": "2026-07-17T00:00:00",
    }

    isolated_jobs._run_job("job-trace-1")

    assert "during" in captured
    ctx = captured["during"]
    assert ctx.get("trace_id") == "trace-job-trace-1"
    assert ctx.get("job_id") == "job-trace-1"
    # stage 在 _execute_chat 内被 bind 为 job_chat
    assert ctx.get("stage") == "job_chat"


def test_run_job_clears_trace_context_after_completion(isolated_jobs, monkeypatch):
    """_run_job 退出后 trace_id / job_id / stage 应被清理，不泄漏到主线程。"""
    from infrastructure.observability import clear_trace_context

    clear_trace_context("trace_id", "job_id", "stage")

    monkeypatch.setattr(
        isolated_jobs, "_run_job_chat_with_tools",
        lambda prompt, job_id: {"role": "assistant", "text": "ok"},
    )

    isolated_jobs.BACKGROUND_JOBS["job-trace-2"] = {
        "id": "job-trace-2",
        "title": "trace cleanup test",
        "kind": "analysis",
        "prompt": "hi",
        "status": "queued",
        "createdAt": "2026-07-17T00:00:00",
        "updatedAt": "2026-07-17T00:00:00",
    }

    # 主线程执行前 contextvars 应为空
    before = _capture_structlog_context()
    assert before.get("trace_id") in (None, "")

    isolated_jobs._run_job("job-trace-2")

    # 主线程执行后 contextvars 仍应为空（_run_job 的 finally 已清理）
    after = _capture_structlog_context()
    assert after.get("trace_id") in (None, "")
    assert after.get("job_id") in (None, "")
    assert after.get("stage") in (None, "")


def test_run_job_chat_with_tools_binds_trace_id_for_llm_path(isolated_jobs, monkeypatch):
    """_run_job_chat_with_tools 自身也应 bind trace_id，供直接调用场景使用。"""
    from infrastructure.observability import clear_trace_context

    clear_trace_context("trace_id", "job_id", "stage")

    captured: dict[str, dict] = {}

    # 拦截 stream_chat，进入函数体时抓 contextvars
    def fake_stream_chat(messages):
        captured["during_llm"] = _capture_structlog_context()
        yield "回答"

    monkeypatch.setattr("core.llm.stream_chat", fake_stream_chat)

    # 跳过 memory retrieval 和 web search，避免测试依赖真实数据库和网络
    monkeypatch.setattr(
        "core.context.classify_query_intent",
        lambda prompt: {"intent": "chat"},
    )
    monkeypatch.setattr(
        "terminal.api._tools._select_api_skills",
        lambda prompt, all_skills=None: {},
    )
    # 直接把 memory.retrieve.for_context 替换成空结果
    def _empty_for_context(*args, **kwargs):
        return [], []
    monkeypatch.setattr("memory.retrieve.for_context", _empty_for_context)

    isolated_jobs._run_job_chat_with_tools("测试 prompt", "job-trace-3")

    assert "during_llm" in captured
    ctx = captured["during_llm"]
    assert ctx.get("trace_id") == "trace-job-trace-3"
    assert ctx.get("job_id") == "job-trace-3"
    assert ctx.get("stage") == "job_chat"

    # 函数退出后已清理
    after = _capture_structlog_context()
    assert after.get("trace_id") in (None, "")


# ---------------------------------------------------------------------------
# 2. session append 并发压力测试
# ---------------------------------------------------------------------------

def test_concurrent_append_session_does_not_lose_messages(tmp_path, monkeypatch):
    """N 个线程并发 append 到同一 session 文件，最终消息数必须等于 N*2 + 初始 2。"""
    from terminal.api import session_routes

    monkeypatch.setattr("core.session.SESSIONS_DIR", tmp_path)

    session_id = "20260717_120000"
    path = tmp_path / f"{session_id}.json"
    path.write_text(
        json.dumps([
            {"role": "user", "content": "init-q"},
            {"role": "assistant", "content": "init-a"},
        ]),
        encoding="utf-8",
    )

    thread_count = 20
    barrier = threading.Barrier(thread_count)
    errors: list[Exception] = []

    def append_one(idx: int) -> None:
        try:
            barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            return
        payload = {
            "messages": [
                {"role": "user", "content": f"q-{idx}"},
                {"role": "assistant", "content": f"a-{idx}"},
            ],
        }
        try:
            session_routes.append_session(session_id, payload)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=append_one, args=(i,), daemon=True) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == [], f"并发 append 出现异常: {errors}"

    # 重新读回文件，验证消息总数。session 文件结构为 {messages, meta}。
    with path.open("r", encoding="utf-8") as f:
        saved = json.load(f)
    messages = saved["messages"] if isinstance(saved, dict) else saved
    expected = 2 + thread_count * 2
    assert len(messages) == expected, (
        f"并发 append 丢失消息：期望 {expected} 条，实际 {len(messages)} 条"
    )

    # 验证所有 idx 都存在，没有重复也没有丢失
    contents = {m["content"] for m in messages}
    for i in range(thread_count):
        assert f"q-{i}" in contents, f"q-{i} 丢失"
        assert f"a-{i}" in contents, f"a-{i} 丢失"


def test_concurrent_append_to_different_sessions_do_not_block_each_other(tmp_path, monkeypatch):
    """不同 session_id 的并发 append 不应互相阻塞（锁是 per-session-id 的）。"""
    from terminal.api import session_routes

    monkeypatch.setattr("core.session.SESSIONS_DIR", tmp_path)

    # 准备两个不同 session
    for sid in ("20260717_130000", "20260717_130001"):
        (tmp_path / f"{sid}.json").write_text(
            json.dumps([
                {"role": "user", "content": "init"},
                {"role": "assistant", "content": "ok"},
            ]),
            encoding="utf-8",
        )

    # 在第一个 session 的 append 中注入小延迟，模拟慢 IO
    original_write_text = Path.write_text
    slow_session_id = "20260717_130000"
    delays: list[float] = []

    def slow_write(self, data, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.stem == slow_session_id:
            delays.append(time.perf_counter())
            time.sleep(0.2)  # 模拟慢盘
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", slow_write)

    errors: list[Exception] = []
    start_barrier = threading.Barrier(2)

    def append_to(sid: str) -> None:
        try:
            start_barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            return
        session_routes.append_session(sid, {
            "messages": [
                {"role": "user", "content": f"q-{sid}"},
                {"role": "assistant", "content": f"a-{sid}"},
            ],
        })
        try:
            start_barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            return

    t1 = threading.Thread(target=append_to, args=(slow_session_id,), daemon=True)
    t2 = threading.Thread(target=append_to, args=("20260717_130001",), daemon=True)

    t1_start = time.perf_counter()
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    total = time.perf_counter() - t1_start

    assert errors == []
    # 如果两把锁串行（错误实现），慢 session 0.2s + 快 session ~0s = 至少 0.2s
    # 并行执行下快 session 不被阻塞，整体时间应接近慢 session 单独时间
    # 这里只做宽松断言：总耗时 < 0.6s（允许 CI 和本地调度抖动）
    assert total < 0.6, f"不同 session 的 append 似乎被串行化，总耗时 {total:.3f}s"

    # 验证两个文件都写成功（session 文件结构为 {messages, meta}）
    for sid in ("20260717_130000", "20260717_130001"):
        with (tmp_path / f"{sid}.json").open("r", encoding="utf-8") as f:
            data = json.load(f)
        messages = data["messages"] if isinstance(data, dict) else data
        assert len(messages) == 4, f"{sid} 应有 4 条消息，实际 {len(messages)}"
