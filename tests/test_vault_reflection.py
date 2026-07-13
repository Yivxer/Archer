"""
test_vault_reflection.py — Vault Bridge Phase 2 测试

覆盖：
- LLM JSON 解析容错
- cooldown 机制
- 单篇笔记结晶（mock LLM）
- cooldown 命中跳过
- force 绕过 cooldown
- 批量扫描最近修改笔记
- 未配置 vault 降级
- API 路由 POST/GET /vault/reflection
"""
import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch
from terminal.api import job_routes as jobs

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _setup_db(tmp_dir: str):
    """初始化临时 DB + 配置，返回 store 模块。"""
    import memory.store as store_mod
    store_mod.DB_PATH = Path(tmp_dir) / "test.db"
    store_mod.init_db()
    return store_mod


def _setup_vault(tmp_dir: str) -> Path:
    """创建临时 vault，写一篇长笔记。"""
    vault = Path(tmp_dir) / "vault"
    vault.mkdir()
    note = vault / "测试笔记.md"
    note.write_text(
        "# 测试笔记\n\n"
        "今天思考了 Archer 和 Obsidian 的融合问题。"
        "核心矛盾在于：Archer 想要成为主大脑，但 Obsidian 用户习惯了在自己的编辑器里思考。"
        "解决方案是把 Obsidian 作为感知层，Archer 作为思考层。"
        "这样做的好处是用户不用切换工具，Archer 能自然感知用户在写什么。"
        "情绪上我感到兴奋但也有点焦虑，因为这是一个大方向的选择。"
        "方法论是：先做只读感知，验证可行性，再考虑写回。" * 3,
        encoding="utf-8",
    )
    return vault


def _mock_llm_response():
    """模拟 LLM 返回的结晶 JSON。"""
    return json.dumps({
        "core_insight": "Archer 与 Obsidian 的融合点是感知层与思考层分离",
        "core_tension": "主大脑定位与用户编辑器习惯之间的张力",
        "emotion_pattern": "兴奋与焦虑并存，面对大方向选择时的典型情绪",
        "reusable_method": "先做只读感知验证可行性，再考虑写回",
        "life_theme": "工具融合与数字伴生体",
        "related_threads": ["Archer 成长计划", "第二大脑"],
        "confidence": 0.85,
        "soul_worthy": True,
        "soul_note": "用户正在探索 AI 与知识库的融合范式",
    }, ensure_ascii=False)


# ── LLM JSON 解析 ──────────────────────────────────────────────────────────────

def test_parse_plain_json():
    from workflows.vault_reflection import _parse_llm_json
    result = _parse_llm_json('{"core_insight": "test", "confidence": 0.5}')
    assert result is not None
    assert result["core_insight"] == "test"


def test_parse_markdown_wrapped_json():
    from workflows.vault_reflection import _parse_llm_json
    raw = '```json\n{"core_insight": "wrapped", "confidence": 0.7}\n```'
    result = _parse_llm_json(raw)
    assert result is not None
    assert result["core_insight"] == "wrapped"


def test_parse_json_with_surrounding_text():
    from workflows.vault_reflection import _parse_llm_json
    raw = '好的，这是结果：\n{"core_insight": "extracted", "confidence": 0.6}\n以上。'
    result = _parse_llm_json(raw)
    assert result is not None
    assert result["core_insight"] == "extracted"


def test_parse_invalid_json_returns_none():
    from workflows.vault_reflection import _parse_llm_json
    assert _parse_llm_json("not json at all") is None
    assert _parse_llm_json("") is None


# ── cooldown 机制 ───────────────────────────────────────────────────────────────

def test_cooldown_blocks_within_window(tmp_path, monkeypatch):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    from workflows import vault_reflection as vr
    vr.init_reflections_table()

    # 记录一次结晶
    vr._record_reflection("note.md", "abc123", "Note", {"pending_ids": [1]}, "summary")

    # 应该在冷却期内
    cooling, last = vr._is_on_cooldown("note.md")
    assert cooling is True
    assert last != ""


def test_cooldown_expired_allows_rereflection(tmp_path):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    from workflows import vault_reflection as vr
    vr.init_reflections_table()

    # 记录一次结晶，时间戳设为很久以前
    conn = vr._conn()
    old_time = (datetime.now() - timedelta(hours=vr.COOLDOWN_HOURS + 1)).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO vault_reflections (note_path, note_hash, note_title, reflected_at, insights_count, pending_ids, confidence, summary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("old_note.md", "hash", "Old", old_time, 0, "[]", 0.0, ""),
    )
    conn.commit()
    conn.close()

    cooling, _ = vr._is_on_cooldown("old_note.md")
    assert cooling is False


