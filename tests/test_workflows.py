"""
Workflows 层测试（v1.2.1）
不依赖 LLM 连接，验证模块结构、注册表和基础参数处理。
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── 1. 模块结构 ───────────────────────────────────────────────────────────────

def test_workflow_modules_have_required_attrs():
    """每个工作流模块都有 WORKFLOW dict 和 run() 函数。"""
    from workflows import voice_to_journal, url_to_reading_note, weekly_digest, project_briefing
    for mod in [voice_to_journal, url_to_reading_note, weekly_digest, project_briefing]:
        assert hasattr(mod, "WORKFLOW"), f"{mod.__name__} 缺少 WORKFLOW"
        assert hasattr(mod, "run"), f"{mod.__name__} 缺少 run()"
        wf = mod.WORKFLOW
        assert "name" in wf
        assert "description" in wf
        assert "usage" in wf


def test_workflow_names_are_unique():
    """工作流名称不重复。"""
    from workflows import voice_to_journal, url_to_reading_note, weekly_digest, project_briefing
    names = [m.WORKFLOW["name"] for m in [voice_to_journal, url_to_reading_note, weekly_digest, project_briefing]]
    assert len(names) == len(set(names)), f"重复的工作流名称：{names}"


# ── 2. Runner 注册表 ──────────────────────────────────────────────────────────

def test_runner_registry_loads():
    """registry() 能正常加载并返回所有工作流。"""
    from workflows.runner import registry
    reg = registry()
    assert isinstance(reg, dict)
    assert len(reg) == 4
    assert "voice" in reg
    assert "url" in reg
    assert "digest" in reg
    assert "briefing" in reg


def test_handle_workflow_unknown_name(capsys):
    """未知工作流名称输出提示，不崩溃。"""
    from workflows.runner import handle_workflow
    from rich.console import Console
    console = MagicMock()
    handle_workflow(["/workflow", "nonexistent"], console, {})
    console.print.assert_called()
    # 检查输出包含提示字样
    call_args = str(console.print.call_args_list)
    assert "未知工作流" in call_args or "nonexistent" in call_args


def test_handle_workflow_list(capsys):
    """/workflow（无子命令）输出工作流列表，不崩溃。"""
    from workflows.runner import handle_workflow
    console = MagicMock()
    handle_workflow(["/workflow"], console, {})
    console.print.assert_called()


# ── 3. 各工作流参数边界 ────────────────────────────────────────────────────────

def test_voice_no_args():
    """voice 缺少参数时输出用法提示，不崩溃。"""
    from workflows.voice_to_journal import run
    console = MagicMock()
    run([], console, {})
    console.print.assert_called()
    call_args = str(console.print.call_args_list)
    assert "用法" in call_args or "voice" in call_args


def test_voice_missing_file():
    """voice 指定不存在的文件时输出错误提示。"""
    from workflows.voice_to_journal import run
    console = MagicMock()
    run(["/tmp/nonexistent_audio_xyz.m4a"], console, {})
    console.print.assert_called()
    call_args = str(console.print.call_args_list)
    assert "不存在" in call_args or "red" in call_args


def test_url_no_args():
    """url 缺少参数时输出用法提示，不崩溃。"""
    from workflows.url_to_reading_note import run
    console = MagicMock()
    run([], console, {})
    console.print.assert_called()
    call_args = str(console.print.call_args_list)
    assert "用法" in call_args or "url" in call_args


def test_digest_invalid_days():
    """digest 传入非数字时默认使用 7 天，不崩溃（需 DB mock）。"""
    from workflows.weekly_digest import run
    console = MagicMock()

    with patch("memory.store.list_all", return_value=[]), \
         patch("memory.store.list_projects", return_value=[]):
        run(["not-a-number"], console, {
            "persona": {"memory_path": "/tmp/nonexistent/MEMORY.md"},
            "obsidian": {"vault_path": "/tmp"},
        })
    console.print.assert_called()


def test_digest_empty_db():
    """digest 在空 DB 情况下输出"没有记录"提示。"""
    from workflows.weekly_digest import run
    console = MagicMock()

    with patch("memory.store.list_all", return_value=[]), \
         patch("memory.store.list_projects", return_value=[]):
        run([], console, {
            "persona": {"memory_path": "/tmp/nonexistent/MEMORY.md"},
            "obsidian": {"vault_path": "/tmp"},
        })

    call_args = str(console.print.call_args_list)
    assert "没有记录" in call_args or "dim" in call_args


def test_briefing_no_active_project():
    """briefing 无活跃项目时输出提示，不崩溃。"""
    from workflows.project_briefing import run
    console = MagicMock()

    with patch("memory.store.list_projects", return_value=[]), \
         patch("memory.store.get_project_by_name", return_value=None):
        run([], console, {})

    call_args = str(console.print.call_args_list)
    assert "没有活跃项目" in call_args or "dim" in call_args


def test_briefing_project_not_found():
    """briefing 找不到指定项目时输出提示，不崩溃。"""
    from workflows.project_briefing import run
    console = MagicMock()

    with patch("memory.store.get_project_by_name", return_value=None):
        run(["不存在的项目"], console, {})

    call_args = str(console.print.call_args_list)
    assert "未找到" in call_args or "yellow" in call_args


# ── 2. Crystal 子命令测试 ──────────────────────────────────────────────────
def _make_wf(name="test_wf", keywords="kw", steps=None):
    """构造一个假的工作流 dict。"""
    return {
        "id": 1,
        "name": name,
        "keywords": keywords,
        "steps": steps or [{"skill": "browser_automation", "args": {"desc": "open google"}}],
        "use_count": 0,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


def test_crystal_save_duplicate_name(capsys):
    """重名时提示覆盖，确认后删除旧版本。"""
    from workflows.runner import _handle_crystal
    from unittest.mock import patch
    console = MagicMock()
    wf = _make_wf()
    # input 返回值序列：重名确认(y) → 步骤输入(一步) → 保存确认(y)
    with patch("memory.workflow_crystal.list_all", return_value=[wf]), \
         patch("memory.workflow_crystal.delete") as mock_del, \
         patch("memory.workflow_crystal.save", return_value=99) as mock_save, \
         patch("builtins.input", side_effect=["y", "step1", "", "y"]):
        _handle_crystal(["save", "test_wf", "new_kw"], console)
        mock_del.assert_called_once_with(1)
        mock_save.assert_called_once()


def test_crystal_save_duplicate_name_abort(capsys):
    """重名时用户拒绝覆盖，应取消保存。"""
    from workflows.runner import _handle_crystal
    from unittest.mock import patch
    console = MagicMock()
    wf = _make_wf()
    with patch("memory.workflow_crystal.list_all", return_value=[wf]), \
         patch("memory.workflow_crystal.save") as mock_save, \
         patch("builtins.input", return_value="n"):
        _handle_crystal(["save", "test_wf"], console)
        mock_save.assert_not_called()


def test_crystal_view_format(capsys):
    """view 子命令应使用 Panel 输出。"""
    from workflows.runner import _handle_crystal
    from rich.panel import Panel
    console = MagicMock()
    wf = _make_wf("my_wf", "kw1", [{"skill": "s1", "args": {"desc": "d1"}}])
    with patch("memory.workflow_crystal.get", return_value=wf):
        _handle_crystal(["view", "1"], console)
    panel_calls = [c for c in console.print.call_args_list if c and isinstance(c[0][0], Panel)]
    assert panel_calls, "view 应输出 Panel"


def test_crystal_view_not_found(capsys):
    """view 不存在的 ID 应提示。"""
    from workflows.runner import _handle_crystal
    console = MagicMock()
    with patch("memory.workflow_crystal.get", return_value=None):
        _handle_crystal(["view", "999"], console)
    call_args = str(console.print.call_args_list)
    assert "未找到" in call_args


def test_crystal_delete_confirm(capsys):
    """delete 需确认，拒绝时不删除。"""
    from workflows.runner import _handle_crystal
    console = MagicMock()
    wf = _make_wf()
    with patch("memory.workflow_crystal.get", return_value=wf), \
         patch("memory.workflow_crystal.delete") as mock_del, \
         patch("builtins.input", return_value="n"):
        _handle_crystal(["delete", "1"], console)
        mock_del.assert_not_called()


def test_crystal_delete_confirmed(capsys):
    """delete 确认后执行删除。"""
    from workflows.runner import _handle_crystal
    console = MagicMock()
    wf = _make_wf()
    with patch("memory.workflow_crystal.get", return_value=wf), \
         patch("memory.workflow_crystal.delete") as mock_del, \
         patch("builtins.input", return_value="y"):
        _handle_crystal(["delete", "1"], console)
        mock_del.assert_called_once_with(1)


def test_crystal_search(capsys):
    """search 子命令应调用 workflow_crystal.search。"""
    from workflows.runner import _handle_crystal
    console = MagicMock()
    wf = _make_wf("demo", "keyword")
    with patch("memory.workflow_crystal.search", return_value=[wf]) as mock_search:
        _handle_crystal(["search", "demo"], console)
        mock_search.assert_called_once_with("demo")


def test_crystal_search_no_result(capsys):
    """search 无结果时输出提示。"""
    from workflows.runner import _handle_crystal
    console = MagicMock()
    with patch("memory.workflow_crystal.search", return_value=[]):
        _handle_crystal(["search", "nonexistent"], console)
    call_args = str(console.print.call_args_list)
    assert "未找到" in call_args


def test_crystal_run_not_found(capsys):
    """run 不存在的 ID 应提示。"""
    from workflows.runner import _handle_crystal
    console = MagicMock()
    with patch("memory.workflow_crystal.get", return_value=None), \
         patch("memory.workflow_crystal.increment_use"):
        _handle_crystal(["run", "999"], console)
    call_args = str(console.print.call_args_list)
    assert "未找到" in call_args


def test_crystal_run_skip_missing_skill(capsys):
    """run 时技能不存在应跳过并提示。"""
    from workflows.runner import _handle_crystal
    console = MagicMock()
    wf = _make_wf("wf1", "", [{"skill": "no_such_skill", "args": {}}])
    with patch("memory.workflow_crystal.get", return_value=wf), \
         patch("memory.workflow_crystal.increment_use"), \
         patch("skills.loader.load_skills", return_value={}):
        _handle_crystal(["run", "1"], console)
    call_args = str(console.print.call_args_list)
    assert "不存在" in call_args or "跳过" in call_args


def test_crystal_run_executes_skill(capsys):
    """run 时技能存在应调用其 run()。"""
    from workflows.runner import _handle_crystal
    console = MagicMock()
    mock_skill = MagicMock()
    wf = _make_wf("wf1", "", [{"skill": "my_skill", "args": {"desc": "do something"}}])
    with patch("memory.workflow_crystal.get", return_value=wf), \
         patch("memory.workflow_crystal.increment_use"), \
         patch("skills.loader.load_skills", return_value={"my_skill": mock_skill}):
        _handle_crystal(["run", "1"], console)
    mock_skill.run.assert_called_once_with("do something", console)


def test_crystal_run_skill_exception(capsys):
    """run 时技能抛出异常应捕获并提示。"""
    from workflows.runner import _handle_crystal
    console = MagicMock()
    mock_skill = MagicMock()
    mock_skill.run.side_effect = RuntimeError("boom")
    wf = _make_wf("wf1", "", [{"skill": "bad_skill", "args": {}}])
    with patch("memory.workflow_crystal.get", return_value=wf), \
         patch("memory.workflow_crystal.increment_use"), \
         patch("skills.loader.load_skills", return_value={"bad_skill": mock_skill}):
        _handle_crystal(["run", "1"], console)
    call_args = str(console.print.call_args_list)
    assert "执行失败" in call_args or "boom" in call_args


def test_handle_workflow_crystal_sub_no_args(capsys):
    """"/workflow crystal" 无子命令时显示列表（list 是默认）。"""
    from workflows.runner import _handle_crystal
    console = MagicMock()
    with patch("memory.workflow_crystal.list_all", return_value=[]):
        _handle_crystal([], console)
    # 应调用 console.print（打印空列表提示或表格）
    console.print.assert_called()


# ── Runner ────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_workflow_modules_have_required_attrs,
        test_workflow_names_are_unique,
        test_runner_registry_loads,
        test_handle_workflow_unknown_name,
        test_handle_workflow_list,
        test_voice_no_args,
        test_voice_missing_file,
        test_url_no_args,
        test_digest_invalid_days,
        test_digest_empty_db,
        test_briefing_no_active_project,
        test_briefing_project_not_found,
        test_crystal_save_duplicate_name,
        test_crystal_save_duplicate_name_abort,
        test_crystal_view_format,
        test_crystal_view_not_found,
        test_crystal_delete_confirm,
        test_crystal_delete_confirmed,
        test_crystal_search,
        test_crystal_search_no_result,
        test_crystal_run_not_found,
        test_crystal_run_skip_missing_skill,
        test_crystal_run_executes_skill,
        test_crystal_run_skill_exception,
        test_handle_workflow_crystal_sub_no_args,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
