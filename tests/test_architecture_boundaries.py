from __future__ import annotations

import ast
import subprocess
import types
from pathlib import Path

import pytest

from core.policy import Decision, check


ROOT = Path(__file__).resolve().parents[1]
GOD_FILE_LINE_BASELINE = {
    "terminal/api/_tools.py": 3368,
    "terminal/api/_routes.py": 3075,
    "memory/store.py": 1609,
    "client/desktop/src/renderer/src/pages/ChatPage.tsx": 2361,
    "client/desktop/src/renderer/src/adapters/localArcher.ts": 1132,
}


def _imports_under(package: str, imported_root: str) -> set[tuple[str, str]]:
    imports: set[tuple[str, str]] = set()
    for path in (ROOT / package).rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module == imported_root or module.startswith(f"{imported_root}."):
                    imports.add((str(path.relative_to(ROOT)), module))
    return imports


@pytest.mark.contract
def test_memory_core_imports_cannot_grow_beyond_documented_legacy_debt():
    imports = _imports_under("memory", "core")
    approved_infrastructure = {
        item for item in imports if item[1] == "core.paths"
    }
    legacy_debt = imports - approved_infrastructure

    assert legacy_debt == set()


@pytest.mark.contract
def test_workflows_never_import_terminal_api():
    assert _imports_under("workflows", "terminal") == set()


