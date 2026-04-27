"""
P2-C — Doctor Tests
验证各检查项的 OK / WARN / ERROR 分支，以及 --fix 修复逻辑。
"""
import sqlite3
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import core.artifacts as art_mod
from core.doctor import (
    Level, apply_fixes, run_checks,
    _check_api, _check_config, _check_memory, _check_pending,
    _check_soul, _check_obsidian, _check_skills, _check_artifacts,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _minimal_cfg(tmp: str) -> dict:
    db = Path(tmp) / "archer.db"
    _init_db(db)
    return {
        "api":     {"api_key": "sk-testkey1234567890", "base_url": "https://api.test.com/v1", "model": "test-model"},
        "memory":  {"db_path": str(db)},
        "persona": {"soul_path": ""},
        "obsidian": {},
    }


def _init_db(db: Path):
    """建立最小测试数据库（全部 7 张表）。"""
    conn = sqlite3.connect(db)
    tables = [
        "CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, content TEXT, tags TEXT DEFAULT '', type TEXT DEFAULT 'insight', importance INTEGER DEFAULT 3, status TEXT DEFAULT 'active', source TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '', archived_at TEXT, scope TEXT DEFAULT 'user', confidence REAL DEFAULT 0.8, last_used_at TEXT, valid_until TEXT)",
        "CREATE TABLE IF NOT EXISTS pending_memories (id INTEGER PRIMARY KEY, content TEXT, type TEXT, importance INTEGER, tags TEXT, source TEXT, confidence REAL, created_at TEXT, status TEXT DEFAULT 'pending')",
        "CREATE TABLE IF NOT EXISTS themes (id INTEGER PRIMARY KEY, name TEXT, category TEXT, description TEXT, occurrence_count INTEGER DEFAULT 1, last_seen_at TEXT)",
        "CREATE TABLE IF NOT EXISTS memory_links (id INTEGER PRIMARY KEY, memory_id INTEGER, theme_id INTEGER, strength REAL)",
        "CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, name TEXT, description TEXT, status TEXT DEFAULT 'active', current_phase TEXT, goal TEXT, created_at TEXT, updated_at TEXT)",
        "CREATE TABLE IF NOT EXISTS project_events (id INTEGER PRIMARY KEY, project_id INTEGER, event_type TEXT, content TEXT, source_session_id TEXT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS soul_proposals (id INTEGER PRIMARY KEY, content TEXT, source TEXT, status TEXT DEFAULT 'pending', created_at TEXT)",
    ]
    for ddl in tables:
        conn.execute(ddl)
    conn.commit()
    conn.close()


def _mock_skill(name: str):
    mod = types.ModuleType(name)
    mod.SKILL = {"name": name}
    return mod


# ── config checks ─────────────────────────────────────────────────────────────

def test_config_ok():
    cfg = {"api": {"api_key": "sk-xxx", "base_url": "http://x", "model": "m"}, "memory": {"db_path": "/tmp/x.db"}}
    r = _check_config(cfg)
    assert r.level == Level.OK

def test_config_missing_key():
    cfg = {"api": {"base_url": "http://x", "model": "m"}, "memory": {"db_path": "/tmp/x.db"}}
    r = _check_config(cfg)
    assert r.level == Level.ERROR
    assert "api.api_key" in r.message


# ── api checks ────────────────────────────────────────────────────────────────

def test_api_ok():
    cfg = {"api": {"api_key": "sk-realkey1234567890", "base_url": "https://api.test/v1", "model": "gpt"}}
    r = _check_api(cfg)
    assert r.level == Level.OK

def test_api_placeholder_key():
    cfg = {"api": {"api_key": "your-api-key", "base_url": "https://api.test/v1", "model": "gpt"}}
    r = _check_api(cfg)
    assert r.level == Level.WARN


# ── memory / schema checks ────────────────────────────────────────────────────

def test_memory_ok():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _minimal_cfg(tmp)
        results = _check_memory(cfg)
        levels = {r.name: r.level for r in results}
        assert levels["schema"] == Level.OK

def test_memory_db_not_exist():
    cfg = {"api": {}, "memory": {"db_path": "/nonexistent/archer.db"}}
    results = _check_memory(cfg)
    assert results[0].level == Level.ERROR

def test_memory_missing_table():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "archer.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT, created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '')")
        conn.commit()
        conn.close()
        cfg = {"api": {}, "memory": {"db_path": str(db)}}
        results = _check_memory(cfg)
        schema_r = next(r for r in results if r.name == "schema")
        assert schema_r.level == Level.WARN
        assert "pending_memories" in schema_r.message


# ── pending checks ────────────────────────────────────────────────────────────

def test_pending_zero():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _minimal_cfg(tmp)
        r = _check_pending(cfg)
        assert r.level == Level.OK

