from __future__ import annotations

import ast
import subprocess
import types
from pathlib import Path

import pytest

from core.policy import Decision, check

ROOT = Path(__file__).resolve().parents[1]
GOD_FILE_LINE_BASELINE = {
    # 2026-10-04: code scanning extracted; exact baselines, no growth buffer.
    "core/policy.py": 730,
    "core/policy_code_scan.py": 188,
    # Part 10 Wave 4 收尾后收紧（2026-07-17）+ P1 store 拆分（2026-07-18）：
    # 基线从拆分前高位降到当前实际行数 +10% buffer，让后续回归被更早发现。
    # store.py 从 1369 降到 786（拆出 store_quality / store_pending / store_themes /
    # store_projects / store_soul_proposals 五个 domain 模块）。
    "terminal/api/_tools.py": 781,        # 实际 781
    "terminal/api/_routes.py": 629,        # 实际 629
    "terminal/api/job_routes.py": 880,     # 实际 824
    "memory/store.py": 870,                # 实际 786（P1 拆分后）
    "client/desktop/src/renderer/src/pages/ChatPage.tsx": 2355,
    "client/desktop/src/renderer/src/adapters/localArcher.ts": 1129,
}


@pytest.mark.contract
def test_tool_executors_cannot_own_runtime_completion():
    executor_paths = (
        "core/tool_runtime.py",
        "core/api_tool_service.py",
        "skills/obsidian_write.py",
    )
    forbidden_authority = (
        "core.run_store",
        "core.step_store",
        "core.outcome_store",
        "transition_run(",
        "transition_step(",
        "RunState.COMPLETED",
        "StepState.COMPLETED",
    )

    for relative_path in executor_paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden_authority), relative_path


@pytest.mark.contract
def test_desktop_runtime_state_is_an_http_projection_not_a_fact_store():
    adapter = (
        ROOT
        / "client/desktop/src/renderer/src/adapters/runtimeRunsAdapter.ts"
    ).read_text(encoding="utf-8")
    store = (
        ROOT
        / "client/desktop/src/renderer/src/lib/runtimeRunStore.ts"
    ).read_text(encoding="utf-8")

    assert "/runtime/runs" in adapter
    assert "listRuntimeRuns" in store
    assert "requestRuntimeCancellation" in store
    forbidden_local_authority = (
        "localStorage",
        "runtime_runs",
        "runtime_events",
        "transitionRun",
        "RunState.COMPLETED",
        "sqlite",
    )
    assert not any(
        token in adapter or token in store for token in forbidden_local_authority
    )


@pytest.mark.contract
def test_task_plan_shadow_cannot_execute_or_migrate_legacy_job_authority():
    source = (ROOT / "core/task_plan_shadow.py").read_text(encoding="utf-8")
    forbidden_authority = (
        "tool_runtime",
        "background_job",
        "job_routes",
        "approval_store",
        "approval_routes",
        "EXECUTING",
        "transition_step(",
        "COMPLETED",
    )

    assert not any(token in source for token in forbidden_authority)


@pytest.mark.contract
def test_task_plan_observation_can_only_close_or_record_legacy_handoff():
    source = (ROOT / "core/task_plan_observation.py").read_text(encoding="utf-8")
    forbidden_authority = (
        "tool_runtime",
        "background_job",
        "job_routes",
        "approval_store",
        "approval_routes",
        "RunState.EXECUTING",
        "RunState.COMPLETED",
        "transition_step(",
    )

    assert "legacy_job_unmigrated" in source
    assert "runtime_execution_claimed=False" in source
    assert not any(token in source for token in forbidden_authority)


@pytest.mark.contract
def test_desktop_legacy_plan_status_only_reports_to_shadow_api():
    chat_page = (
        ROOT / "client/desktop/src/renderer/src/pages/ChatPage.tsx"
    ).read_text(encoding="utf-8")
    adapter = (
        ROOT
        / "client/desktop/src/renderer/src/adapters/runtimeRunsAdapter.ts"
    ).read_text(encoding="utf-8")

    assert "await recordPlanLifecycleStatus(plan, 'accepted')" in chat_page
    assert "await recordPlanLifecycleStatus(plan, 'dismissed')" in chat_page
    assert "/runtime/task-plan-shadows/" in adapter
    assert "Shadow observation must never block" in chat_page


@pytest.mark.contract
def test_task_plan_job_shadow_cannot_claim_runtime_execution():
    shadow = (ROOT / "core/task_plan_job_shadow.py").read_text(encoding="utf-8")

    assert "runtime_execution_claimed=False" in shadow
    assert "runtime_state_changed=False" in shadow
    assert "transition_run" not in shadow
    assert "transition_step" not in shadow
    assert "job_routes" not in shadow
    assert "tool_runtime" not in shadow


@pytest.mark.contract
def test_job_execution_adapter_is_pure_contract_not_an_executor():
    adapter = (
        ROOT / "core/job_execution_adapter.py"
    ).read_text(encoding="utf-8")

    assert "LEGACY_JOB_V0_CAPABILITIES" in adapter
    assert "RESULT_VERIFICATION" in adapter
    assert "OUTCOME_VERIFICATION" in adapter
    assert "transition_run" not in adapter
    assert "transition_step" not in adapter
    assert "job_routes" not in adapter
    assert "BACKGROUND_JOBS" not in adapter
    assert "threading" not in adapter


