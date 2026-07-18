from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PR_WORKFLOW = ROOT / ".github/workflows/pr.yml"
NIGHTLY_WORKFLOW = ROOT / ".github/workflows/nightly.yml"
PYTEST_CONFIG = ROOT / "pytest.ini"


@pytest.mark.unit
def test_pr_ci_is_deterministic_and_never_runs_real_model_journeys():
    source = PR_WORKFLOW.read_text(encoding="utf-8")

    assert "journey_smoke.sh" not in source
    assert "ARCHER_API_KEY" not in source
    assert "DEEPSEEK_API_KEY" not in source
    assert "tests/test_ci_workflows.py" in source
    assert "tests/test_workflow_evals.py" in source
    # Part 10 守门测试必须在每次 PR 跑，防止架构回退
    assert "tests/test_architecture_boundaries.py" in source
    assert "tests/test_api_tool_helpers.py" in source
    assert "tests/test_job_trace_and_session_concurrency.py" in source


@pytest.mark.contract
def test_nightly_creates_api_token_and_waits_for_health_and_ready():
    source = NIGHTLY_WORKFLOW.read_text(encoding="utf-8")

    assert "ARCHER_NIGHTLY_API_KEY" in source
    assert "ARCHER_TOKEN_FILE" in source
    assert '"$ARCHER_TOKEN_FILE"' in source
    assert "python terminal/archer_api.py" in source
    assert "/health" in source
    assert "/ready" in source
    assert "bash scripts/journey_smoke.sh --all" in source
    assert ".venv/bin/python" not in source


@pytest.mark.unit
def test_pytest_declares_all_four_verification_layers():
    source = PYTEST_CONFIG.read_text(encoding="utf-8")

    for marker in ("unit", "contract", "integration", "journey"):
        assert f"{marker}:" in source
