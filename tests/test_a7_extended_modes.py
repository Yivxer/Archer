"""
A7 — 扩展模式与安全测试
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

MODES = ROOT / "modes"


def test_a7_extended_mode_files_exist():
    for name in ["therapist", "writer", "witness", "ritualist"]:
        assert (MODES / f"{name}.md").is_file()


def test_therapist_mode_has_safety_retreat():
    text = (MODES / "therapist.md").read_text(encoding="utf-8")
    assert "心理分析者" in text
    assert "安全退让" in text
    assert "自伤" in text
    assert "专业帮助" in text


def test_writer_mode_focuses_unsayable_into_words():
    text = (MODES / "writer.md").read_text(encoding="utf-8")
    assert "作家" in text
    assert "说不清的说清楚" in text
    assert "独白" in text
    assert "书信" in text


def test_witness_mode_tracks_long_arc():
    text = (MODES / "witness.md").read_text(encoding="utf-8")
    assert "见证者" in text
    assert "长期轨迹" in text
    assert "阶段变化" in text


def test_ritualist_mode_designs_transitions():
    text = (MODES / "ritualist.md").read_text(encoding="utf-8")
    assert "仪式设计者" in text
    assert "开始" in text
    assert "结束" in text
    assert "复盘" in text