def test_pending_many():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _minimal_cfg(tmp)
        db = Path(cfg["memory"]["db_path"])
        conn = sqlite3.connect(db)
        for i in range(12):
            conn.execute(
                "INSERT INTO pending_memories (content, type, importance, tags, source, confidence, created_at, status) VALUES (?, 'insight', 3, '', 'test', 0.7, '2026-01-01', 'pending')",
                (f"mem {i}",),
            )
        conn.commit()
        conn.close()
        r = _check_pending(cfg)
        assert r.level == Level.WARN
        assert "12" in r.message


# ── soul / obsidian checks ────────────────────────────────────────────────────

def test_soul_not_configured():
    cfg = {"persona": {}}
    r = _check_soul(cfg)
    assert r.level == Level.WARN

def test_soul_file_exists(tmp_path):
    soul = tmp_path / "SOUL.md"
    soul.write_text("soul content")
    cfg = {"persona": {"soul_path": str(soul)}}
    r = _check_soul(cfg)
    assert r.level == Level.OK

def test_soul_file_missing(tmp_path):
    cfg = {"persona": {"soul_path": str(tmp_path / "SOUL.md")}}
    r = _check_soul(cfg)
    assert r.level == Level.ERROR

def test_obsidian_not_configured():
    r = _check_obsidian({})
    assert r.level == Level.WARN

def test_obsidian_exists(tmp_path):
    r = _check_obsidian({"obsidian": {"vault_path": str(tmp_path)}})
    assert r.level == Level.OK

def test_obsidian_missing():
    r = _check_obsidian({"obsidian": {"vault_path": "/nonexistent/vault"}})
    assert r.level == Level.ERROR


# ── skills checks ────────────────────────────────────────────────────────────

def test_skills_ok():
    skills = {n: _mock_skill(n) for n in ["weather", "web_fetch", "shell"]}
    results = _check_skills(skills)
    skill_r = next(r for r in results if r.name == "skills")
    assert skill_r.level == Level.OK
    assert "3" in skill_r.message

def test_skills_empty():
    results = _check_skills({})
    skill_r = next(r for r in results if r.name == "skills")
    assert skill_r.level == Level.WARN

def test_skills_high_risk_info():
    skills = {n: _mock_skill(n) for n in ["shell", "installer", "weather"]}
    results = _check_skills(skills)
    risk_r = next((r for r in results if r.name == "risk"), None)
    assert risk_r is not None
    assert risk_r.level == Level.INFO
    assert "shell" in risk_r.message

def test_skills_no_high_risk():
    skills = {n: _mock_skill(n) for n in ["weather", "web_fetch"]}
    results = _check_skills(skills)
    risk_r = next((r for r in results if r.name == "risk"), None)
    assert risk_r is None


# ── artifacts checks ──────────────────────────────────────────────────────────

def test_artifacts_ok(tmp_path):
    orig = art_mod.ARTIFACTS_DIR
    try:
        art_mod.ARTIFACTS_DIR = tmp_path / ".artifacts"
        art_mod.ARTIFACTS_DIR.mkdir()
        r = _check_artifacts()
        assert r.level == Level.OK
    finally:
        art_mod.ARTIFACTS_DIR = orig

def test_artifacts_missing_with_fix(tmp_path):
    orig = art_mod.ARTIFACTS_DIR
    try:
        art_mod.ARTIFACTS_DIR = tmp_path / ".artifacts"
        r = _check_artifacts()
        assert r.level == Level.WARN
        assert r.fix_fn is not None
        msg = r.fix_fn()
        assert art_mod.ARTIFACTS_DIR.exists()
        assert "创建" in msg
    finally:
        art_mod.ARTIFACTS_DIR = orig


# ── run_checks integration ────────────────────────────────────────────────────

def test_run_checks_returns_list():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _minimal_cfg(tmp)
        skills = {n: _mock_skill(n) for n in ["weather", "web_fetch"]}
        results = run_checks(cfg, skills)
        assert len(results) >= 8
        names = {r.name for r in results}
        assert "config" in names
        assert "schema" in names
        assert "soul" in names
        assert "skills" in names


# ── apply_fixes ───────────────────────────────────────────────────────────────

def test_apply_fixes_creates_dir(tmp_path):
    orig = art_mod.ARTIFACTS_DIR
    try:
        art_mod.ARTIFACTS_DIR = tmp_path / ".artifacts"
        from core.doctor import CheckResult, Level

        def _fix() -> str:
            art_mod.ARTIFACTS_DIR.mkdir(parents=True)
            return "ok"

        results = [CheckResult(Level.WARN, "test", "missing dir", fix_fn=_fix)]
        applied = apply_fixes(results)
        assert len(applied) == 1
        assert "[fix]" in applied[0]
    finally:
        art_mod.ARTIFACTS_DIR = orig

def test_apply_fixes_skips_ok():
    from core.doctor import CheckResult, Level
    called = []
    results = [CheckResult(Level.OK, "test", "all good", fix_fn=lambda: called.append(1) or "x")]
    apply_fixes(results)
    assert called == []
