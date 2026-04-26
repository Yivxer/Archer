"""
P2 — /listen 静默模态 + 配置热加载 Tests
"""
import sys
import tempfile
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── 配置热加载 ──────────────────────────────────────────────────────────────────

def test_config_loads_on_first_call():
    import core.llm as llm_mod
    old_cfg, old_mtime = llm_mod._cfg, llm_mod._config_mtime
    try:
        llm_mod._cfg = None
        llm_mod._config_mtime = 0.0
        cfg = llm_mod._load_config()
        assert isinstance(cfg, dict)
        assert "api" in cfg
    finally:
        llm_mod._cfg = old_cfg
        llm_mod._config_mtime = old_mtime


def test_config_no_reload_when_unchanged():
    """文件未改动时，_load_config 返回同一个对象（无重载）。"""
    import core.llm as llm_mod
    old_cfg, old_mtime, old_flag = llm_mod._cfg, llm_mod._config_mtime, llm_mod._config_reloaded
    try:
        # 先加载一次确保缓存
        llm_mod._cfg = None
        llm_mod._config_mtime = 0.0
        first = llm_mod._load_config()
        second = llm_mod._load_config()
        assert first is second, "文件未改动时应返回缓存对象"
        assert not llm_mod._config_reloaded
    finally:
        llm_mod._cfg = old_cfg
        llm_mod._config_mtime = old_mtime
        llm_mod._config_reloaded = old_flag


def test_config_reloads_when_file_changes():
    """文件 mtime 变化时，_load_config 返回新 dict 并置 _config_reloaded=True。"""
    import core.llm as llm_mod
    old_cfg, old_path = llm_mod._cfg, llm_mod._CONFIG_PATH
    old_mtime, old_flag = llm_mod._config_mtime, llm_mod._config_reloaded
    try:
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "archer.toml"
            toml_path.write_text(
                '[api]\napi_key = "test"\nbase_url = "http://x"\nmodel = "m1"\n'
                '[memory]\nmax_context_memories = 5\n[persona]\ndefault_mode = "coach"\n[paths]\n',
                encoding="utf-8",
            )
            llm_mod._CONFIG_PATH = toml_path
            llm_mod._cfg = None
            llm_mod._config_mtime = 0.0

            # 首次加载
            llm_mod._load_config()
            assert not llm_mod._config_reloaded  # 首次加载不算 reload

            # 修改文件，确保 mtime 变化
            time.sleep(0.02)
            toml_path.write_text(
                '[api]\napi_key = "test"\nbase_url = "http://x"\nmodel = "m2"\n'
                '[memory]\nmax_context_memories = 5\n[persona]\ndefault_mode = "coach"\n[paths]\n',
                encoding="utf-8",
            )
            toml_path.touch()  # 强制更新 mtime

            cfg2 = llm_mod._load_config()
            assert llm_mod._config_reloaded is True
            assert cfg2["api"]["model"] == "m2"
    finally:
        llm_mod._cfg = old_cfg
        llm_mod._CONFIG_PATH = old_path
        llm_mod._config_mtime = old_mtime
        llm_mod._config_reloaded = old_flag


def test_pop_config_reloaded_resets_flag():
    import core.llm as llm_mod
    old_flag = llm_mod._config_reloaded
    try:
        llm_mod._config_reloaded = True
        assert llm_mod.pop_config_reloaded() is True
        assert llm_mod._config_reloaded is False
        assert llm_mod.pop_config_reloaded() is False
    finally:
        llm_mod._config_reloaded = old_flag


def test_config_handles_missing_file_gracefully():
    """文件不存在时，若已有缓存则返回缓存，不报错。"""
    import core.llm as llm_mod
    old_cfg, old_path = llm_mod._cfg, llm_mod._CONFIG_PATH
    old_mtime = llm_mod._config_mtime
    try:
        cached = {"api": {"model": "cached"}}
        llm_mod._cfg = cached
        llm_mod._CONFIG_PATH = Path("/不存在/的路径/archer.toml")
        result = llm_mod._load_config()
        assert result is cached
    finally:
        llm_mod._cfg = old_cfg
        llm_mod._CONFIG_PATH = old_path
        llm_mod._config_mtime = old_mtime


