import subprocess
from pathlib import Path


ROOT = Path(__file__).parent.parent


def test_private_boundary_check_passes_for_repo():
    result = subprocess.run(
        ["python3", "scripts/check_private_boundary.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