@pytest.mark.contract
def test_job_authority_cutover_is_a_decision_contract_not_an_executor():
    cutover = (
        ROOT / "core/job_authority_cutover.py"
    ).read_text(encoding="utf-8")
    observation = (
        ROOT / "core/job_cutover_observation.py"
    ).read_text(encoding="utf-8")
    evidence_window = (
        ROOT / "core/job_cutover_evidence_window.py"
    ).read_text(encoding="utf-8")
    command_authority = (
        ROOT / "core/job_command_authority.py"
    ).read_text(encoding="utf-8")
    forbidden_authority = (
        "terminal.api",
        "job_routes",
        "tool_runtime",
        "approval_routes",
        "transition_run(",
        "transition_step(",
        "_start_job(",
        "_create_job(",
        "BACKGROUND_JOBS",
        "threading",
    )

    assert "record_job_authority_cutover_decision" in cutover
    assert "authority_enabled=status is JobCutoverStatus.AUTHORITATIVE" in cutover
    assert "record_job_cutover_observation" in observation
    assert "review_job_cutover_evidence_window" in evidence_window
    assert "resolve_job_command_migration_mode" in command_authority
    assert "authority_enabled: bool = False" in evidence_window
    assert not any(
        token in cutover
        or token in observation
        or token in evidence_window
        or token in command_authority
        for token in forbidden_authority
    )


@pytest.mark.contract
def test_vault_reflection_worker_does_not_manufacture_approval_reachability():
    routes = (ROOT / "terminal/api/job_routes.py").read_text(encoding="utf-8")
    start = routes.index("def _execute_vault_reflection()")
    end = routes.index("# 按 kind 分派", start)
    worker = routes[start:end]

    assert "_pause_job_for_approval" not in worker
    assert "pendingTool" not in worker
    assert "approve_legacy_job_tool" not in worker


@pytest.mark.contract
def test_job_outcome_verifier_is_pure_and_non_authoritative():
    verifier = (
        ROOT / "core/job_outcome_verification.py"
    ).read_text(encoding="utf-8")

    assert "no_deterministic_verifier_for_kind" in verifier
    assert "transition_run" not in verifier
    assert "transition_step" not in verifier
    assert "terminal.api" not in verifier
    assert "memory.store" not in verifier
    assert "workflows." not in verifier
    assert "BACKGROUND_JOBS" not in verifier


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
    from terminal.api import (
        _routes,
        job_approval,
        job_cancellation,
        job_retry,
        job_routes,
        job_terminal_finalize,
    )

    job_symbols = {
        "BACKGROUND_JOBS",
        "BACKGROUND_JOB_LOCK",
        "_create_job",
        "_list_jobs",
        "_job_detail",
        "_run_job",
        "_start_job",
        "_pause_job_for_approval",
        "_spawn_child_jobs",
        "_kick_queued_children",
        "_try_rollup_parent_result",
    }

    for name in job_symbols:
        assert getattr(_routes, name) is getattr(job_routes, name)
    assert (
        _routes.retry_legacy_job_response
        is job_retry.retry_legacy_job_response
    )
    assert (
        _routes.request_legacy_job_cancellation_response
        is job_cancellation.request_legacy_job_cancellation_response
    )
    assert (
        _routes.approve_legacy_job_tool_response
        is job_approval.approve_legacy_job_tool_response
    )
    assert (
        job_routes._try_rollup_parent_result
        is job_terminal_finalize.try_rollup_legacy_parent_result
    )

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
def test_sessions_live_behind_routes_facade():
    from terminal.api import _routes, session_routes

    # _routes.py re-exports session_routes symbols under private aliases.
    # Map the _routes alias to the real name defined in session_routes.
    session_symbol_map = {
        "_add_thread_session": "add_thread_session",
        "_append_session": "append_session",
        "_create_thread": "create_thread",
        "_delete_session": "delete_session",
        "_session_detail": "session_detail",
        "_session_meta_from_payload": "session_meta_from_payload",
        "_sessions": "sessions",
        "_sessions_search": "sessions_search",
        "_save_session": "save_session",
        "_thread_detail": "thread_detail",
        "_threads": "threads",
        "_update_thread": "update_thread",
    }

    for alias, real_name in session_symbol_map.items():
        assert getattr(_routes, alias) is getattr(session_routes, real_name)

    routes_tree = ast.parse(
        (ROOT / "terminal/api/_routes.py").read_text(encoding="utf-8")
    )
    route_definitions = {
        node.name
        for node in routes_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert not set(session_symbol_map.keys()) & route_definitions


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


@pytest.mark.contract
def test_python_tool_runtime_does_not_delegate_to_ts_bridge():
    runtime_tree = ast.parse(
        (ROOT / "core/tool_runtime.py").read_text(encoding="utf-8")
    )
    imported_names = {
        alias.name
        for node in ast.walk(runtime_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "core.ts_skill_bridge"
        for alias in node.names
    }
    called_names = {
        node.func.id
        for node in ast.walk(runtime_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "try_execute_ts_skill" not in imported_names
    assert "try_execute_ts_skill" not in called_names


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


@pytest.mark.contract
def test_policy_code_scanning_and_tool_stage_do_not_own_persistent_state() -> None:
    # These helpers must use arguments/callbacks; persistence belongs to callers.
    for relative_path in ("core/policy_code_scan.py", "terminal/api/tool_stage.py"):
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, relative_path
                modules.append(node.module or "")
        assert not any(
            module.split(".")[0] in {"core", "memory", "infrastructure", "terminal", "sqlite3"}
            for module in modules
        ), relative_path