# ── 单篇笔记结晶 ───────────────────────────────────────────────────────────────

def test_reflect_on_note_success(tmp_path, monkeypatch):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    vault = _setup_vault(str(tmp_path))

    # mock vault 配置
    from skills import _vault
    monkeypatch.setattr(_vault, "read_vault_path", lambda: vault)
    monkeypatch.setattr(_vault, "resolve_vault", lambda: vault.resolve())

    from workflows import vault_reflection as vr

    # mock LLM
    def mock_stream(messages, track_usage=False):
        yield _mock_llm_response()

    with patch("core.llm.stream_chat", mock_stream):
        result = vr.reflect_on_note("测试笔记.md", force=True)

    assert result["ok"] is True
    assert result["confidence"] >= 0.8
    assert len(result["pending_ids"]) >= 3  # insight + tension + emotion + method + theme

    # 验证 pending memory 已写入
    pends = store_mod.list_pending()
    assert len(pends) >= 3
    sources = {p["source"] for p in pends}
    assert "vault_reflection" in sources

    # 验证 soul proposal 已写入（confidence >= 0.7 且 soul_worthy）
    assert result["soul_proposal_id"] is not None


def test_reflect_on_note_cooldown_skip(tmp_path, monkeypatch):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    vault = _setup_vault(str(tmp_path))
    from skills import _vault
    monkeypatch.setattr(_vault, "read_vault_path", lambda: vault)
    monkeypatch.setattr(_vault, "resolve_vault", lambda: vault.resolve())

    from workflows import vault_reflection as vr

    def mock_stream(messages, track_usage=False):
        yield _mock_llm_response()

    # 第一次结晶
    with patch("core.llm.stream_chat", mock_stream):
        r1 = vr.reflect_on_note("测试笔记.md", force=True)
    assert r1["ok"] is True

    # 第二次不 force，应被 cooldown 跳过
    with patch("core.llm.stream_chat", mock_stream):
        r2 = vr.reflect_on_note("测试笔记.md", force=False)
    assert r2["ok"] is False
    assert r2.get("skipped") is True
    assert "冷却" in r2["reason"]


def test_reflect_on_note_force_bypasses_cooldown(tmp_path, monkeypatch):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    vault = _setup_vault(str(tmp_path))
    from skills import _vault
    monkeypatch.setattr(_vault, "read_vault_path", lambda: vault)
    monkeypatch.setattr(_vault, "resolve_vault", lambda: vault.resolve())

    from workflows import vault_reflection as vr

    def mock_stream(messages, track_usage=False):
        yield _mock_llm_response()

    with patch("core.llm.stream_chat", mock_stream):
        vr.reflect_on_note("测试笔记.md", force=True)

    # force=True 应绕过 cooldown
    with patch("core.llm.stream_chat", mock_stream):
        r2 = vr.reflect_on_note("测试笔记.md", force=True)
    assert r2["ok"] is True


def test_reflect_on_note_too_short(tmp_path, monkeypatch):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    vault = Path(tmp_path) / "vault"
    vault.mkdir()
    (vault / "短.md").write_text("太短了", encoding="utf-8")

    from skills import _vault
    monkeypatch.setattr(_vault, "read_vault_path", lambda: vault)
    monkeypatch.setattr(_vault, "resolve_vault", lambda: vault.resolve())

    from workflows import vault_reflection as vr
    result = vr.reflect_on_note("短.md", force=True)
    assert result["ok"] is False
    assert "太短" in result["reason"]


def test_reflect_on_note_unconfigured_vault(tmp_path, monkeypatch):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    from skills import _vault
    monkeypatch.setattr(_vault, "read_vault_path", lambda: None)
    monkeypatch.setattr(_vault, "resolve_vault", lambda: None)

    from workflows import vault_reflection as vr
    result = vr.reflect_on_note("any.md", force=True)
    assert result["ok"] is False
    assert "未配置" in result["reason"]


def test_reflect_on_note_llm_failure(tmp_path, monkeypatch):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    vault = _setup_vault(str(tmp_path))
    from skills import _vault
    monkeypatch.setattr(_vault, "read_vault_path", lambda: vault)
    monkeypatch.setattr(_vault, "resolve_vault", lambda: vault.resolve())

    from workflows import vault_reflection as vr

    # mock LLM 抛异常
    def mock_stream(messages, track_usage=False):
        raise RuntimeError("LLM down")
        yield  # noqa

    with patch("core.llm.stream_chat", mock_stream):
        result = vr.reflect_on_note("测试笔记.md", force=True)

    assert result["ok"] is False
    assert "LLM" in result["reason"]


