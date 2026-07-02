"""
test_vault_sensor.py — Vault Bridge Phase 1 测试

覆盖：
- init_vault_index_table 建表幂等
- refresh_index 全量扫描 + 计数
- refresh_index cooldown 命中跳过
- refresh_index force=True 绕过 cooldown
- 未配置 vault 降级返回 ok=False
- detect_current_focus 窗口内命中
- detect_current_focus 窗口外返回 focused=False
- get_current_focus 读取缓存
- search_indexed_notes 关键词过滤 + limit
- search_indexed_notes 空关键词返回最近笔记
"""
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _setup_db(tmp_path: Path):
    """重定向 memory.store.DB_PATH 到临时路径。"""
    import memory.store as store_mod
    store_mod.DB_PATH = tmp_path / "test.db"
    store_mod.init_db()
    return store_mod


def _make_vault(tmp_path: Path) -> Path:
    """创建临时 vault 目录，写两篇笔记。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Archer.md").write_text("# Archer\n\n主大脑笔记", encoding="utf-8")
    (vault / "Obsidian.md").write_text(
        "---\ntitle: Obsidian 笔记\ntags: [工具, 写作]\n---\n\n# Obsidian\n\n编辑器笔记",
        encoding="utf-8",
    )
    return vault


def _patch_vault(monkeypatch, vault: Path):
    """让 skills._vault 指向临时 vault。"""
    import skills._vault as vmod
    monkeypatch.setattr(vmod, "read_vault_path", lambda: vault)
    monkeypatch.setattr(vmod, "resolve_vault", lambda: vault)


# ── init_vault_index_table ───────────────────────────────────────────────

def test_init_table_creates_tables(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    from knowledge import vault_sensor
    vault_sensor.init_vault_index_table()

    import sqlite3
    import memory.store as store_mod
    conn = sqlite3.connect(store_mod.DB_PATH)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "vault_notes" in tables
    assert "vault_focus" in tables


def test_init_table_idempotent(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    from knowledge import vault_sensor
    vault_sensor.init_vault_index_table()
    vault_sensor.init_vault_index_table()  # 再调一次不应抛


# ── refresh_index ────────────────────────────────────────────────────────

def test_refresh_index_scans_all_notes(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    result = vault_sensor.refresh_index(force=True)
    assert result["ok"] is True
    assert result["indexed"] == 2
    assert result["vault"] == str(vault)


def test_refresh_index_unconfigured_vault(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    import skills._vault as vmod
    monkeypatch.setattr(vmod, "resolve_vault", lambda: None)

    from knowledge import vault_sensor
    result = vault_sensor.refresh_index(force=True)
    assert result["ok"] is False
    assert "未配置" in result["reason"]


def test_refresh_index_cooldown_skips(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    # 第一次强制全量
    r1 = vault_sensor.refresh_index(force=True)
    assert r1["indexed"] == 2
    # 第二次不强制，应该命中 cooldown
    r2 = vault_sensor.refresh_index(force=False)
    assert r2["ok"] is True
    assert r2.get("skipped") is True


def test_refresh_index_force_overrides_cooldown(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.refresh_index(force=True)
    r = vault_sensor.refresh_index(force=True)
    assert r["ok"] is True
    assert "indexed" in r
    assert "skipped" not in r


def test_refresh_index_first_scan_bypasses_cooldown(tmp_path, monkeypatch):
    """索引表为空时首次扫描应绕过 cooldown，直接全量索引。"""
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    # 不先 force 扫描，直接调 refresh_index(force=False)
    # 索引表为空，应绕过 cooldown 直接全量扫描
    r = vault_sensor.refresh_index(force=False)
    assert r["ok"] is True
    assert r.get("indexed") == 2
    assert "skipped" not in r


# ── detect_current_focus ─────────────────────────────────────────────────

def test_detect_focus_within_window(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.refresh_index(force=True)

    # 把索引中第一篇笔记的 mtime 改到「现在」
    import sqlite3
    import memory.store as store_mod
    now_str = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(store_mod.DB_PATH)
    conn.execute("UPDATE vault_notes SET mtime=? WHERE path LIKE '%Archer%'", (now_str,))
    conn.commit()
    conn.close()

    result = vault_sensor.detect_current_focus()
    assert result["focused"] is True
    assert "Archer" in result["note_path"]
    assert result["detection_method"] == "mtime"


def test_detect_focus_outside_window(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.refresh_index(force=True)

    # 把所有 mtime 推到很久以前
    import sqlite3
    import memory.store as store_mod
    old = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
    conn = sqlite3.connect(store_mod.DB_PATH)
    conn.execute("UPDATE vault_notes SET mtime=?", (old,))
    conn.commit()
    conn.close()

    result = vault_sensor.detect_current_focus()
    assert result["focused"] is False
    assert result["note_path"] is None


def test_detect_focus_skips_empty_note(tmp_path, monkeypatch):
    """size=0 的空笔记不应被误判为 focus（刚创建的空文件）。"""
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.refresh_index(force=True)

    import sqlite3
    import memory.store as store_mod
    now_str = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(store_mod.DB_PATH)
    # 把所有笔记改成"刚修改"但 size=0
    conn.execute("UPDATE vault_notes SET mtime=?, size=0", (now_str,))
    conn.commit()
    conn.close()

    result = vault_sensor.detect_current_focus()
    assert result["focused"] is False
    assert result["note_path"] is None


def test_detect_focus_skips_future_mtime(tmp_path, monkeypatch):
    """mtime 在未来（iCloud 同步漂移）的笔记不应被误判为 focus。"""
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.refresh_index(force=True)

    import sqlite3
    import memory.store as store_mod
    # 把所有笔记 mtime 推到 1 小时后（模拟 iCloud 同步漂移）
    future = (datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds")
    conn = sqlite3.connect(store_mod.DB_PATH)
    conn.execute("UPDATE vault_notes SET mtime=?, size=100", (future,))
    conn.commit()
    conn.close()

    result = vault_sensor.detect_current_focus()
    assert result["focused"] is False
    assert result["note_path"] is None


# ── get_current_focus ────────────────────────────────────────────────────

def test_get_current_focus_reads_cache(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.refresh_index(force=True)

    import sqlite3
    import memory.store as store_mod
    now_str = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(store_mod.DB_PATH)
    conn.execute("UPDATE vault_notes SET mtime=? WHERE path LIKE '%Archer%'", (now_str,))
    conn.commit()
    conn.close()

    vault_sensor.detect_current_focus()
    cached = vault_sensor.get_current_focus()
    assert cached["focused"] is True
    assert "Archer" in cached["note_path"]


def test_get_current_focus_empty_when_no_detection(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.refresh_index(force=True)

    # 没调过 detect，focus 表应该是空 / NULL
    result = vault_sensor.get_current_focus()
    assert result["focused"] is False
    assert result["note_path"] is None


def test_ingest_focus_event_records_explicit_sensor_focus(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    result = vault_sensor.ingest_focus_event({
        "file_path": "Obsidian.md",
        "title": "当前打开的笔记",
        "selected_text": "用户选中的关键段落",
        "visible_headings": ["一、问题", "二、方案"],
        "tags": ["Archer", "Obsidian"],
    })

    assert result["ok"] is True
    focus = vault_sensor.get_current_focus()
    assert focus["focused"] is True
    assert focus["note_path"] == "Obsidian.md"
    assert focus["note_title"] == "当前打开的笔记"
    assert focus["selected_text"] == "用户选中的关键段落"
    assert focus["visible_headings"] == ["一、问题", "二、方案"]
    assert focus["tags"] == ["Archer", "Obsidian"]
    assert focus["detection_method"] == "sensor"


def test_build_focus_context_uses_sensor_excerpt(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.ingest_focus_event({
        "file_path": "Archer.md",
        "title": "Archer 当前稿",
        "content_preview": "这篇文章正在讨论 Archer 和 Obsidian 的连接方式。",
    })

    context, source = vault_sensor.build_focus_context()
    assert "Archer 当前稿" in context
    assert "这篇文章正在讨论 Archer" in context
    assert source is not None
    assert source["path"] == "Archer.md"
    assert source["detection_method"] == "sensor"


def test_sensor_focus_api_routes(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from terminal.api import _routes as routes

    status, payload = routes.payload_post("/sensors/obsidian/focus", {
        "file_path": "Obsidian.md",
        "title": "API 当前笔记",
        "content_preview": "来自 Obsidian 插件的当前片段",
    })
    assert status == 200
    assert payload["ok"] is True

    status, payload = routes.payload_get("/sensors/status")
    assert status == 200
    assert payload["ok"] is True
    assert payload["obsidian"]["focused"] is True
    assert payload["obsidian"]["note_title"] == "API 当前笔记"


# ── search_indexed_notes ─────────────────────────────────────────────────

def test_search_by_keyword(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.refresh_index(force=True)

    results = vault_sensor.search_indexed_notes("Archer")
    assert len(results) == 1
    assert "Archer" in results[0]["path"]
    assert results[0]["title"] == "Archer"


def test_search_returns_tags_parsed(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.refresh_index(force=True)

    results = vault_sensor.search_indexed_notes("Obsidian")
    assert len(results) == 1
    assert results[0]["title"] == "Obsidian 笔记"
    assert results[0]["tags"] == ["工具", "写作"]


def test_search_empty_keyword_returns_recent(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.refresh_index(force=True)

    results = vault_sensor.search_indexed_notes("")
    assert len(results) == 2


def test_search_limit_clamped(tmp_path, monkeypatch):
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    vault_sensor.refresh_index(force=True)

    # 负数被夹到 1
    results = vault_sensor.search_indexed_notes("", limit=-5)
    assert len(results) == 1
    # 超大被夹到 100
    results = vault_sensor.search_indexed_notes("", limit=99999)
    assert len(results) == 2


# ── Phase 3: build_focus_context 自动 detect ──────────────────────────────────

def test_build_focus_context_auto_detects_when_no_cache(tmp_path, monkeypatch):
    """无缓存 focus 时，build_focus_context 应主动调 detect_current_focus。"""
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor

    # 先 refresh_index 让索引里有笔记
    vault_sensor.refresh_index(force=True)

    # 不调 ingest_focus_event，缓存为空，直接调 build_focus_context
    # 应该自动 detect：Archer.md 和 Obsidian.md 的 mtime 都在窗口内，
    # 取最近修改的（实际是相同时间，取 mtime DESC 的第一个）
    context, source = vault_sensor.build_focus_context()

    assert source is not None
    assert source["detection_method"] == "mtime"
    assert source["path"] in ("Archer.md", "Obsidian.md")
    assert "Obsidian 当前聚焦笔记" in context or "最近修改的 Obsidian 笔记" in context


def test_build_focus_context_refreshes_when_focus_expired(tmp_path, monkeypatch):
    """缓存 focus 过期（detected_at 早于 FOCUS_WINDOW）时应主动刷新。"""
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    import sqlite3
    import memory.store as store_mod

    # 先 ingest 一个 sensor focus（写入缓存）
    vault_sensor.ingest_focus_event({
        "file_path": "Archer.md",
        "title": "Archer 旧标题",
        "content_preview": "旧内容",
    })

    # 把 detected_at 改成 1 小时前（过期）
    old_time = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    conn = sqlite3.connect(store_mod.DB_PATH)
    conn.execute("UPDATE vault_focus SET detected_at=? WHERE id=1", (old_time,))
    conn.commit()
    conn.close()

    # refresh_index 让索引里有最近修改的笔记
    vault_sensor.refresh_index(force=True)

    # build_focus_context 应发现过期，主动 detect_current_focus 刷新
    context, source = vault_sensor.build_focus_context()

    assert source is not None
    # 刷新后 detection_method 应变成 mtime（detect_current_focus 的标记）
    assert source["detection_method"] == "mtime"


def test_build_focus_context_keeps_fresh_sensor_focus(tmp_path, monkeypatch):
    """缓存 focus 新鲜（detected_at 在窗口内）时不应主动 detect，直接用 sensor 数据。"""
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor

    # ingest 新鲜的 sensor focus
    vault_sensor.ingest_focus_event({
        "file_path": "Archer.md",
        "title": "Archer 当前稿",
        "content_preview": "正在编辑的内容",
    })

    # build_focus_context 不应触发 detect，应直接用 sensor 缓存
    context, source = vault_sensor.build_focus_context()

    assert source is not None
    assert source["detection_method"] == "sensor"
    assert source["path"] == "Archer.md"
    assert "Archer 当前稿" in context
    assert "正在编辑的内容" in context


def test_build_focus_context_skips_when_no_vault(tmp_path, monkeypatch):
    """vault 未配置时，build_focus_context 应降级返回空。"""
    _setup_db(tmp_path)

    from knowledge import vault_sensor
    import skills._vault as vmod
    monkeypatch.setattr(vmod, "read_vault_path", lambda: None)
    monkeypatch.setattr(vmod, "resolve_vault", lambda: None)

    # 即使 detect_current_focus 也会因为 vault None 而返回 focused=False
    context, source = vault_sensor.build_focus_context()
    assert context == ""
    assert source is None


def test_detect_focus_preserves_sensor_cache_when_no_mtime_candidate(tmp_path, monkeypatch):
    """detect_current_focus 没找到 mtime 候选时，若 sensor 缓存仍在 2x 窗口内应保留。"""
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    import sqlite3
    import memory.store as store_mod

    # 先 ingest 一个 sensor focus
    vault_sensor.ingest_focus_event({
        "file_path": "Archer.md",
        "title": "Archer 当前稿",
        "content_preview": "正在看这篇",
    })

    # 把所有 vault_notes 的 mtime 推到很久以前（mtime fallback 找不到候选）
    conn = sqlite3.connect(store_mod.DB_PATH)
    old = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
    conn.execute("UPDATE vault_notes SET mtime=?", (old,))
    # 但 sensor 缓存的 detected_at 仍在 2x 窗口内（10 分钟内）
    recent = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds")
    conn.execute("UPDATE vault_focus SET detected_at=?", (recent,))
    conn.commit()
    conn.close()

    result = vault_sensor.detect_current_focus()
    # 应保留 sensor 缓存
    assert result["focused"] is True
    assert result["note_path"] == "Archer.md"
    assert result["detection_method"] == "sensor"


def test_detect_focus_clears_sensor_cache_after_2x_window(tmp_path, monkeypatch):
    """sensor 缓存超过 2x 窗口且无 mtime 候选时，应清空。"""
    _setup_db(tmp_path)
    vault = _make_vault(tmp_path)
    _patch_vault(monkeypatch, vault)

    from knowledge import vault_sensor
    import sqlite3
    import memory.store as store_mod

    vault_sensor.ingest_focus_event({
        "file_path": "Archer.md",
        "title": "Archer 旧稿",
        "content_preview": "过期内容",
    })

    # 所有 mtime 推到很久以前
    conn = sqlite3.connect(store_mod.DB_PATH)
    old = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
    conn.execute("UPDATE vault_notes SET mtime=?", (old,))
    # sensor 缓存也超过 2x 窗口（30 分钟前 > 20 分钟 2x 窗口）
    stale = (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")
    conn.execute("UPDATE vault_focus SET detected_at=?", (stale,))
    conn.commit()
    conn.close()

    result = vault_sensor.detect_current_focus()
    assert result["focused"] is False
    assert result["note_path"] is None
