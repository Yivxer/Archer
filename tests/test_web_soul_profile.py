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


def test_web_soul_export_contains_structured_profile():
    script = textwrap.dedent(
        """
        const { buildSoulExport } = require('./web/public/assets/soul-profile.js');
        const payload = buildSoulExport({
          soulAnswers: {
            1: '枫弋',
            2: '我在想如何把 Archer 做成灵魂伴生体',
            3: '少打扰我，但在阶段变化时提醒我'
          },
          initialComplete: true,
          initialAnswers: [
            { q: '什么会让你觉得踏实？', a: '自己能做的事情尽量自己做好' },
            { q: '有什么事你还放在心上？', a: '害怕旧记忆突然丢失' },
            { q: '你想放下什么？', a: '把一切都靠意志硬撑的惯性' },
            { q: '什么时候最像自己？', a: '把复杂体验写成清楚的文字' }
          ],
          deepAnswers: [
            { id: 'd1', theme: 'emotion', q: '焦虑时会怎样？', a: '我会用规划填充不确定' },
            { id: 'd1', theme: 'emotion', q: '重复答案', a: '这条应该去重' },
            { id: 'd2', theme: 'project', q: 'Archer 像什么？', a: '终端是内核，客户端是壳' }
          ]
        }, '2026-05-25T00:00:00.000Z');
        console.log(JSON.stringify(payload));
        """
    )

    payload = run_node(script)

    assert payload["version"] == 2
    assert payload["exportedAt"] == "2026-05-25T00:00:00.000Z"
    assert payload["depth"] == 12
    assert len(payload["deepAnswers"]) == 2
    assert payload["soulProfile"]["current_life_stage"] == ["我在想如何把 Archer 做成灵魂伴生体"]
    assert "自己能做的事情尽量自己做好" in payload["soulProfile"]["core_values"]
    assert "害怕旧记忆突然丢失" in payload["soulProfile"]["recurring_fears"]
    assert "把复杂体验写成清楚的文字" in payload["soulProfile"]["creative_identity"]
    assert "我会用规划填充不确定" in payload["soulProfile"]["emotional_patterns"]
    assert "终端是内核，客户端是壳" in payload["soulProfile"]["project_mythology"]


def test_web_soul_profile_omits_empty_values_and_caps_fields():
    script = textwrap.dedent(
        """
        const { buildSoulProfileFromState } = require('./web/public/assets/soul-profile.js');
        const initialAnswers = Array.from({ length: 12 }, (_, index) => ({
          q: `价值题 ${index}`,
          a: `价值回答 ${index}`
        }));
        const profile = buildSoulProfileFromState({
          soulAnswers: { 2: '  ' },
          initialAnswers,
          deepAnswers: Array.from({ length: 8 }, (_, index) => ({
            id: `life-${index}`,
            theme: 'life',
            q: `追问 ${index}`,
            a: `生命主题 ${index}`
          }))
        });
        console.log(JSON.stringify(profile));
        """
    )

    profile = run_node(script)

    assert profile["current_life_stage"] == []
    assert profile["core_values"] == ["价值回答 0", "价值回答 5"]
    assert len(profile["life_themes"]) <= 4