# ── 批量扫描 ───────────────────────────────────────────────────────────────────

def test_reflect_on_recent_scans_modified_notes(tmp_path, monkeypatch):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    vault = Path(tmp_path) / "vault"
    vault.mkdir()
    # 写两篇足够长的笔记
    for name in ("note1.md", "note2.md"):
        (vault / name).write_text(
            "# " + name + "\n\n" + "这是一篇关于 Archer 的深度思考笔记。" * 20,
            encoding="utf-8",
        )

    from skills import _vault
    monkeypatch.setattr(_vault, "read_vault_path", lambda: vault)
    monkeypatch.setattr(_vault, "resolve_vault", lambda: vault.resolve())

    from workflows import vault_reflection as vr

    call_count = {"n": 0}
    def mock_stream(messages, track_usage=False):
        call_count["n"] += 1
        yield _mock_llm_response()

    with patch("core.llm.stream_chat", mock_stream):
        result = vr.reflect_on_recent(days=7, max_notes=5, force=True)

    assert result["ok"] is True
    assert result["total"] >= 1


def test_reflect_on_recent_progress_callback(tmp_path, monkeypatch):
    """progress_callback 应在每篇笔记完成后被调用，传入 {done, total, note_path, ok}。"""
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    vault = Path(tmp_path) / "vault"
    vault.mkdir()
    for name in ("note1.md", "note2.md"):
        (vault / name).write_text(
            "# " + name + "\n\n" + "这是一篇关于 Archer 的深度思考笔记。" * 20,
            encoding="utf-8",
        )

    from skills import _vault
    monkeypatch.setattr(_vault, "read_vault_path", lambda: vault)
    monkeypatch.setattr(_vault, "resolve_vault", lambda: vault.resolve())

    from workflows import vault_reflection as vr

    def mock_stream(messages, track_usage=False):
        yield _mock_llm_response()

    progress_events: list[dict] = []
    def capture_progress(p: dict) -> None:
        progress_events.append(p)

    with patch("core.llm.stream_chat", mock_stream):
        result = vr.reflect_on_recent(
            days=7, max_notes=5, force=True,
            progress_callback=capture_progress,
        )

    # 应该至少有 2 次进度回调（两篇笔记）
    assert len(progress_events) >= 2
    # 每次进度都包含 done/total/note_path/ok
    for p in progress_events:
        assert "done" in p
        assert "total" in p
        assert "note_path" in p
        assert "ok" in p
    # done 应该是递增的
    dones = [p["done"] for p in progress_events]
    assert dones == sorted(dones)
    # total 应该等于 batch_total
    assert result.get("batch_total") == dones[-1]


# ── API 路由 ───────────────────────────────────────────────────────────────────

def test_api_post_vault_reflection_single_note(tmp_path, monkeypatch):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    vault = _setup_vault(str(tmp_path))
    from skills import _vault
    monkeypatch.setattr(_vault, "read_vault_path", lambda: vault)
    monkeypatch.setattr(_vault, "resolve_vault", lambda: vault.resolve())

    from terminal.api import _routes as routes

    def mock_stream(messages, track_usage=False):
        yield _mock_llm_response()

    with patch("core.llm.stream_chat", mock_stream):
        status, payload = routes.payload_post("/vault/reflection", {
            "path": "测试笔记.md",
            "force": True,
        })

    assert status == 200
    assert payload["ok"] is True


def test_api_post_vault_reflection_missing_params(tmp_path):
    from terminal.api import _routes as routes
    status, payload = routes.payload_post("/vault/reflection", {})
    assert status == 200
    assert payload["ok"] is False
    assert "path" in payload["error"] or "days" in payload["error"]


def test_api_get_recent_reflections(tmp_path):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    from workflows import vault_reflection as vr
    vr.init_reflections_table()
    vr._record_reflection("note.md", "hash", "Title", {"pending_ids": [1]}, "summary")

    from terminal.api import _routes as routes
    status, payload = routes.payload_get("/vault/reflection/recent")

    assert status == 200
    assert payload["ok"] is True
    assert len(payload["reflections"]) >= 1
    assert payload["reflections"][0]["note_path"] == "note.md"


