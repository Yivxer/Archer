import json
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).parent.parent


def test_generate_tokens_outputs_json_and_typescript(tmp_path):
    source = tmp_path / "tokens.css"
    json_out = tmp_path / "tokens.json"
    ts_out = tmp_path / "tokens.ts"
    source.write_text(
        textwrap.dedent(
            """
            :root {
              --cyan: #4dd9d4;
              --bg-1: #f8f5ef;
              --brand-font: "Comfortaa", sans-serif;
            }

            :root[data-theme="dark"] {
              --bg-1: #0d1219;
            }
            """
        ).strip(),
        encoding="utf-8",
    )

    subprocess.run(
        [
            "python3",
            "scripts/generate_tokens.py",
            "--source",
            str(source),
            "--json",
            str(json_out),
            "--ts",
            str(ts_out),
        ],
        cwd=ROOT,
        check=True,
    )

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["themes"]["light"]["cyan"] == "#4dd9d4"
    assert payload["themes"]["light"]["bg-1"] == "#f8f5ef"
    assert payload["themes"]["dark"]["bg-1"] == "#0d1219"
    assert payload["themes"]["dark"]["cyan"] == "#4dd9d4"
    assert "export const designTokens" in ts_out.read_text(encoding="utf-8")


def test_generated_repo_tokens_are_in_sync():
    result = subprocess.run(
        ["python3", "scripts/generate_tokens.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
