import json
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).parent.parent


def run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_web_companion_persona_matches_core_soul_companion_direction():
    script = textwrap.dedent(
        """
        const companion = require('./web/public/assets/web-companion.js');
        console.log(JSON.stringify({
          identity: companion.WEB_SOUL_COMPANION_IDENTITY,
          rhythm: companion.WEB_CONVERSATION_RHYTHM_RULES,
          systemNote: companion.buildWebCompanionSystemNote(12),
          currentOpening: companion.buildWebThreadOpening('current'),
          soulOpening: companion.buildWebThreadOpening('soul')
        }));
        """
    )

    payload = run_node(script)

    assert "长期陪伴型 AI 灵魂伴生体" in payload["identity"]
    assert "不是万能工具" in payload["identity"]
    assert any("短句" in item and "先承接" in item for item in payload["rhythm"])
    assert "当前深度 12/50" in payload["systemNote"]
    assert "先承接" in payload["systemNote"]
    assert "最不舒服的那一处" in payload["currentOpening"]
    assert "更稳定地理解你" in payload["soulOpening"]
