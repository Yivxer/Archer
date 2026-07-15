from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "client/desktop/src/renderer/src/main.tsx"
REVIEW_PAGE = ROOT / "client/desktop/src/renderer/src/pages/ReviewPage.tsx"


def test_session_consumers_use_session_store_instead_of_direct_adapter_reads():
    main_source = MAIN.read_text()
    review_source = REVIEW_PAGE.read_text()

    assert "from './lib/sessionStore'" in main_source
    assert "loadSessionDetail" in main_source
    assert "loadLocalSession" not in main_source

    assert "from '../lib/sessionStore'" in review_source
    assert "useSessionStore" in review_source
    assert "loadSessionDetail" in review_source
    assert "searchSessions" in review_source
    assert "loadLocalSession" not in review_source
    assert "searchLocalSessions" not in review_source