@pytest.mark.contract
def test_background_jobs_live_in_domain_module_behind_routes_facade():
    from terminal.api import _routes, job_routes

    job_symbols = {
        "BACKGROUND_JOBS",
        "BACKGROUND_JOB_LOCK",
        "_create_job",
        "_list_jobs",
        "_job_detail",
        "_run_job",
        "_start_job",
        "_cancel_job",
        "_retry_job",
        "_approve_job_tool",
        "_pause_job_for_approval",
        "_spawn_child_jobs",
        "_kick_queued_children",
        "_try_rollup_parent_result",
    }

    for name in job_symbols:
        assert getattr(_routes, name) is getattr(job_routes, name)

    routes_tree = ast.parse(
        (ROOT / "terminal/api/_routes.py").read_text(encoding="utf-8")
    )
    route_definitions = {
        node.name
        for node in routes_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert not job_symbols & route_definitions


@pytest.mark.contract
def test_memory_vault_and_sensors_live_behind_routes_facade():
    from terminal.api import _routes, memory_routes

    domain_symbols = {
        "_memory",
        "_resolve_pending_memory",
        "_batch_resolve_pending",
        "_hypotheses",
        "_create_hypothesis",
        "_import_obsidian_hypotheses",
        "_vault_reflection",
        "_list_recent_reflections",
        "_vault_refresh_index",
        "_vault_current_focus",
        "_vault_search_index",
        "_sensor_obsidian_focus",
        "_sensors_status",
    }

    for name in domain_symbols:
        assert getattr(_routes, name) is getattr(memory_routes, name)

    routes_tree = ast.parse(
        (ROOT / "terminal/api/_routes.py").read_text(encoding="utf-8")
    )
    route_definitions = {
        node.name
        for node in routes_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert not domain_symbols & route_definitions


@pytest.mark.contract
def test_profiles_settings_and_skills_live_behind_routes_facade():
    from terminal.api import _routes, profile_routes

    domain_symbols = {
        "_disabled_skills_path",
        "_load_disabled_skills",
        "_save_disabled_skills",
        "_toggle_skill",
        "_skills",
        "_available_modes",
        "_available_experts",
        "_switch_current_mode",
        "_switch_current_expert",
        "_soul_files",
        "_soul_profile_summary",
        "_period_review",
        "_journal_review",
        "_settings",
        "_validate_settings_draft",
        "_save_settings_draft",
        "_save_profile_settings",
        "_switch_active_profile",
        "_test_model_profile",
    }

    for name in domain_symbols:
        assert getattr(_routes, name) is getattr(profile_routes, name)

    routes_tree = ast.parse(
        (ROOT / "terminal/api/_routes.py").read_text(encoding="utf-8")
    )
    route_definitions = {
        node.name
        for node in routes_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert not domain_symbols & route_definitions


@pytest.mark.contract
def test_part8_shadow_routes_live_behind_routes_facade():
    from terminal.api import _routes, initiative_routes

    domain_symbols = {
        "_proactive_touch",
        "_initiative_shadow",
        "_initiative_shadow_failure",
        "_safe_initiative_shadow",
        "_initiative_shadow_report",
        "_initiative_shadow_long_term_report",
        "_initiative_shadow_delivery_gate",
        "_initiative_shadow_review_packet",
        "_initiative_shadow_feedback",
        "_initiative_presence",
        "_initiative_delivery_opt_in",
    }

    for name in domain_symbols:
        assert getattr(_routes, name) is getattr(initiative_routes, name)

    routes_tree = ast.parse(
        (ROOT / "terminal/api/_routes.py").read_text(encoding="utf-8")
    )
    route_definitions = {
        node.name
        for node in routes_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert not domain_symbols & route_definitions


@pytest.mark.contract
def test_api_tool_helpers_live_behind_tools_facade():
    from terminal.api import _tools, api_tool_helpers

    helper_symbols = {
        "_is_dangerous_shell",
        "_execute_shell_command",
        "_tool_event",
        "_obsidian_write_draft",
        "_make_api_tool_request",
        "_obsidian_work_intent",
        "_expert_scoped_skills",
        "_select_api_skills",
        "_filter_api_skills_for_intent",
        "_tool_event_from_request",
        "_tool_event_from_result",
        "_execute_api_tool_preview",
    }

    for name in helper_symbols:
        assert getattr(_tools, name) is getattr(api_tool_helpers, name)

    tools_tree = ast.parse(
        (ROOT / "terminal/api/_tools.py").read_text(encoding="utf-8")
    )
    tool_definitions = {
        node.name
        for node in tools_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert not helper_symbols & tool_definitions


@pytest.mark.contract
def test_hugo_workflow_helpers_live_behind_tools_facade():
    from terminal.api import _tools, hugo_workflow

    helper_symbols = {
        "_extract_md_path_from_query",
        "_extract_md_paths_from_text",
        "_read_md_source",
        "_collect_hugo_markdown_sources",
        "_extract_frontmatter_hints",
        "_format_hugo_chat_summary",
        "_hugo_workflow_event",
        "_run_hugo_publish_workflow",
        "_try_direct_hugo_deploy_existing",
        "_wants_hugo_delete",
        "_try_direct_hugo_delete",
        "_parse_markdown_for_hugo",
        "_hugo_confirmation_result",
        "_try_direct_hugo_publish",
        "_try_direct_hugo_redeploy_with_attachment",
        "_run_hugo_agent_turn",
    }

    for name in helper_symbols:
        assert getattr(_tools, name) is getattr(hugo_workflow, name)

    tools_tree = ast.parse(
        (ROOT / "terminal/api/_tools.py").read_text(encoding="utf-8")
    )
    tool_definitions = {
        node.name
        for node in tools_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert not helper_symbols & tool_definitions


@pytest.mark.contract
def test_desktop_tool_execution_helpers_live_behind_tools_facade():
    from terminal.api import _tools, desktop_tool_execution

    helper_symbols = {
        "_run_desktop_tool_loop",
        "_iter_obsidian_search_events",
        "_iter_obsidian_read_events",
        "_iter_obsidian_write_events",
        "_iter_shell_events",
        "_iter_github_events",
        "_iter_hugo_blog_events",
        "_generate_hugo_draft_from_reply",
        "_generate_obsidian_draft_with_ai",
        "_iter_api_tool_events",
        "_append_obsidian_draft",
        "_execute_github_operation",
    }

    for name in helper_symbols:
        assert getattr(_tools, name) is getattr(desktop_tool_execution, name)

    tools_tree = ast.parse(
        (ROOT / "terminal/api/_tools.py").read_text(encoding="utf-8")
    )
    tool_definitions = {
        node.name
        for node in tools_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert not helper_symbols & tool_definitions


def _skill(name: str, *, risk: str = "medium"):
    module = types.ModuleType(name)
    module.SKILL = {
        "name": name,
        "risk": risk,
        "requires_confirmation": False,
    }
    return module


@pytest.mark.contract
def test_side_effect_skills_require_approval_outside_read_only_domains():
    obsidian = check(
        "obsidian_write",
        {"path": "私人日记/今天.md", "content": "changed"},
        {"obsidian_write": _skill("obsidian_write")},
    )
    hugo = check(
        "hugo_blog",
        {"action": "deploy"},
        {"hugo_blog": _skill("hugo_blog")},
    )

    assert obsidian.decision == Decision.CONFIRM
    assert hugo.decision == Decision.CONFIRM

    hugo_read = check(
        "hugo_blog",
        {"action": "read", "filename": "existing.md"},
        {"hugo_blog": _skill("hugo_blog")},
    )
    assert hugo_read.decision == Decision.ALLOW


@pytest.mark.contract
def test_generated_and_runtime_artifacts_are_ignored_and_untracked():
    samples = [
        "archer.toml.bak.123",
        "memory/conversation_threads.json",
        "client/desktop/index-generated.js",
        "client/desktop/resources/icon.png.bak-123",
    ]
    ignored = subprocess.run(
        ["git", "check-ignore", *samples],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    tracked = set(
        subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.splitlines()
    )

    assert ignored.returncode == 0
    assert set(ignored.stdout.splitlines()) == set(samples)
    assert not set(samples) & tracked


@pytest.mark.contract
def test_god_files_cannot_grow_beyond_part10_gate0_baseline():
    actual = {
        path: len((ROOT / path).read_text(encoding="utf-8").splitlines())
        for path in GOD_FILE_LINE_BASELINE
    }

    assert {
        path: lines
        for path, lines in actual.items()
        if lines > GOD_FILE_LINE_BASELINE[path]
    } == {}


@pytest.mark.contract
def test_memory_extraction_stage_never_reads_global_store_db_path():
    source = (ROOT / "terminal/api/memory_extraction.py").read_text(encoding="utf-8")

    assert "memory.store.DB_PATH" not in source
    assert "from memory.store import DB_PATH" not in source


@pytest.mark.contract
def test_tools_facade_does_not_own_extracted_stage_executors():
    source = (ROOT / "terminal/api/_tools.py").read_text(encoding="utf-8")

    assert "def _do_extract_api(" not in source
    assert "def _bg_extract_api(" not in source
    assert "def _iter_model_stream_with_heartbeat(" not in source


@pytest.mark.contract
def test_tools_facade_does_not_redefine_chat_turn_stages():
    source = (ROOT / "terminal/api/_tools.py").read_text(encoding="utf-8")

    assert "def prepare_full_turn(" not in source
    assert "def iter_hugo_turn_events(" not in source
    assert "def iter_chat_reply_events(" not in source
    assert "def iter_post_reply_draft_events(" not in source
