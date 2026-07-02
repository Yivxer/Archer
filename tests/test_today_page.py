from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_TSX = ROOT / "client/desktop/src/renderer/src/main.tsx"
TODAY_PAGE = ROOT / "client/desktop/src/renderer/src/pages/TodayPage.tsx"
PAGES_CSS = ROOT / "client/desktop/src/renderer/src/styles/pages.css"
TYPES_TS = ROOT / "client/desktop/src/renderer/src/types.ts"


def test_today_route_and_page_are_wired_into_desktop_navigation():
    main_source = MAIN_TSX.read_text()
    route_types = TYPES_TS.read_text()

    assert "'Today'" in route_types
    assert "import { TodayPage }" in main_source
    assert "route === 'Today'" in main_source


def test_today_page_shows_shadow_candidates_without_delivery_controls():
    source = TODAY_PAGE.read_text()

    assert "data.initiativeShadow.items" in source
    assert "主动影子候选" in source
    assert "不进入聊天，也不触发通知" in source
    assert 'aria-label="今日主动候选"' in source
    assert "暂无可展示的主动候选" in source
    assert "onDeliver" not in source


def test_today_page_has_dedicated_responsive_styles():
    css = PAGES_CSS.read_text()

    assert ".today-page" in css
    assert ".today-candidate-grid" in css
    assert ".today-candidate-card" in css


def test_initiative_sse_is_bridged_into_shared_today_data():
    main_source = MAIN_TSX.read_text()
    chat_source = (ROOT / "client/desktop/src/renderer/src/pages/ChatPage.tsx").read_text()

    assert "mergeInitiativeShadowEvent" in main_source
    assert "onInitiativeEvent={handleInitiativeEvent}" in main_source
    assert "onInitiativeEvent?: (event: InitiativeEvent) => void" in chat_source
    assert "onInitiativeEvent?.(event)" in chat_source


def test_today_page_offers_local_feedback_and_presence_controls():
    source = TODAY_PAGE.read_text()

    assert "submitInitiativeFeedback" in source
    assert "setInitiativePresence" in source
    assert "认可这条候选" in source
    assert "标记为太频繁" in source
    assert "静音主动候选" in source
    assert "presenceLabel" in source
    assert "已静音" in source


def test_today_page_surfaces_shadow_manual_review_report():
    source = TODAY_PAGE.read_text()

    assert "人工复核状态" in source
    assert "readyForManualReview" in source
    assert "observationDays" in source
    assert "recognitionRate" in source
    assert "reasons" in source


def test_today_page_surfaces_long_term_shadow_metrics_without_delivery_toggle():
    source = TODAY_PAGE.read_text()

    assert "长期验证快照" in source
    assert "longTermReport" in source
    assert "tooFrequentRate" in source
    assert "threadResumeCount" in source
    assert "readyForDeliveryReview" in source
    assert "onEnableDelivery" not in source


def test_today_page_surfaces_delivery_gate_without_opt_in_control():
    source = TODAY_PAGE.read_text()

    assert "切真发送保险丝" in source
    assert "复核建议" in source
    assert "deliveryGate" in source
    assert "reviewPacket" in source
    assert "recommendedAction" in source
    assert "canEnableDelivery" in source
    assert "shadowOnly" in source
    assert "explicit_opt_in_required" in source
    assert "remainingObservationDays" in source
    assert "earliestReviewAt" in source
    assert "onOptInDelivery" not in source
