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


@pytest.mark.unit
def test_pr_ci_subset_files_are_not_marked_integration_at_file_level():
    """PR CI 用文件列表枚举，不依赖 marker 过滤。
    但如果某天有人给子集文件加了 `pytestmark = pytest.mark.integration`，
    会让本地 `pytest -m "not integration"` 误跳过 PR CI 必跑的测试。
    此处守门：PR CI 子集文件不能有文件级 integration marker。"""
    import re

    source = PR_WORKFLOW.read_text(encoding="utf-8")
    # 提取 pr.yml 中所有 tests/xxx.py 引用（去掉 ::ClassName 后缀）
    referenced = set()
    for match in re.finditer(r"tests/[A-Za-z0-9_/]+\.py", source):
        referenced.add(match.group(0).split("::")[0])

    assert referenced, "未从 pr.yml 解析出任何 tests/*.py 文件引用"

    violations = []
    for rel_path in sorted(referenced):
        test_file = ROOT / rel_path
        if not test_file.exists():
            violations.append(f"{rel_path}: 文件不存在")
            continue
        content = test_file.read_text(encoding="utf-8")
        # 文件级 marker 形式：`pytestmark = pytest.mark.integration`
        if re.search(r"^pytestmark\s*=\s*pytest\.mark\.integration", content, re.MULTILINE):
            violations.append(f"{rel_path}: 含文件级 pytestmark = pytest.mark.integration")

    assert not violations, (
        "PR CI 子集文件不应有文件级 integration marker，否则本地 "
        "`pytest -m 'not integration'` 会跳过 PR CI 必跑的测试：\n  - "
        + "\n  - ".join(violations)
    )
