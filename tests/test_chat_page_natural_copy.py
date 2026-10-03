from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_PAGE = ROOT / "client/desktop/src/renderer/src/pages/ChatPage.tsx"
CHAT_CSS = ROOT / "client/desktop/src/renderer/src/styles/chat.css"
PLAN_BRIDGE = ROOT / "client/desktop/src/agent/planBridge.ts"


def test_chat_page_rotates_home_greetings():
    source = CHAT_PAGE.read_text()
    greetings = (ROOT / "client/desktop/src/renderer/src/lib/chatGreetings.ts").read_text()

    assert "pickChatGreeting" in source
    assert "homeGreeting" in source
    assert "CHAT_GREETINGS" in greetings
    assert "想说点什么？" in greetings
    assert "我在，慢慢说。" in greetings


def test_chat_page_offers_expert_conversation_starters():
    source = CHAT_PAGE.read_text()

    assert "homeStarters" in source
    assert "DEFAULT_STARTERS" in source
    assert "starter-row" in source
    assert "setDraft(starter.prompt)" in source
    assert "activeExpert?.starters" in source


def test_chat_page_no_longer_pins_approval_cards_above_composer():
    """Q4: chat-approval-dock 已移除，但 PlanEventCard 仍用于显示旧计划卡片（修复首页空白态）。"""
    source = CHAT_PAGE.read_text()

    # approval dock 不再渲染（已移除命令块 UI）
    assert "chat-approval-dock" not in source
    # PlanEventCard 仍用于显示旧计划卡片（第三十五项修复首页空白态）
    assert "runtimePlans.map((plan) => (" in source


def test_runtime_activity_prevents_empty_home_state():
    source = CHAT_PAGE.read_text()

    assert "hasRuntimeActivity" in source
    assert "runtimeRuns.length > 0" in source
    assert "runtimePlans.length > 0" in source
    assert "messages.length === 0 && !isTyping && !isSending && !activeSession && !hasRuntimeActivity" in source


def test_chat_busy_error_restores_input_without_connection_failure_copy():
    source = CHAT_PAGE.read_text()
    guards = (ROOT / "client/desktop/src/renderer/src/pages/chatPage/errorGuards.ts").read_text()

    assert "ChatBusyError" in guards
    assert "function isChatBusy" in guards
    assert "上一轮还在处理中，内容已放回输入框。等它结束后再发送。" in source
    assert "上一轮还在处理中，暂时不能重新生成。" in source
    assert source.index("isChatBusy(error)") < source.index("本地聊天请求失败。")


def test_tool_approval_cards_use_runtime_state_as_source_of_truth():
    source = CHAT_PAGE.read_text()

    assert "toolEventWithRuntimeResult" in source
    assert "runtimeState.toolResults[event.id]" in source
    assert "current.map((event) => {" not in source
    assert "博客发布已执行" not in source


def test_completed_hugo_tools_do_not_stay_in_chat_or_composer_notice():
    source = CHAT_PAGE.read_text()

    assert "isCompletedHugoToolEvent" in source
    assert ".filter((event) => !isCompletedHugoToolEvent(event))" in source
    assert "pendingEvent?.name === 'hugo_blog'" in source
    assert "setToolNotice('')" in source


def test_conversation_thread_followup_sends_accumulated_history():
    source = CHAT_PAGE.read_text()

    assert "const nextMessages = [...messages, userMessage]" in source
    assert "const requestMessages = nextMessages.map" in source
    assert "await streamLocalChat(\n        requestMessages," in source
    assert "saveSessionMessages([...requestMessages" in source
    assert "appendSessionMessages(activeSession.id" in source
    assert "saveLocalSession" not in source


def test_job_shadow_projects_outcome_summary_without_result_body():
    source = CHAT_PAGE.read_text()

    assert "const outcome = job.outcomeVerification" in source
    assert "outcomeVerificationId: outcome?.id" in source
    assert "outcomeStatus: outcome?.status" in source
    assert "outcomeVerifier: outcome?.verifier" in source
    assert "outcomeReason: outcome?.reason" in source
    assert "result: job.result" not in source[source.index(
        "const evidenceSummary"
    ):source.index("await observeTaskPlanShadowJob")]


def test_plan_jobs_send_command_identity_into_shadow_observation():
    source = CHAT_PAGE.read_text()
    bridge = PLAN_BRIDGE.read_text()

    assert "buildConfirmedPlanJobPayload(plan)" in source
    assert "runtimeShadowRunId: plan.shadowProjection?.runId" in bridge
    assert "runtimeShadowRunId: plan.shadowProjection?.runId" in source
    assert "createCommandId: job.createCommandId" in source
    assert "startCommandId: job.startCommandId" in source
    assert "attemptId: artifact?.attemptId || job.startCommandId" in source


def test_chat_styles_keep_conversation_chrome_quiet():
    css = CHAT_CSS.read_text()

    assert ".home-subtitle" in css
    assert "background: transparent;" in css
    assert "padding: 2px 0 0;" in css
    assert ".starter-row" in css
