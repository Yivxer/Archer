from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_TSX = ROOT / "client/desktop/src/renderer/src/main.tsx"
TODAY_PAGE = ROOT / "client/desktop/src/renderer/src/pages/TodayPage.tsx"
SHADOW_CARD = ROOT / "client/desktop/src/renderer/src/components/ShadowCandidateCard.tsx"
WORKSPACE_PANEL = ROOT / "client/desktop/src/renderer/src/components/WorkspaceContextPanel.tsx"
PAGES_CSS = ROOT / "client/desktop/src/renderer/src/styles/pages.css"
TYPES_TS = ROOT / "client/desktop/src/renderer/src/types.ts"
REVIEW_PANELS = ROOT / "client/desktop/src/renderer/src/components/ReviewPanels.tsx"
REVIEW_PAGE = ROOT / "client/desktop/src/renderer/src/pages/ReviewPage.tsx"


def test_today_route_and_page_are_wired_into_desktop_navigation():
    main_source = MAIN_TSX.read_text()
    route_types = TYPES_TS.read_text()

    assert "'Today'" in route_types
    assert "import { TodayPage }" in main_source
    assert "route === 'Today'" in main_source
    assert "route: 'Today'" in main_source
    assert "label: '今天'" in main_source


def test_today_page_shows_shadow_candidates_without_delivery_controls():
    source = TODAY_PAGE.read_text()

    assert "feedback.review" in source
    assert "话题拾起候选" in source
    assert "不进入聊天，也不触发系统通知" in source
    assert "item.kind === 'thread_resume'" in source
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

    assert "mergeSseInitiativeEvent" in main_source
    assert "onInitiativeEvent={handleInitiativeEvent}" in main_source
    assert "onInitiativeEvent?: (event: InitiativeEvent) => void" in chat_source
    assert "onInitiativeEvent?.(event)" in chat_source


def test_today_page_offers_local_feedback_and_presence_controls():
    source = TODAY_PAGE.read_text()

    assert "useShadowFeedback" in source
    assert "feedback.sendFeedback" in source
    assert "feedback.togglePresence" in source
    assert "认可这条候选" in source
    assert "标记为太频繁" in source
    assert "静音主动候选" in source
    assert "presenceLabel" in source
    assert "已静音" in source


def test_workspace_shadow_card_is_review_only_and_not_chat_delivery():
    card_source = SHADOW_CARD.read_text()
    panel_source = WORKSPACE_PANEL.read_text()

    assert "Archer 注意到" in card_source
    assert "不代表已经理解正确" in card_source
    assert "认可" in card_source
    assert "太频繁" in card_source
    assert "静音" in card_source
    assert "claimDailyCandidate: true" in panel_source
    assert "onNavigate?.('Today')" in panel_source
    assert "assistant" not in card_source
    assert "notification" not in card_source


def test_review_route_uses_semantic_name():
    main_source = MAIN_TSX.read_text()
    route_types = TYPES_TS.read_text()

    assert "route === 'Review'" in main_source
    assert "'Review'" in route_types
    assert "'Sessions'" not in route_types


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


def test_today_and_review_offer_explicit_reversible_thread_resume_opt_in():
    today = TODAY_PAGE.read_text()
    review_panels = REVIEW_PANELS.read_text()
    review_page = REVIEW_PAGE.read_text()

    assert "授权话题拾起" in today
    assert "关闭话题拾起" in today
    assert "setInitiativeDeliveryOptIn" in review_panels
    assert "授权话题拾起" in review_panels
    assert "关闭话题拾起" in review_panels
    assert "<ReviewInitiativeShadowPanel canControl={connected} />" in review_page
    assert "setInitiativeDeliveryOptInAction(enabled)" in review_panels
    assert "loadState !== 'ready' || storeBusy" in review_panels