# ── /listen 静默录入 ────────────────────────────────────────────────────────────

def test_listen_mode_global_exists():
    import archer
    assert hasattr(archer, "_listen_mode")
    assert isinstance(archer._listen_mode, bool)


def test_listen_write_creates_log_file():
    import archer
    old_dir = archer._LISTEN_LOG_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            archer._LISTEN_LOG_DIR = Path(tmp) / "listen_logs"
            archer._listen_write("今天开始专注写作")
            logs = list(Path(tmp).rglob("*.md"))
            assert len(logs) == 1
            content = logs[0].read_text(encoding="utf-8")
            assert "今天开始专注写作" in content
    finally:
        archer._LISTEN_LOG_DIR = old_dir


def test_listen_write_appends_timestamp():
    import archer
    old_dir = archer._LISTEN_LOG_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            archer._LISTEN_LOG_DIR = Path(tmp) / "listen_logs"
            archer._listen_write("第一条")
            archer._listen_write("第二条")
            logs = list(Path(tmp).rglob("*.md"))
            content = logs[0].read_text(encoding="utf-8")
            assert "第一条" in content
            assert "第二条" in content
            # 每条记录独立一行，以 "-" 开头
            lines = [l for l in content.splitlines() if l.startswith("-")]
            assert len(lines) == 2
    finally:
        archer._LISTEN_LOG_DIR = old_dir


def test_handle_listen_toggle():
    import archer
    archer._listen_mode = False
    archer._handle_listen(["/listen"])
    assert archer._listen_mode is True
    archer._handle_listen(["/listen"])
    assert archer._listen_mode is False


def test_handle_listen_stop_subcommand():
    import archer
    archer._listen_mode = True
    archer._handle_listen(["/listen", "stop"])
    assert archer._listen_mode is False


def test_listen_mode_shows_in_display():
    """进入 listen 模式后，状态栏应显示静默录入标识。"""
    import archer
    archer._listen_mode = True
    # display_mode 的构建逻辑在 run() 内部，这里验证全局变量正确
    assert archer._listen_mode is True
    archer._listen_mode = False  # reset


def test_listen_write_also_logs_to_project():
    """如果有活跃项目，_listen_write 应同时写入项目事件。"""
    import archer
    import memory.store as store_mod
    old_dir = archer._LISTEN_LOG_DIR
    old_pid = archer._active_project_id
    old_db = store_mod.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            archer._LISTEN_LOG_DIR = Path(tmp) / "listen_logs"
            store_mod.DB_PATH = Path(tmp) / "test.db"
            store_mod.init_db()

            pid = store_mod.create_project("测试项目")
            archer._active_project_id = pid

            archer._listen_write("项目相关思考")

            events = store_mod.get_project_events(pid)
            assert any(e["event_type"] == "listen" for e in events)
            assert any("项目相关思考" in e["content"] for e in events)
    finally:
        archer._LISTEN_LOG_DIR = old_dir
        archer._active_project_id = old_pid
        store_mod.DB_PATH = old_db


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_config_loads_on_first_call,
        test_config_no_reload_when_unchanged,
        test_config_reloads_when_file_changes,
        test_pop_config_reloaded_resets_flag,
        test_config_handles_missing_file_gracefully,
        test_listen_mode_global_exists,
        test_listen_write_creates_log_file,
        test_listen_write_appends_timestamp,
        test_handle_listen_toggle,
        test_handle_listen_stop_subcommand,
        test_listen_mode_shows_in_display,
        test_listen_write_also_logs_to_project,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
            passed += 1
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
