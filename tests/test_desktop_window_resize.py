from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_TS = ROOT / "client/desktop/src/main/index.ts"


def test_desktop_window_allows_portrait_9_16_minimum():
    source = MAIN_TS.read_text()

    assert "minWidth: 360" in source
    assert "minHeight: 640" in source


def test_desktop_supports_new_portrait_window():
    source = MAIN_TS.read_text()

    assert "新建窗口" in source
    assert "CmdOrCtrl+Shift+N" in source
    assert "createWindow({ width: 405, height: 720 })" in source