def test_api_get_recent_reflections_with_limit(tmp_path):
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()

    from workflows import vault_reflection as vr
    vr.init_reflections_table()
    for i in range(5):
        vr._record_reflection(f"note{i}.md", "hash", f"Title{i}", {"pending_ids": []}, "s")

    from terminal.api import _routes as routes
    status, payload = routes.payload_get("/vault/reflection/recent?limit=2")

    assert status == 200
    assert len(payload["reflections"]) == 2


# ── 后台 job 化（P0-1）─────────────────────────────────────────────────────────

def _reset_jobs(monkeypatch, tmp_path):
    """重置 BACKGROUND_JOBS 状态，避免跨测试污染。"""
    from terminal.api import _routes as routes
    from terminal.api import job_routes as jobs
    monkeypatch.setattr(jobs, "BACKGROUND_JOBS_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(jobs, "BACKGROUND_JOBS_LOADED", True)
    jobs.BACKGROUND_JOBS.clear()
    return routes


def test_api_post_vault_reflection_background_creates_job(tmp_path, monkeypatch):
    """background=true 时应创建后台 job，把参数打包进 vaultArgs，不同步执行。"""
    routes = _reset_jobs(monkeypatch, tmp_path)

    captured = {}

    def fake_create_job(payload):
        captured["payload"] = payload
        return {"ok": True, "job": {"id": "job-bg-1", "kind": "vault_reflection", "status": "queued"}}

    monkeypatch.setattr(routes, "_create_job", fake_create_job)

    status, payload = routes.payload_post("/vault/reflection", {
        "path": "测试笔记.md",
        "force": True,
        "background": True,
    })

    assert status == 200
    assert payload["ok"] is True
    assert payload["background"] is True
    assert payload["job"]["kind"] == "vault_reflection"
    # vaultArgs 正确打包
    assert captured["payload"]["vaultArgs"]["note_path"] == "测试笔记.md"
    assert captured["payload"]["vaultArgs"]["force"] is True
    assert captured["payload"]["kind"] == "vault_reflection"
    # 默认 timeout 应 >= 300（避免长任务被掐）
    assert captured["payload"]["timeoutSeconds"] >= 300


def test_api_post_vault_reflection_background_days(tmp_path, monkeypatch):
    """background=true + days 应打包 days/maxNotes 进 vaultArgs。"""
    routes = _reset_jobs(monkeypatch, tmp_path)

    captured = {}

    def fake_create_job(payload):
        captured["payload"] = payload
        return {"ok": True, "job": {"id": "job-bg-2", "kind": "vault_reflection"}}

    monkeypatch.setattr(routes, "_create_job", fake_create_job)

    status, payload = routes.payload_post("/vault/reflection", {
        "days": 14,
        "maxNotes": 8,
        "background": True,
    })

    assert status == 200
    assert payload["background"] is True
    assert captured["payload"]["vaultArgs"]["days"] == 14
    assert captured["payload"]["vaultArgs"]["maxNotes"] == 8


def test_api_post_vault_reflection_background_missing_params(tmp_path, monkeypatch):
    """background=true 但缺 path/days 应返回错误。"""
    routes = _reset_jobs(monkeypatch, tmp_path)

    def fake_create_job(payload):  # 不应被调用
        raise AssertionError("_create_job should not be called")

    monkeypatch.setattr(routes, "_create_job", fake_create_job)

    status, payload = routes.payload_post("/vault/reflection", {
        "background": True,
    })

    assert status == 200
    assert payload["ok"] is False
    assert "path" in payload["error"] or "days" in payload["error"]


def test_run_job_vault_reflection_dispatches_note(tmp_path, monkeypatch):
    """_run_job 对 kind=vault_reflection + note_path 的 job 应调 reflect_on_note。"""
    routes = _reset_jobs(monkeypatch, tmp_path)

    job_id = "job-run-note"
    jobs.BACKGROUND_JOBS[job_id] = {
        "id": job_id,
        "title": "Vault 结晶：测试.md",
        "kind": "vault_reflection",
        "prompt": "Vault 结晶：测试.md",
        "status": "queued",
        "result": "",
        "createdAt": datetime.now().isoformat(),
        "updatedAt": datetime.now().isoformat(),
        "timeoutSeconds": 60,
        "vaultArgs": {"note_path": "测试.md", "force": True},
    }

    called = {}

    def fake_reflect_on_note(path, force=False):
        called["path"] = path
        called["force"] = force
        return {"ok": True, "note_path": path, "pending_ids": [1, 2], "confidence": 0.8}

    monkeypatch.setattr("workflows.vault_reflection.reflect_on_note", fake_reflect_on_note)

    jobs._run_job(job_id)

    job = jobs.BACKGROUND_JOBS[job_id]
    assert job["status"] == "complete"
    assert called["path"] == "测试.md"
    assert called["force"] is True
    result = json.loads(job["result"])
    assert result["ok"] is True
    assert result["pending_ids"] == [1, 2]


def test_run_job_vault_reflection_dispatches_recent(tmp_path, monkeypatch):
    """_run_job 对 kind=vault_reflection + days 的 job 应调 reflect_on_recent。"""
    routes = _reset_jobs(monkeypatch, tmp_path)

    job_id = "job-run-recent"
    jobs.BACKGROUND_JOBS[job_id] = {
        "id": job_id,
        "title": "Vault 结晶：最近 7 天",
        "kind": "vault_reflection",
        "prompt": "Vault 结晶：最近 7 天",
        "status": "queued",
        "result": "",
        "createdAt": datetime.now().isoformat(),
        "updatedAt": datetime.now().isoformat(),
        "timeoutSeconds": 60,
        "vaultArgs": {"days": 7, "maxNotes": 3, "force": True},
    }

    called = {}

    def fake_reflect_on_recent(days=7, max_notes=5, force=False, progress_callback=None):
        called["days"] = days
        called["max_notes"] = max_notes
        called["force"] = force
        called["progress_callback"] = progress_callback
        return {"ok": True, "reflected": [], "total": 0}

    monkeypatch.setattr("workflows.vault_reflection.reflect_on_recent", fake_reflect_on_recent)

    jobs._run_job(job_id)

    job = jobs.BACKGROUND_JOBS[job_id]
    assert job["status"] == "complete"
    assert called["days"] == 7
    assert called["max_notes"] == 3
    assert called["force"] is True
    assert called["progress_callback"] is not None


def test_run_job_vault_reflection_progress_updates_job(tmp_path, monkeypatch):
    """progress_callback 应实时把进度写入 job.progress 字段供前端轮询。"""
    routes = _reset_jobs(monkeypatch, tmp_path)

    job_id = "job-run-prog"
    jobs.BACKGROUND_JOBS[job_id] = {
        "id": job_id,
        "title": "Vault 结晶：最近 7 天",
        "kind": "vault_reflection",
        "prompt": "Vault 结晶：最近 7 天",
        "status": "queued",
        "result": "",
        "createdAt": datetime.now().isoformat(),
        "updatedAt": datetime.now().isoformat(),
        "timeoutSeconds": 60,
        "vaultArgs": {"days": 7, "maxNotes": 3, "force": True},
    }

    def fake_reflect_on_recent(days=7, max_notes=5, force=False, progress_callback=None):
        for i in range(1, 4):
            progress_callback({"done": i, "total": 3, "note_path": f"n{i}.md", "ok": True})
        return {"ok": True, "reflected": [], "total": 3}

    monkeypatch.setattr("workflows.vault_reflection.reflect_on_recent", fake_reflect_on_recent)

    jobs._run_job(job_id)

    job = jobs.BACKGROUND_JOBS[job_id]
    assert job["status"] == "complete"
    assert "progress" in job
    assert len(job["progress"]) == 3
    assert job["progress"][0]["done"] == 1
    assert job["progress"][2]["note_path"] == "n3.md"


def test_run_job_vault_reflection_failure_marks_failed(tmp_path, monkeypatch):
    """reflect_on_note 抛异常时 job 应被标记为 failed，error 字段非空。"""
    routes = _reset_jobs(monkeypatch, tmp_path)

    job_id = "job-run-fail"
    jobs.BACKGROUND_JOBS[job_id] = {
        "id": job_id,
        "title": "Vault 结晶：bad.md",
        "kind": "vault_reflection",
        "prompt": "Vault 结晶：bad.md",
        "status": "queued",
        "result": "",
        "createdAt": datetime.now().isoformat(),
        "updatedAt": datetime.now().isoformat(),
        "timeoutSeconds": 60,
        "vaultArgs": {"note_path": "bad.md", "force": False},
    }

    def boom(path, force=False):
        raise RuntimeError("boom")

    monkeypatch.setattr("workflows.vault_reflection.reflect_on_note", boom)

    jobs._run_job(job_id)

    job = jobs.BACKGROUND_JOBS[job_id]
    assert job["status"] == "failed"
    assert "boom" in str(job.get("error", ""))
