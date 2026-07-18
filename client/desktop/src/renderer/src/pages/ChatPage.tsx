import React from 'react'
import { ArrowUp, Check, ChevronDown, Copy, CornerDownLeft, Crop, Download, Edit3, FileText, Github, Loader2, Mic, Monitor, Paperclip, RotateCcw, Send, Terminal, X } from 'lucide-react'
import { appendLocalSession, approveJobToolEvent, cancelBackgroundJobEvent, createBackgroundJobEvent, ensureLocalConnection, fetchBackgroundJob, pollBackgroundJobEvents, retryBackgroundJobEvent, saveLocalSession, spawnChildJobs, streamLocalChat, ChatBusyError, StreamIdleTimeoutError, submitToolApprovalEvent, switchLocalExpert, switchLocalActiveProfile } from '../adapters/localArcher'
import { pickChatGreeting } from '../lib/chatGreetings'
import { extendedConversationModes, modelProfileShortLabel, modelSwitchNotice } from '../lib/conversationPersona'
import { canDeploy, isInputDisabled, isSendDisabled, type ConnectionState } from '../lib/connectionState'
import type { ConnectionStateSnapshot } from '../lib/useConnectionState'
import {
  createInitialDispatcherContext,
  dispatchAgentEvent,
  fallbackActionWhenNoReply,
  type DispatcherContext,
} from '../lib/chatEventDispatcher'
import type { ArcherAdapter, BackgroundJob, ChatMessage, ExpertStarter, FileRef, MemoryContextMode, ObsidianContextMode, Route, SavedSession, SessionDetail, ToolEvent, WorkIntent } from '../types'
import { ArcherRing, MarkdownMessage, ThinkingDots, ThinkingMutter } from '../components/common'
import { ExpertAvatar } from '../components/ExpertAvatar'
import { WorkspaceContextPanel, type WorkspaceJobSummary } from '../components/WorkspaceContextPanel'
import { AttachmentUpload } from '../components/AttachmentUpload'
import { ConfirmationCard } from '../components/ConfirmationCard'
import { EmptyState } from '../components/EmptyState'
import { ErrorRecovery } from '../components/ErrorRecovery'
import { LoadingState } from '../components/LoadingState'
import { PermissionPrompt } from '../components/PermissionPrompt'
import { TracePanel } from '../components/TracePanel'
import { WorkReceipt as WorkReceiptComponent } from '../components/WorkReceipt'
import { buildThinkingMutter } from '../lib/thinkingMutter'
import { useMemoryGroundedCompanion } from '../lib/useMemoryGroundedCompanion'
import { loadJobList, mergeJobEvent, useJobStore } from '../lib/jobStore'
import { buildTraceDiagnostics, createInitialRuntimeState, createPersistentEventLog, reduceRuntimeEvent, restoreRuntimeStateFromEvents, isForegroundOnlyWritingFeedbackPlan, isHugoBlogPublishPlan, jobSnapshotToAgentEvent, buildPlanChildJobSpecs, buildPlanCoordinatorPrompt, buildPlanExecutionPrompt, planWithStatus } from '../../../agent'
import type { AgentEvent, ApprovalResultEvent, EventLog, JobEvent, OrchestrationEvent, PlanEvent, TraceDiagnostics } from '../../../agent'
import type { FailureHintEvent, InitiativeEvent } from '../../../agent/contracts'

/**
 * L1.2.5：ChatPage 接收来自 App 的连接状态与动作。
 * - state 用于决定发送按钮 / 输入框 disabled
 * - deadReason 用于在 placeholder 中提示用户
 * - actions 在 dead 状态下暴露"手动恢复"入口（后续可在 composer 工具栏加按钮）
 */
export type ChatPageConnectionProps = {
  connectionState: ConnectionState
  connectionDeadReason?: string
  connectionActions?: {
    start: () => void
    recover: () => void
    quit: () => void
    refresh: () => Promise<ConnectionStateSnapshot>
  }
}

const DEFAULT_STARTERS: ExpertStarter[] = [
  { label: '倾听', prompt: '我先说一段，你不用急着给方案。' },
  { label: '卡住了', prompt: '我现在有点卡住，想先说一段。' },
  { label: '复盘', prompt: '帮我轻轻复盘一下刚才这件事。' },
  { label: '继续', prompt: '我们继续刚才那条线。' },
]

function isAbortError(error: unknown): boolean {
  return (error instanceof DOMException && error.name === 'AbortError') || (error instanceof Error && error.name === 'AbortError')
}

function isRequestTimeout(error: unknown): boolean {
  return error instanceof StreamIdleTimeoutError
    || (error instanceof Error && /timed out|timeout|超时/i.test(error.message))
}

function isChatBusy(error: unknown): boolean {
  return error instanceof ChatBusyError
    || (error instanceof Error && /chat_busy|上一轮对话仍在处理中|仍在处理/i.test(error.message))
}

export function ChatPage({
  data,
  memoryMode,
  obsidianMode,
  activeSession,
  sessionLoadState = 'idle',
  sessionLoadError = '',
  resetRuntimeOnMount = false,
  connectionState = 'disconnected',
  connectionDeadReason = '',
  connectionActions,
  onNavigate,
  onInitiativeEvent,
  onRefresh,
  onExpertSwitch,
  onSessionAppended
}: {
  data: ArcherAdapter
  memoryMode: MemoryContextMode
  obsidianMode: ObsidianContextMode
  activeSession?: SessionDetail | null
  sessionLoadState?: 'idle' | 'loading' | 'error'
  sessionLoadError?: string
  resetRuntimeOnMount?: boolean
  connectionState?: ConnectionState
  connectionDeadReason?: string
  connectionActions?: {
    start: () => void
    recover: () => void
    quit: () => void
    refresh: () => Promise<ConnectionStateSnapshot>
  }
  onNavigate?: (route: Route) => void
  onInitiativeEvent?: (event: InitiativeEvent) => void
  onRefresh?: () => Promise<void>
  onExpertSwitch?: () => Promise<void>
  onSessionAppended?: (messages: ChatMessage[], savedSession?: SavedSession) => void
}) {
  const [homeGreeting] = React.useState(() => pickChatGreeting())
  const [messages, setMessages] = React.useState<ChatMessage[]>(activeSession?.messages ?? data.chat.initialMessages)
  const [draft, setDraft] = React.useState('')
  const [isTyping, setIsTyping] = React.useState(false)
  const bottomRef = React.useRef<HTMLDivElement>(null)
  const composerRef = React.useRef<HTMLDivElement>(null)
  const draftTextareaRef = React.useRef<HTMLTextAreaElement>(null)
  const abortControllerRef = React.useRef<AbortController | null>(null)
  const backgroundJobAbortRef = React.useRef<AbortController | null>(null)
  const composingRef = React.useRef(false)
  const lastAttachedFilesRef = React.useRef<FileRef[]>([])
  const [isSending, setIsSending] = React.useState(false)
  const [isBackgrounding, setIsBackgrounding] = React.useState(false)
  const [chatError, setChatError] = React.useState('')
  const [tracePanel, setTracePanel] = React.useState<TraceDiagnostics | null>(null)
  const [saveState, setSaveState] = React.useState('')
  const [toolEvents, setToolEvents] = React.useState<ToolEvent[]>(data.chat.toolEvents)
  const [toolNotice, setToolNotice] = React.useState('')
  const { recordDirectReply } = useMemoryGroundedCompanion({
    enabled: data.status.adapter === 'local' && (connectionState === 'ready' || connectionState === 'degraded'),
    scopeId: activeSession?.id || 'desktop-session',
    setMessages,
    onControlFailure: () => setToolNotice('这次陪伴偏好没有保存成功，但不影响继续聊天。'),
  })
  const [fileRefs, setFileRefs] = React.useState<FileRef[]>([])
  const [activeComposerMenu, setActiveComposerMenu] = React.useState<'attach' | 'screenshot' | 'model' | 'persona' | null>(null)
  const [captureSources, setCaptureSources] = React.useState<Array<{ id: string; name: string; kind: 'screen' | 'window'; thumbnailEmpty?: boolean; screenStatus?: string }>>([])
  const [captureSourcesState, setCaptureSourcesState] = React.useState<'idle' | 'loading' | 'error'>('idle')
  const activeModelProfile = data.settings.activeProfile || 'lite'
  const [switchingModel, setSwitchingModel] = React.useState<'lite' | 'pro' | 'max' | null>(null)
  const [expertSwitching, setExpertSwitching] = React.useState(false)
  const workspaceJobs = useJobStore((state) => state.jobs)
  const workspaceJobsLoadState = useJobStore((state) => state.loadState)
  const workspaceJobsState: 'idle' | 'loading' | 'error' = workspaceJobsLoadState === 'loading'
    ? 'loading'
    : workspaceJobsLoadState === 'error' ? 'error' : 'idle'
  const [workspaceContextOpen, setWorkspaceContextOpen] = React.useState(() => (
    window.localStorage.getItem('archer-workspace-context-open') === '1'
  ))
  const expertSwitchingRef = React.useRef(false)
  const activeExpertId = data.experts?.current ?? data.status.expertId ?? 'default'
  const expertOptions = data.experts?.experts ?? []
  const activeExpert = expertOptions.find((option) => option.id === activeExpertId)
  const homeStarters = (activeExpert?.starters?.length ? activeExpert.starters : DEFAULT_STARTERS).slice(0, 4)
  const modelProfiles = data.settings.modelProfiles ?? []
  const fullConversationModes = extendedConversationModes(data.modes.modes ?? [])
  const activeThread = React.useMemo(() => (
    activeSession?.threadId
      ? data.threads.find((thread) => thread.id === activeSession.threadId)
      : undefined
  ), [activeSession?.threadId, data.threads])

  function sessionSaveMeta() {
    const modeId = data.modes.current || data.status.mode || 'auto'
    return {
      expertId: activeExpertId,
      expertLabel: activeExpert?.label || data.status.expertLabel,
      modeId,
      modeLabel: data.modes.modes.find((item) => item.id === modeId)?.label || modeId,
    }
  }

  function threadContextPayload() {
    if (!activeThread?.title && !activeThread?.summary) return null
    return {
      id: activeThread?.id,
      sessionId: activeSession?.id,
      title: activeThread?.title,
      summary: activeThread?.summary,
    }
  }

  React.useEffect(() => {
    if (data.status.adapter === 'local') void loadJobList()
  }, [data.status.adapter])

  React.useEffect(() => {
  }, [data.experts?.current, data.status.expertId])

  React.useEffect(() => {
    window.localStorage.setItem('archer-workspace-context-open', workspaceContextOpen ? '1' : '0')
  }, [workspaceContextOpen])
  const [copiedMessageId, setCopiedMessageId] = React.useState<number | null>(null)
  const [collapsedMessages, setCollapsedMessages] = React.useState<Record<number, boolean>>({})
  const runtimeSessionId = activeSession?.id || 'desktop-session'
  const eventLogRef = React.useRef<EventLog | null>(null)
  if (eventLogRef.current === null) {
    eventLogRef.current = createPersistentEventLog(window.localStorage)
    if (resetRuntimeOnMount) {
      eventLogRef.current.clearSession(runtimeSessionId)
    }
  }
  const [runtimeState, setRuntimeState] = React.useState(() => restoreRuntimeState(runtimeSessionId, eventLogRef.current))
  const runtimeJobs = Object.values(runtimeState.jobs).sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  const sidebarJobs = mergeWorkspaceJobs(runtimeJobs, workspaceJobs).slice(0, 3)
  const activeSidebarJobCount = sidebarJobs.filter((job) => (
    job.status === 'queued' || job.status === 'running' || job.status === 'waiting_approval'
  )).length
  const hugoPlanContextText = React.useMemo(() => messages.slice(-6).map((message) => message.text).join(' '), [messages])
  const runtimePlans = Object.values(runtimeState.plans)
    .filter((plan) => !isHugoBlogPublishPlan(plan, hugoPlanContextText))
    .filter((plan) => !isForegroundOnlyWritingFeedbackPlan(plan))
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  const recentTraceId = React.useMemo(
    () => [...runtimeState.events].reverse().find((event) => event.traceId)?.traceId,
    [runtimeState.events]
  )
  function recordAgentEvent(event: AgentEvent) {
    eventLogRef.current?.append(event)
    setRuntimeState((current) => reduceRuntimeEvent(current, event))
    if (event.type === 'job.event') {
      const merged = mergeJobEvent(event.jobId, {
        status: event.status,
        result: event.detail,
        stale: event.stale,
      })
      if (!merged) void loadJobList()
    }
    if (event.type === 'initiative.event') onInitiativeEvent?.(event)
  }

  function openTraceDiagnostics(traceId?: string) {
    const events = runtimeState.events
    const selectedTraceId = traceId
      || [...events].reverse().find((event) => event.traceId)?.traceId
      || ''
    setTracePanel(buildTraceDiagnostics(events, selectedTraceId))
  }

  React.useEffect(() => {
    setMessages(activeSession?.messages ?? data.chat.initialMessages)
    setIsTyping(false)
    setIsSending(false)
    setIsBackgrounding(false)
    setChatError('')
    setTracePanel(null)
    setSaveState('')
    setToolEvents(activeSession ? [] : data.chat.toolEvents)
    setToolNotice('')
    setFileRefs([])
    setActiveComposerMenu(null)
    setCopiedMessageId(null)
    setCollapsedMessages({})
    setRuntimeState(restoreRuntimeState(activeSession?.id || 'desktop-session', eventLogRef.current))
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    backgroundJobAbortRef.current?.abort()
    backgroundJobAbortRef.current = null
  }, [activeSession?.id])

  // After restore from eventLog, detect stale jobs (active-status jobs persisted before app restart)
  // and sync their real status from the backend API
  React.useEffect(() => {
    const activeJobs = Object.values(runtimeState.jobs).filter(
      (j) => j.status === 'queued' || j.status === 'running' || j.status === 'waiting_approval'
    )
    if (activeJobs.length === 0 || data.status.adapter !== 'local') return

    for (const job of activeJobs) {
      fetchBackgroundJob(job.jobId)
        .then((realJob) => {
          const event = jobSnapshotToAgentEvent(runtimeSessionId, realJob)
          // Only update if status actually changed (avoids re-render noise)
          if (realJob.status !== job.status) {
            recordAgentEvent(event)
          }
        })
        .catch(() => {
          // API may be restarting; stale job stays as-is, user can retry manually
        })
    }
  }, []) // Run once on mount after initial state restore

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, toolEvents, runtimeJobs.length, runtimePlans.length, isTyping])

  React.useEffect(() => {
    if (!activeComposerMenu) return
    function handlePointerDown(event: PointerEvent) {
      const target = event.target
      if (!(target instanceof Element)) return
      if (target.closest('.composer-popover') || target.closest('.composer-tool-btn')) return
      setActiveComposerMenu(null)
    }
    document.addEventListener('pointerdown', handlePointerDown)
    return () => document.removeEventListener('pointerdown', handlePointerDown)
  }, [activeComposerMenu])

  React.useEffect(() => {
    const textarea = draftTextareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    const lineHeight = parseFloat(window.getComputedStyle(textarea).lineHeight) || 23
    const maxHeight = Math.round(lineHeight * 10 + 20)
    const nextHeight = Math.min(textarea.scrollHeight, maxHeight)
    textarea.style.height = `${nextHeight}px`
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }, [draft])

  // 自动清理已完成的工具事件
  React.useEffect(() => {
    const staleIds = toolEvents
      .filter((e) => {
        const result = runtimeState.toolResults[e.id]
        if (e.name === 'hugo_blog') return false
        if (result?.receipt) return false
        return e.status === 'complete' || e.status === 'denied' || e.status === 'blocked' || result
      })
      .map((e) => e.id)
    if (!staleIds.length) return
    const timer = setTimeout(() => {
      setToolEvents((current) => current.filter((e) => !staleIds.includes(e.id)))
    }, 3000)
    return () => clearTimeout(timer)
  }, [toolEvents, runtimeState.toolResults])

  // 键盘快捷键
  React.useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const isMod = e.metaKey || e.ctrlKey

      // Cmd/Ctrl+K: 清空对话
      if (isMod && e.key === 'k') {
        e.preventDefault()
        setMessages(data.chat.initialMessages)
        setDraft('')
        setToolEvents([])
        eventLogRef.current?.clear()
        setRuntimeState(createInitialRuntimeState(runtimeSessionId))
        backgroundJobAbortRef.current?.abort()
        backgroundJobAbortRef.current = null
        return
      }

      // Cmd/Ctrl+Shift+K: 清空并重置所有状态
      if (isMod && e.shiftKey && e.key === 'K') {
        e.preventDefault()
        setMessages(data.chat.initialMessages)
        setDraft('')
        setToolEvents([])
        setChatError('')
        setSaveState('')
        setToolNotice('')
        eventLogRef.current?.clear()
        setRuntimeState(createInitialRuntimeState(runtimeSessionId))
        backgroundJobAbortRef.current?.abort()
        backgroundJobAbortRef.current = null
        return
      }

      // Cmd/Ctrl+O: 引用本地文件
      if (isMod && e.key.toLowerCase() === 'o') {
        e.preventDefault()
        pickLocalFiles()
        return
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [data])

  /**
   * L1.2.7：通过 connection state hook 判断本地 API 是否就绪。
   * - ready/degraded 直接通过（degraded 仍可聊天）
   * - dead/disconnected 直接拒绝
   * - connecting/recovering 刷新一次再判断
   * 没传 connectionActions 时回退到旧 ensureLocalConnection 路径。
   */
  async function ensureConnectionReady(): Promise<boolean> {
    if (!connectionActions) return ensureLocalConnection()
    if (connectionState === 'ready' || connectionState === 'degraded') return true
    if (connectionState === 'dead' || connectionState === 'disconnected') return false
    // connecting / recovering：主动刷新一次看是否已就绪
    const snap = await connectionActions.refresh()
    return snap.state === 'ready' || snap.state === 'degraded'
  }

  async function sendMessage() {
    const text = draft.trim()
    if (!text || isSending || isBackgrounding) return
    // L1.2.5：连接状态守门——非 ready/degraded 直接拦截
    if (isSendDisabled(connectionState)) {
      setChatError('本地 API 未就绪，请稍候或点侧栏恢复连接。')
      return
    }
    let sentFileRefs = await prepareFileRefsForSend(text)
    if (!sentFileRefs.length && lastAttachedFilesRef.current.length && messageWantsHugoPublish(text)) {
      sentFileRefs = await hydrateFileRefs(lastAttachedFilesRef.current)
    }
    const explicitFailures = sentFileRefs.filter((file) => file.attachStatus === 'failed' && isExplicitMarkdownPath(text, file.path))
    if (explicitFailures.length) {
      setToolNotice(`文稿读取失败：${explicitFailures.map((file) => file.name).join('、')}`)
      setFileRefs(sentFileRefs)
      return
    }
    const previousMessages = messages
    const nextId = messages.length + 1
    const sentMessageFileRefs = sentFileRefs.map((file) => (
      file.content
        ? { ...file, attachStatus: 'ok' as const, attachDetail: fileAttachLabel(file) }
        : { ...file, attachStatus: 'reading' as const, attachDetail: '读取中…' }
    ))
    const userMessage: ChatMessage = { id: nextId, role: 'user', text, fileRefs: sentMessageFileRefs }
    const nextMessages = [...messages, userMessage]
    setMessages(nextMessages)
    setDraft('')
    setFileRefs([])
    setChatError('')
    setSaveState('')
    setToolEvents((current) => current.filter((event) => (
      event.requiresApproval
      && event.status === 'waiting'
      && !event.id.startsWith('mock-')
      && !event.id.startsWith('local-')
    )))
    setToolNotice('')
    eventLogRef.current?.clearSession(runtimeSessionId)
    setRuntimeState((current) => ({
      ...createInitialRuntimeState(runtimeSessionId),
      pendingApprovals: current.pendingApprovals.filter((req) => req.requiresApproval),
      toolResults: Object.fromEntries(
        Object.entries(current.toolResults).filter(([, value]) => value.decision === undefined)
      ),
    }))
    setIsSending(true)

    if (!(await ensureConnectionReady())) {
      setMessages(previousMessages)
      setDraft(text)
      setFileRefs(sentMessageFileRefs)
      setIsSending(false)
      setChatError('大脑正在启动，几秒后会自动连上。')
      return
    }
    await onRefresh?.()

    setIsTyping(true)
    const controller = new AbortController()
    abortControllerRef.current = controller
    try {
      const ensured = await window.archerDesktop?.ensureApi?.()
      if (ensured && !ensured.ok && ensured.reason !== 'reused' && ensured.reason !== 'owned' && ensured.reason !== 'started') {
        throw new Error('[network] 本地大脑进程未运行，请点侧栏「重试」')
      }
      await recordDirectReply(text)
      const assistantId = nextId + 1
      const requestMessages = nextMessages.map((message) => ({ role: message.role, content: message.text }))
      const thinkingMutter = buildThinkingMutter(text, sentFileRefs.length)
      setMessages([...nextMessages, { id: assistantId, role: 'assistant', text: '', mutter: thinkingMutter }])
      let streamedReply = ''
      let reply = ''
      let sawToolEvent = false
      let lastFailureHint: AgentEvent | null = null
      // L2.3：dispatcher ctx 维护本轮事件状态（sawToolEvent / hasStreamedReply / seenRequestIds）
      const dispatcherCtx: DispatcherContext = createInitialDispatcherContext()
      await streamLocalChat(
        requestMessages,
        memoryMode,
        obsidianMode,
        sentFileRefs,
        threadContextPayload(),
        (chunk) => {
          streamedReply += chunk
          reply = streamedReply
          setMessages([...nextMessages, { id: assistantId, role: 'assistant', text: reply }])
        },
        (event) => {
          sawToolEvent = true
          if (event.name === 'file.reference' && event.draft?.path) {
            const refPath = String(event.draft.path)
            const updateRef = (file: FileRef): FileRef => {
              if (file.path !== refPath) return file
              if (event.status === 'complete') {
                const chars = event.draft?.injectedChars
                return {
                  ...file,
                  attachStatus: 'ok',
                  attachDetail: typeof chars === 'number' ? `已读取 ${chars} 字` : '已读取',
                }
              }
              if (event.status === 'blocked') {
                return { ...file, attachStatus: 'failed', attachDetail: event.summary || '读取失败' }
              }
              return { ...file, attachStatus: 'reading', attachDetail: event.summary || '读取中…' }
            }
            setMessages((current) => current.map((message) => (
              message.id === nextId
                ? { ...message, fileRefs: (message.fileRefs || []).map(updateRef) }
                : message
            )))
          }
          setToolEvents((current) => {
            const existing = current.findIndex((item) => item.id === event.id)
            if (existing === -1) return [...current, event]
            return current.map((item) => (item.id === event.id ? event : item))
          })
        },
        (event) => {
          if (event.type === 'failure.hint') lastFailureHint = event
          // L2.3：通过 dispatcher 维护 ctx（actions 由 recordAgentEvent 处理，暂不消费）
          dispatchAgentEvent(event, dispatcherCtx)
          recordAgentEvent(event)
        },
        controller.signal,
        runtimeSessionId
      )
      if (!streamedReply) {
        // L2.3：流结束未收到回复，走 dispatcher 兜底文案
        reply = fallbackActionWhenNoReply(
          lastFailureHint as FailureHintEvent | null,
          dispatcherCtx,
        ).text
        void sawToolEvent // 保留原变量供 file.reference 逻辑使用，dispatcher ctx 已独立维护
        setMessages([...nextMessages, { id: assistantId, role: 'assistant', text: reply }])
      } else {
        try {
          const finalMessages: ChatMessage[] = [...nextMessages, { id: assistantId, role: 'assistant', text: reply }]
          if (activeSession) {
            const saved = await appendLocalSession(activeSession.id, [
              { role: 'user', content: text },
              { role: 'assistant', content: reply }
            ])
            onSessionAppended?.(finalMessages, saved)
            setSaveState('已续写当前会话')
          } else {
            const saved = await saveLocalSession([...requestMessages, { role: 'assistant', content: reply }], sessionSaveMeta())
            onSessionAppended?.(finalMessages, saved)
            setSaveState('已保存到历史会话')
          }
          await onRefresh?.()
        } catch (error) {
          setSaveState('保存失败')
          setChatError(error instanceof Error ? error.message : '保存失败')
        }
      }
    } catch (error) {
      if (isAbortError(error)) {
        setMessages(previousMessages)
        setDraft(text)
        setFileRefs(sentMessageFileRefs)
        setToolEvents([])
        setToolNotice('已停止发送，内容已放回输入框')
      } else if (isRequestTimeout(error)) {
        setMessages(previousMessages)
        setDraft(text)
        setFileRefs(sentMessageFileRefs)
        setToolEvents([])
        setToolNotice('请求超时，内容已放回输入框。可以稍后重试。')
      } else if (isChatBusy(error)) {
        setMessages(previousMessages)
        setDraft(text)
        setFileRefs(sentMessageFileRefs)
        setToolEvents([])
        setToolNotice('上一轮还在处理中，内容已放回输入框。等它结束后再发送。')
      } else {
        setChatError(error instanceof Error ? error.message : '请求失败')
        setFileRefs(sentMessageFileRefs)
        setMessages([
          ...nextMessages,
          {
            id: nextId + 1,
            role: 'assistant',
            text: [
              '本地聊天请求失败。',
              '',
              '- 先点侧栏 **重试**（会自动拉起大脑进程）',
              '- 仍失败：完全退出 Archer（⌘Q）再打开',
              '- 检查设置里的连接口令是否与 `~/Projects/Archer` 内核一致',
              '- 检查 `archer.toml` 的模型配置是否可用'
            ].join('\n')
          }
        ])
      }
    } finally {
      if (abortControllerRef.current === controller) abortControllerRef.current = null
      setIsTyping(false)
      setIsSending(false)
    }
  }

  function stopSending() {
    abortControllerRef.current?.abort()
  }

  async function executeConfirmedPlan(plan: PlanEvent) {
    if (plan.status !== 'proposed' || isBackgrounding || data.status.adapter !== 'local') return
    if (isHugoBlogPublishPlan(plan, hugoPlanContextText)) {
      recordAgentEvent(planWithStatus(plan, 'dismissed'))
      setToolNotice('这类博客发布计划不能放到后台执行，请使用枫弋札记确认卡继续。')
      return
    }
    if (isForegroundOnlyWritingFeedbackPlan(plan)) {
      recordAgentEvent(planWithStatus(plan, 'dismissed'))
      setToolNotice('这类只读写作反馈不能放到后台写入，请直接在当前对话里继续。')
      return
    }
    const prompt = buildPlanExecutionPrompt(plan)
    recordAgentEvent(planWithStatus(plan, 'accepted'))

    const assistantId = messages.length + 1
    const pendingAssistant: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      text: '已按计划放入后台执行，完成后会把结果贴回来。',
    }
    const nextMessages = [...messages, pendingAssistant]
    const controller = new AbortController()

    backgroundJobAbortRef.current?.abort()
    backgroundJobAbortRef.current = controller
    setMessages(nextMessages)
    setChatError('')
    setSaveState('')
    setToolNotice('')
    setIsBackgrounding(true)

    try {
      const { result, event } = await createBackgroundJobEvent(runtimeSessionId, {
        title: plan.title || '任务计划',
        kind: 'chat',
        prompt,
        timeoutSeconds: 600,
      })
      recordAgentEvent(event)
      const finalJob = await pollBackgroundJobEvents(
        runtimeSessionId,
        result.job.id,
        recordAgentEvent,
        { signal: controller.signal },
      )
      const reply = finalJob.status === 'complete'
        ? finalJob.result || '后台任务已完成，但没有返回内容。'
        : `后台任务${finalJob.status === 'failed' ? '失败' : '结束'}：${finalJob.error || finalJob.result || finalJob.status}`
      setMessages((current) => current.map((message) =>
        message.id === assistantId ? { ...message, text: reply } : message,
      ))
      try {
        if (activeSession) {
          const saved = await appendLocalSession(activeSession.id, [{ role: 'assistant', content: reply }])
          onSessionAppended?.(nextMessages.map((message) =>
            message.id === assistantId ? { ...message, text: reply } : message,
          ), saved)
          setSaveState('计划任务结果已续写当前会话')
        } else {
          const requestMessages = messages.map((message) => ({ role: message.role, content: message.text }))
          const saved = await saveLocalSession([...requestMessages, { role: 'assistant', content: reply }], sessionSaveMeta())
          onSessionAppended?.(nextMessages.map((message) =>
            message.id === assistantId ? { ...message, text: reply } : message,
          ), saved)
          setSaveState('计划任务结果已保存到历史会话')
        }
        await onRefresh?.()
      } catch (error) {
        setSaveState('保存失败')
        setChatError(error instanceof Error ? error.message : '保存失败')
      }
    } catch (error) {
      if (!isAbortError(error)) {
        const message = error instanceof Error ? error.message : '计划任务失败'
        setChatError(message)
        setMessages((current) => current.map((item) =>
          item.id === assistantId ? { ...item, text: `计划任务创建或执行失败：${message}` } : item,
        ))
      }
    } finally {
      if (backgroundJobAbortRef.current === controller) backgroundJobAbortRef.current = null
      setIsBackgrounding(false)
    }
  }

  async function executePlanAsChildJobs(plan: PlanEvent) {
    if (plan.status !== 'proposed' || isBackgrounding || data.status.adapter !== 'local') return
    const childSpecs = buildPlanChildJobSpecs(plan)
    if (!childSpecs.length) return

    recordAgentEvent(planWithStatus(plan, 'accepted'))
    const assistantId = messages.length + 1
    const pendingAssistant: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      text: `已拆分为 ${childSpecs.length} 个子任务，可在「任务」面板查看进度。`,
    }
    setMessages((current) => [...current, pendingAssistant])
    setChatError('')
    setSaveState('')
    setToolNotice('')
    setIsBackgrounding(true)

    try {
      const { result, event } = await createBackgroundJobEvent(runtimeSessionId, {
        title: plan.title || '任务计划',
        kind: 'plan',
        prompt: buildPlanCoordinatorPrompt(plan),
        autoStart: false,
        timeoutSeconds: 600,
      })
      recordAgentEvent(event)
      const spawn = await spawnChildJobs(result.job.id, childSpecs)
      recordAgentEvent(jobSnapshotToAgentEvent(runtimeSessionId, result.job))
      const notice = spawn.spawned > 0
        ? `已创建 ${spawn.spawned} 个子任务（父任务 ${result.job.id}）。需确认的步骤请在任务面板批准。`
        : '未能创建子任务，请检查计划步骤。'
      setToolNotice(notice)
      setMessages((current) => current.map((message) =>
        message.id === assistantId ? { ...message, text: notice } : message,
      ))
      await onRefresh?.()
    } catch (error) {
      const message = error instanceof Error ? error.message : '拆分子任务失败'
      setChatError(message)
      setMessages((current) => current.map((item) =>
        item.id === assistantId ? { ...item, text: `拆分子任务失败：${message}` } : item,
      ))
    } finally {
      setIsBackgrounding(false)
    }
  }

  function dismissPlan(plan: PlanEvent) {
    if (plan.status !== 'proposed') return
    recordAgentEvent(planWithStatus(plan, 'dismissed'))
    setToolNotice('已忽略此计划')
  }

  async function sendBackgroundJob(textOverride?: string, options: {
    reason?: string
    timeoutSeconds?: number
    title?: string
    autoRouted?: boolean
  } = {}) {
    const text = (textOverride ?? draft).trim()
    if (!text || isBackgrounding || data.status.adapter !== 'local') return
    const nextId = messages.length + 1
    const userMessage: ChatMessage = { id: nextId, role: 'user', text }
    const assistantId = nextId + 1
    const pendingAssistant: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      text: options.autoRouted
        ? `我先把具体执行放到后台跑，完成后会把结果贴回来。${options.reason ? `\n\n原因：${backgroundRouteReasonLabel(options.reason)}` : ''}`
        : '我先放到后台执行，完成后会把结果贴回来。',
    }
    const nextMessages = [...messages, userMessage, pendingAssistant]
    const controller = new AbortController()

    backgroundJobAbortRef.current?.abort()
    backgroundJobAbortRef.current = controller
    setMessages(nextMessages)
    setDraft('')
    setFileRefs([])
    setChatError('')
    setSaveState('')
    setToolEvents([])
    setToolNotice('')
    eventLogRef.current?.clearSession(runtimeSessionId)
    setRuntimeState(createInitialRuntimeState(runtimeSessionId))
    setIsBackgrounding(true)

    try {
      const { result, event } = await createBackgroundJobEvent(runtimeSessionId, {
        title: options.title || text.slice(0, 42) || '后台任务',
        kind: 'chat',
        prompt: text,
        timeoutSeconds: options.timeoutSeconds ?? 300,
      })
      recordAgentEvent(event)
      const finalJob = await pollBackgroundJobEvents(
        runtimeSessionId,
        result.job.id,
        recordAgentEvent,
        { signal: controller.signal }
      )
      const reply = finalJob.status === 'complete'
        ? finalJob.result || '后台任务已完成，但没有返回内容。'
        : `后台任务${finalJob.status === 'failed' ? '失败' : '结束'}：${finalJob.error || finalJob.result || finalJob.status}`
      const finalMessages: ChatMessage[] = nextMessages.map((message) =>
        message.id === assistantId ? { ...message, text: reply, mutter: undefined } : message
      )
      setMessages((current) => current.map((message) =>
        message.id === assistantId ? { ...message, text: reply, mutter: undefined } : message
      ))
      try {
        if (activeSession) {
          const saved = await appendLocalSession(activeSession.id, [
            { role: 'user', content: text },
            { role: 'assistant', content: reply }
          ])
          onSessionAppended?.(finalMessages, saved)
          setSaveState('后台结果已续写当前会话')
        } else {
          const requestMessages = [...messages, userMessage].map((message) => ({ role: message.role, content: message.text }))
          const saved = await saveLocalSession([...requestMessages, { role: 'assistant', content: reply }], sessionSaveMeta())
          onSessionAppended?.(finalMessages, saved)
          setSaveState('后台结果已保存到历史会话')
        }
        await onRefresh?.()
      } catch (error) {
        setSaveState('保存失败')
        setChatError(error instanceof Error ? error.message : '保存失败')
      }
    } catch (error) {
      if (!isAbortError(error)) {
        const message = error instanceof Error ? error.message : '后台任务失败'
        setChatError(message)
        setMessages((current) => current.map((item) =>
          item.id === assistantId ? { ...item, text: `后台任务创建或执行失败：${message}` } : item
        ))
      }
    } finally {
      if (backgroundJobAbortRef.current === controller) backgroundJobAbortRef.current = null
      setIsBackgrounding(false)
    }
  }

  async function cancelRuntimeJob(job: JobEvent) {
    if (data.status.adapter !== 'local') return
    try {
      const { event } = await cancelBackgroundJobEvent(runtimeSessionId, job.jobId)
      recordAgentEvent(event)
      backgroundJobAbortRef.current?.abort()
      backgroundJobAbortRef.current = null
      setToolNotice('后台任务已取消')
    } catch (error) {
      setToolNotice(error instanceof Error ? error.message : '取消后台任务失败')
    }
  }

  async function retryRuntimeJob(job: JobEvent) {
    if (data.status.adapter !== 'local') return
    const controller = new AbortController()
    backgroundJobAbortRef.current?.abort()
    backgroundJobAbortRef.current = controller
    try {
      const { result, event } = await retryBackgroundJobEvent(runtimeSessionId, job.jobId)
      recordAgentEvent(event)
      setToolNotice('后台任务已重新排队')
      void pollBackgroundJobEvents(
        runtimeSessionId,
        result.job.id,
        recordAgentEvent,
        { signal: controller.signal }
      ).catch((error) => {
        if (!isAbortError(error)) setToolNotice(error instanceof Error ? error.message : '后台任务轮询失败')
      }).finally(() => {
        if (backgroundJobAbortRef.current === controller) backgroundJobAbortRef.current = null
      })
    } catch (error) {
      if (backgroundJobAbortRef.current === controller) backgroundJobAbortRef.current = null
      setToolNotice(error instanceof Error ? error.message : '重试后台任务失败')
    }
  }

  async function decideJobTool(job: JobEvent, decision: 'approved' | 'denied') {
    if (data.status.adapter !== 'local') return
    setToolNotice('')
    try {
      const { result, event } = await approveJobToolEvent(runtimeSessionId, job.jobId, job.jobId + '-tool', decision)
      recordAgentEvent(event)
      setToolNotice(decision === 'approved' ? '工具已执行' : '工具已拒绝')
    } catch (error) {
      setToolNotice(error instanceof Error ? error.message : '审批失败')
    }
  }

  async function decideTool(eventId: string, decision: 'approved' | 'denied') {
    setToolNotice('')
    if (data.status.adapter !== 'local') return
    const restoredRequest = runtimeState.pendingApprovals.find((item) => item.id === eventId)
    const pendingEvent = toolEvents.find((item) => item.id === eventId)
      || (restoredRequest ? toolEventFromRuntimeRequest(restoredRequest) : undefined)
    if (pendingEvent && !toolEvents.some((item) => item.id === eventId)) {
      setToolEvents((current) => [...current, pendingEvent])
    }
    try {
      const { result, event: approvalEvent } = await submitToolApprovalEvent(
        runtimeSessionId,
        eventId,
        decision,
        pendingEvent?.draft,
      )
      // Runtime state is the single source of truth for approval decisions.
      // recordAgentEvent persists the approval.result and updates runtimeState.toolResults,
      // which the UI reads to determine decision state for each tool card.
      recordAgentEvent(approvalEvent)
      const notice = result.executed
        ? (result.output?.trim() || result.message)
        : decision === 'denied' ? (result.message || '已取消，未执行。') : `未执行：${result.message}`
      if (pendingEvent?.name === 'hugo_blog') {
        setToolNotice('')
        const followUp = result.executed
          ? (result.output?.trim() || result.message || '枫弋札记部署已完成。')
          : decision === 'denied' ? '已取消本次枫弋札记操作，未执行部署。' : `部署未完成：${result.message}`
        setMessages((current) => [
          ...current,
          { id: current.length + 1, role: 'assistant', text: followUp },
        ])
      } else {
        setToolNotice(notice)
      }
    } catch (error) {
      setToolNotice(error instanceof Error ? error.message : '审批失败')
    }
  }

  const visibleToolEvents = toolEvents.filter((event) => (
    !event.id.startsWith('mock-')
    && !isHiddenToolEvent(event.name)
    && !isCompletedHugoToolEvent(event)
  ))
  const hasRuntimeActivity = runtimePlans.length > 0 || runtimeJobs.length > 0 || runtimeState.pendingApprovals.length > 0 || visibleToolEvents.length > 0
  const isHome = messages.length === 0 && !isTyping && !isSending && !activeSession && !hasRuntimeActivity
  const displayToolEvents = React.useMemo(() => (
    toolEvents
      .filter((event) => !isHiddenToolEvent(event.name))
      .map((event) => toolEventWithRuntimeResult(event, runtimeState.toolResults[event.id]))
      .filter((event) => !event.requiresApproval)
      .filter((event) => !isCompletedHugoToolEvent(event))
  ), [toolEvents, runtimeState.toolResults])
  const approvalToolEvents = React.useMemo(() => {
    const merged = new Map<string, ToolEvent>()
    for (const event of toolEvents) {
      if (
        event.requiresApproval
        && !runtimeState.toolResults[event.id]
        && !event.id.startsWith('mock-')
        && !event.id.startsWith('local-')
      ) {
        merged.set(event.id, event)
      }
    }
    for (const req of runtimeState.pendingApprovals) {
      if (!merged.has(req.id)) merged.set(req.id, toolEventFromRuntimeRequest(req))
    }
    return [...merged.values()]
  }, [toolEvents, runtimeState.pendingApprovals, runtimeState.toolResults])
  function updateDraftText(text: string) {
    setDraft(text)
  }

  async function hydrateFileRefs(refs: FileRef[]): Promise<FileRef[]> {
    const unique = dedupeFileRefs(refs).slice(0, 5)
    if (!unique.length || !window.archerDesktop?.readFileReferences) return unique
    const readable = unique.filter((file) => isTextLikeFile(file.path))
    if (!readable.length) return unique
    try {
      const results = await window.archerDesktop.readFileReferences(readable)
      const byPath = new Map(results.map((item) => [item.path, item]))
      return unique.map((file) => {
        const result = byPath.get(file.path)
        if (!result) return file
        if (!result.ok) {
          return { ...file, size: result.size || file.size, attachStatus: 'failed', attachDetail: result.error || '读取失败' }
        }
        return {
          ...file,
          size: result.size || file.size,
          attachStatus: 'ok',
          attachDetail: result.truncated ? `已预读 ${result.contentChars || 0} 字，已截断` : `已预读 ${result.contentChars || 0} 字`,
          content: result.content,
          contentChars: result.contentChars,
          truncated: result.truncated,
        }
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : '读取失败'
      return unique.map((file) => isTextLikeFile(file.path) ? { ...file, attachStatus: 'failed', attachDetail: message } : file)
    }
  }

  async function prepareFileRefsForSend(text: string): Promise<FileRef[]> {
    const explicitRefs = shouldLetBackendReadExplicitMarkdownPath(text) ? [] : extractMarkdownPathRefs(text)
    const merged = dedupeFileRefs([...fileRefs, ...explicitRefs])
    const hydrated = await hydrateFileRefs(merged)
    lastAttachedFilesRef.current = hydrated
    if (explicitRefs.length || hydrated.some((file) => file.content)) {
      setFileRefs(hydrated)
    }
    return hydrated
  }

  async function pickLocalFiles() {
    setToolNotice('')
    setActiveComposerMenu(null)
    if (!window.archerDesktop?.pickFiles) {
      setToolNotice('请在桌面客户端中引用本地文件。')
      return
    }
    try {
      const picked = await window.archerDesktop.pickFiles()
      if (!picked.length) return
      let added = 0
      let mergedRefs: FileRef[] = []
      setFileRefs((current) => {
        const known = new Set(current.map((item) => item.path))
        const next = [...current]
        for (const item of picked) {
          if (known.has(item.path)) continue
          next.push({ ...item, attachStatus: 'ready', attachDetail: '' })
          known.add(item.path)
          added += 1
        }
        const merged = next.slice(0, 5)
        mergedRefs = merged
        lastAttachedFilesRef.current = merged
        return merged
      })
      if (added > 0) {
        // 后台静默预读，不在 UI 显示"读取中"；预读失败也不报错（发送时由服务端兜底）
        hydrateFileRefs(mergedRefs)
          .then((hydrated) => {
            lastAttachedFilesRef.current = hydrated
            setFileRefs(hydrated)
          })
          .catch(() => {
            // 预读失败保持 'ready' 状态，发送时由服务端处理
          })
      }
    } catch (error) {
      setToolNotice(error instanceof Error ? error.message : '选择文件失败')
    }
  }

  async function captureScreenshot() {
    setToolNotice('')
    setActiveComposerMenu(null)
    if (!window.archerDesktop?.captureScreenshot) {
      setToolNotice('请在桌面客户端中截图。')
      return
    }
    try {
      const captured = await window.archerDesktop.captureScreenshot()
      if (!captured) return
      setFileRefs((current) => {
        if (current.some((item) => item.path === captured.path)) return current
        return [...current, captured].slice(0, 5)
      })
      setToolNotice('截图已加入输入框')
    } catch {
      setToolNotice('截图已取消或未授权。')
    }
  }

  async function captureWindowScreenshot() {
    setToolNotice('')
    setActiveComposerMenu(null)
    if (!window.archerDesktop?.captureWindowScreenshot) {
      setToolNotice('请在桌面客户端中截取窗口。')
      return
    }
    try {
      const captured = await window.archerDesktop.captureWindowScreenshot()
      if (!captured) return
      setFileRefs((current) => {
        if (current.some((item) => item.path === captured.path)) return current
        return [...current, captured].slice(0, 5)
      })
      setToolNotice('窗口截图已加入输入框')
    } catch {
      setToolNotice('窗口截图已取消或未授权。')
    }
  }

  async function openScreenshotMenu() {
    setToolNotice('')
    if (activeComposerMenu === 'screenshot') {
      setActiveComposerMenu(null)
      return
    }
    setActiveComposerMenu('screenshot')
  }

  async function loadCaptureSources() {
    setToolNotice('')
    if (!window.archerDesktop?.listCaptureSources) return
    setCaptureSourcesState('loading')
    try {
      const sources = await window.archerDesktop.listCaptureSources()
      setCaptureSources(sources)
      if (sources.some((source) => source.screenStatus && source.screenStatus !== 'granted')) {
        setToolNotice(`当前 Electron 屏幕权限状态：${sources[0]?.screenStatus}。可先使用“窗口截图”。`)
      }
      setCaptureSourcesState('idle')
    } catch {
      setCaptureSources([])
      setCaptureSourcesState('error')
    }
  }

  async function captureDesktopSource(sourceId: string) {
    setToolNotice('')
    setActiveComposerMenu(null)
    if (!window.archerDesktop?.captureSource) {
      setToolNotice('请在桌面客户端中截取窗口。')
      return
    }
    try {
      const captured = await window.archerDesktop.captureSource(sourceId)
      if (!captured) {
        setToolNotice('没有获取到这个窗口画面，请检查屏幕录制权限。')
        return
      }
      setFileRefs((current) => {
        if (current.some((item) => item.path === captured.path)) return current
        return [...current, captured].slice(0, 5)
      })
      setToolNotice('屏幕画面已加入输入框')
    } catch (error) {
      const message = error instanceof Error ? error.message : ''
      if (message.includes('screen:')) {
        setToolNotice(`Electron 屏幕权限未通过（${message.replace(/^.*screen:/, '')}），请先用“窗口截图”或重新授权 Archer。`)
      } else {
        setToolNotice('无法截取这个窗口，请先试“窗口截图”，或检查屏幕录制权限。')
      }
    }
  }

  function startSystemDictationHint() {
    setActiveComposerMenu(null)
    draftTextareaRef.current?.focus()
    setToolNotice(window.archerDesktop?.platform === 'darwin' ? '已聚焦输入框。可按 Fn 两下或使用系统听写开始语音输入。' : '已聚焦输入框，可使用系统语音输入。')
  }

  function removeFileRef(path: string) {
    setFileRefs((current) => current.filter((item) => item.path !== path))
  }

  async function copyMessageText(message: ChatMessage) {
    if (!message.text.trim()) return
    try {
      await navigator.clipboard.writeText(message.text)
      setCopiedMessageId(message.id)
      window.setTimeout(() => setCopiedMessageId((current) => (current === message.id ? null : current)), 1200)
    } catch {
      setToolNotice('复制失败')
    }
  }

  function exportConversation() {
    const exportable = messages.filter((m) => m.text.trim())
    if (!exportable.length) {
      setToolNotice('没有可导出的对话')
      return
    }
    const date = new Date().toISOString().slice(0, 10)
    const title = exportable.find((m) => m.role === 'user')?.text.slice(0, 30).trim().replace(/\n/g, ' ') || '对话'
    const md = exportable.map((m) => {
      const role = m.role === 'user' ? '👤 **我**' : m.role === 'assistant' ? '🎯 **Archer**' : '⚙️ **系统**'
      return `### ${role}\n\n${m.text}`
    }).join('\n\n---\n\n')
    const content = `# Archer 对话导出\n\n> 日期：${date}\n> 标题：${title}\n\n---\n\n${md}\n`
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `archer-${date}-${title.slice(0, 20).replace(/[/\\:*?"<>|]/g, '')}.md`
    a.click()
    URL.revokeObjectURL(url)
    setToolNotice('已导出为 Markdown')
    window.setTimeout(() => setToolNotice(''), 2000)
  }

  function toggleMessageCollapsed(messageId: number) {
    setCollapsedMessages((current) => ({ ...current, [messageId]: !current[messageId] }))
  }

  function editUserMessage(message: ChatMessage) {
    setMessages((current) => current.slice(0, current.findIndex((item) => item.id === message.id)))
    setDraft(message.text)
    setToolEvents([])
    setToolNotice('已放回输入框，可重新编辑发送')
    window.setTimeout(() => draftTextareaRef.current?.focus(), 0)
  }

  function useMessageAsDraft(message: ChatMessage) {
    setDraft(message.text)
    setToolNotice(message.role === 'assistant' ? '回答已放入输入框，可继续编辑' : '问题已放入输入框')
    window.setTimeout(() => draftTextareaRef.current?.focus(), 0)
  }

  async function chooseChatModelProfile(profileId: 'lite' | 'pro' | 'max') {
    if (switchingModel || profileId === activeModelProfile) {
      setActiveComposerMenu(null)
      return
    }
    const previousModel = activeModelProfile
    setSwitchingModel(profileId)
    setActiveComposerMenu(null)
    if (!(await ensureConnectionReady())) {
      setSwitchingModel(null)
      setChatError('大脑未就绪，暂时无法切换模型。')
      return
    }
    try {
      const result = await switchLocalActiveProfile(profileId)
      if (!result.ok) {
        setSwitchingModel(null)
        setChatError(`模型切换失败：${result.error || '配置未保存'}`)
        return
      }
      const notice = modelSwitchNotice(previousModel, profileId)
      setMessages((current) => [
        ...current,
        { id: current.length + 1, role: 'system', text: notice.text, detail: notice.detail },
      ])
      setToolNotice(notice.detail)
      setChatError('')
      await onRefresh?.()
    } catch (error) {
      setChatError(error instanceof Error ? error.message : '模型切换失败')
    } finally {
      setSwitchingModel(null)
    }
  }

  function useStarter(starter: ExpertStarter) {
    setDraft(starter.prompt)
    setToolNotice('')
    window.setTimeout(() => draftTextareaRef.current?.focus(), 0)
  }

  async function regenerateAssistantMessage(message: ChatMessage) {
    if (isSending) return
    const assistantIndex = messages.findIndex((item) => item.id === message.id)
    if (assistantIndex === -1) return
    let userIndex = -1
    for (let index = assistantIndex - 1; index >= 0; index -= 1) {
      if (messages[index].role === 'user') {
        userIndex = index
        break
      }
    }
    if (userIndex === -1) return

    const previousMessages = messages
    const baseMessages = messages.slice(0, userIndex + 1)
    const assistantId = Math.max(0, ...baseMessages.map((item) => item.id)) + 1
    const thinkingMutter = buildThinkingMutter(baseMessages[userIndex]?.text || '')
    const pendingAssistant: ChatMessage = { id: assistantId, role: 'assistant', text: '', mutter: thinkingMutter }
    const requestMessages = baseMessages.map((item) => ({ role: item.role, content: item.text }))

    setMessages([...baseMessages, pendingAssistant])
    setDraft('')
    setFileRefs([])
    setChatError('')
    setSaveState('')
    setToolEvents([])
    setToolNotice('')
    eventLogRef.current?.clearSession(runtimeSessionId)
    setRuntimeState(createInitialRuntimeState(runtimeSessionId))
    setIsSending(true)
    setIsTyping(true)

    if (data.status.adapter !== 'local') {
      setMessages([...baseMessages, { id: assistantId, role: 'assistant', text: data.chat.mockReply }])
      setIsTyping(false)
      setIsSending(false)
      return
    }

    const controller = new AbortController()
    abortControllerRef.current = controller
    try {
      let streamedReply = ''
      let reply = ''
      let lastFailureHint: AgentEvent | null = null
      // L2.3：dispatcher ctx 维护本轮事件状态
      const dispatcherCtx: DispatcherContext = createInitialDispatcherContext()
      await streamLocalChat(
        requestMessages,
        memoryMode,
        obsidianMode,
        [],
        threadContextPayload(),
        (chunk) => {
          streamedReply += chunk
          reply = streamedReply
          setMessages([...baseMessages, { id: assistantId, role: 'assistant', text: reply }])
        },
        (event) => {
          setToolEvents((current) => {
            const existing = current.findIndex((item) => item.id === event.id)
            if (existing === -1) return [...current, event]
            return current.map((item) => (item.id === event.id ? event : item))
          })
        },
        (event) => {
          if (event.type === 'failure.hint') lastFailureHint = event
          // L2.3：通过 dispatcher 维护 ctx
          dispatchAgentEvent(event, dispatcherCtx)
          recordAgentEvent(event)
        },
        controller.signal,
        runtimeSessionId
      )
      // L2.3：流结束未收到回复，走 dispatcher 兜底文案（不再用 failureHintFallback + toolEvents.length）
      const regenerateReply = streamedReply
        ? reply
        : fallbackActionWhenNoReply(
            lastFailureHint as FailureHintEvent | null,
            dispatcherCtx,
          ).text
      const finalMessages: ChatMessage[] = [
        ...baseMessages,
        { id: assistantId, role: 'assistant', text: regenerateReply }
      ]
      setMessages(finalMessages)
      if (streamedReply) {
        if (activeSession) {
          onSessionAppended?.(finalMessages)
          setSaveState('已重新生成当前回答')
        } else {
          const saved = await saveLocalSession([...requestMessages, { role: 'assistant', content: reply }], sessionSaveMeta())
          onSessionAppended?.(finalMessages, saved)
          setSaveState('已保存到历史会话')
        }
        await onRefresh?.()
      }
    } catch (error) {
      if (isAbortError(error)) {
        setMessages(previousMessages)
        setToolNotice('已停止重新生成')
      } else if (isRequestTimeout(error)) {
        setMessages(previousMessages)
        setToolNotice('重新生成请求超时，可稍后再试')
      } else if (isChatBusy(error)) {
        setMessages(previousMessages)
        setToolNotice('上一轮还在处理中，暂时不能重新生成。')
      } else {
        setChatError(error instanceof Error ? error.message : '重新生成失败')
        setMessages(previousMessages)
      }
    } finally {
      if (abortControllerRef.current === controller) abortControllerRef.current = null
      setIsTyping(false)
      setIsSending(false)
    }
  }

  const composerPlaceholder = isInputDisabled(connectionState) && connectionDeadReason
    ? `本地 API 不可用：${connectionDeadReason}`
    : isInputDisabled(connectionState)
      ? '本地 API 不可用，请点击侧栏恢复连接'
      : isSendDisabled(connectionState) && connectionState === 'connecting'
        ? '正在连接本地 API…'
        : isSendDisabled(connectionState) && connectionState === 'recovering'
          ? '正在恢复本地 API…'
          : isSendDisabled(connectionState) && connectionState === 'disconnected'
            ? '未连接本地 API'
            : isHome
              ? '想说点什么…'
              : activeSession
                ? '接着这段聊…'
                : '继续说…'

  const modelButtonLabel = modelProfileShortLabel(activeModelProfile)
  const activeExpertTitle = expertOptions.find((item) => item.id === activeExpertId)?.label
    || data.status.expertLabel
    || '基础 Archer'

  const composerEl = (
    <>
    <div className="composer" ref={composerRef}>
      <AttachmentUpload
        variant="composer"
        files={fileRefs}
        onRemove={removeFileRef}
      />
      <textarea
        ref={draftTextareaRef}
        value={draft}
        onChange={(e) => updateDraftText(e.target.value)}
        onCompositionStart={() => { composingRef.current = true }}
        onCompositionEnd={() => { composingRef.current = false }}
        onKeyDown={(e) => {
          const nativeEvent = e.nativeEvent as KeyboardEvent & { isComposing?: boolean }
          const isComposing = composingRef.current || nativeEvent.isComposing || nativeEvent.keyCode === 229
          if (e.key === 'Enter' && !e.shiftKey && !isComposing) { e.preventDefault(); sendMessage() }
        }}
        placeholder={composerPlaceholder}
        rows={1}
        autoFocus={isHome}
        disabled={isInputDisabled(connectionState)}
      />
      {toolNotice && <div className="composer-notice">{toolNotice}</div>}
      <div className="composer-toolbar" aria-label="输入工具栏">
        <div className="composer-left">
          <div className="composer-menu-wrapper">
            <button
              className="composer-tool-btn"
              type="button"
              onClick={() => void pickLocalFiles()}
              disabled={isSending}
              title="添加附件"
              aria-label="添加附件"
            >
              <Paperclip size={17} />
            </button>
          </div>
          <div className="composer-menu-wrapper">
            <button
              className={`composer-tool-btn${activeComposerMenu === 'screenshot' ? ' active' : ''}`}
              type="button"
              onClick={() => void openScreenshotMenu()}
              disabled={isSending}
              title="截图"
              aria-label="截图"
            >
              <Crop size={17} />
            </button>
            {activeComposerMenu === 'screenshot' && (
              <div className="composer-popover choice-menu screenshot-menu">
                <button type="button" onClick={() => void captureWindowScreenshot()}>
                  <Monitor size={15} />
                  <span>
                    <strong>窗口截图</strong>
                    <em>点击 Chrome、备忘录等窗口</em>
                  </span>
                </button>
                <button type="button" onClick={() => void captureScreenshot()}>
                  <Crop size={15} />
                  <span>
                    <strong>框选截图</strong>
                    <em>截取任意区域</em>
                  </span>
                </button>
                <button type="button" onClick={() => void loadCaptureSources()}>
                  <Monitor size={15} />
                  <span>
                    <strong>读取窗口列表</strong>
                    <em>需要屏幕录制权限</em>
                  </span>
                </button>
                {captureSourcesState === 'loading' && (
                  <div className="composer-menu-hint">正在读取屏幕和窗口…</div>
                )}
                {captureSourcesState === 'error' && (
                  <div className="composer-menu-hint warning">无法读取窗口，请检查屏幕录制权限。</div>
                )}
                {captureSources.map((source) => (
                  <button type="button" key={source.id} onClick={() => void captureDesktopSource(source.id)}>
                    <Monitor size={15} />
                    <span>
                      <strong>{source.name}</strong>
                      <em>
                        {source.kind === 'screen' ? '屏幕' : '窗口'}
                        {source.thumbnailEmpty ? ' · 预览不可用' : ''}
                      </em>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <button
            className="composer-tool-btn"
            type="button"
            onClick={startSystemDictationHint}
            disabled={isSending}
            title="语音输入"
            aria-label="语音输入"
          >
            <Mic size={17} />
          </button>
          <div className="composer-menu-wrapper">
            <button
              className={`composer-tool-btn composer-expert-btn${activeComposerMenu === 'persona' || activeExpertId !== 'default' ? ' active' : ''}`}
              type="button"
              onClick={() => setActiveComposerMenu((current) => (current === 'persona' ? null : 'persona'))}
              title={`专家：${activeExpertTitle}`}
              aria-label={`专家：${activeExpertTitle}`}
            >
              <ExpertAvatar expertId={activeExpertId} size={26} title={activeExpertTitle} />
            </button>
            {activeComposerMenu === 'persona' && (
              <div className="composer-popover choice-menu persona-menu">
                <p className="composer-menu-section-label">专家工作台</p>
                {expertOptions.map((option) => (
                  <button
                    className={activeExpertId === option.id ? 'active' : ''}
                    type="button"
                    key={option.id}
                    disabled={expertSwitching}
                    onClick={() => {
                      void (async () => {
                        if (expertSwitchingRef.current || option.id === activeExpertId) return
                        expertSwitchingRef.current = true
                        setExpertSwitching(true)
                        setActiveComposerMenu(null)
                        setChatError('')
                        try {
                          if (data.status.adapter !== 'local') {
                            if (!(await ensureConnectionReady())) {
                              throw new Error('大脑未就绪，暂时无法切换专家。')
                            }
                          }
                          await switchLocalExpert(option.id)
                          if (onExpertSwitch) {
                            await onExpertSwitch()
                          } else {
                            await onRefresh?.()
                          }
                        } catch (error) {
                          setChatError(error instanceof Error ? error.message : '专家切换失败')
                        } finally {
                          expertSwitchingRef.current = false
                          setExpertSwitching(false)
                        }
                      })()
                    }}
                  >
                    <ExpertAvatar expertId={option.id} size={24} title={option.label} />
                    <span>
                      <strong>{option.label}</strong>
                      <em>{option.note}</em>
                    </span>
                    {activeExpertId === option.id && <Check size={14} />}
                  </button>
                ))}
                {fullConversationModes.length > 0 && (
                  <>
                    <p className="composer-menu-section-label">全部姿态</p>
                    {fullConversationModes.slice(0, 4).map((mode) => (
                      <button
                        type="button"
                        key={mode.id}
                        onClick={() => {
                          setActiveComposerMenu(null)
                          sessionStorage.setItem('archer-settings-tab', 'context')
                          onNavigate?.('Settings')
                        }}
                      >
                        <span>
                          <strong>{mode.label}</strong>
                          <em>在设置页切换完整对话姿态</em>
                        </span>
                      </button>
                    ))}
                  </>
                )}
                {onNavigate && (
                  <button
                    className="composer-menu-footer"
                    type="button"
                    onClick={() => {
                      setActiveComposerMenu(null)
                      sessionStorage.setItem('archer-settings-tab', 'context')
                      onNavigate('Settings')
                    }}
                  >
                    <span>
                      <strong>更多姿态</strong>
                      <em>建造者、镜面、哲学家等 12 种完整姿态</em>
                    </span>
                  </button>
                )}
              </div>
            )}
          </div>
          <div className="composer-menu-wrapper">
              <button
              className={`composer-tool-btn composer-model-btn has-label${activeComposerMenu === 'model' ? ' active' : ''}`}
              type="button"
              onClick={() => setActiveComposerMenu((current) => (current === 'model' ? null : 'model'))}
              disabled={Boolean(switchingModel)}
              title={`模型：${modelButtonLabel}`}
              aria-label={`模型：${modelButtonLabel}`}
            >
              <span className="composer-model-label">{modelButtonLabel}</span>
            </button>
            {activeComposerMenu === 'model' && (
              <div className="composer-popover choice-menu">
                {modelProfiles.map((option) => (
                  <button
                    className={activeModelProfile === option.id ? 'active' : ''}
                    type="button"
                    key={option.id}
                    disabled={Boolean(switchingModel) || activeModelProfile === option.id}
                    onClick={() => {
                      void chooseChatModelProfile(option.id)
                    }}
                    title={option.configured ? `${modelProfileShortLabel(option.id)} 已配置` : `${modelProfileShortLabel(option.id)} 未配置 API key`}
                  >
                    <span>
                      <strong>{modelProfileShortLabel(option.id)}</strong>
                      <em>{option.provider}{option.model ? ` · ${option.model}` : ''}{option.configured ? '' : ' · 未配置'}</em>
                    </span>
                    {activeModelProfile === option.id && <Check size={14} />}
                  </button>
                ))}
                <button type="button" onClick={() => onNavigate?.('Settings')}>
                  <span>
                    <strong>打开模型设置</strong>
                    <em>查看 key 状态、测试当前档位</em>
                  </span>
                </button>
              </div>
            )}
          </div>
        </div>
        <div className="composer-right">
          <button
            className="composer-tool-btn"
            type="button"
            onClick={exportConversation}
            disabled={!messages.some((m) => m.text.trim())}
            title="导出为 Markdown"
            aria-label="导出为 Markdown"
          >
            <Download size={16} />
          </button>
          <button
            className={`composer-background${isBackgrounding ? ' active' : ''}`}
            type="button"
            onClick={() => void sendBackgroundJob()}
            disabled={isSending || isBackgrounding || !canDeploy(connectionState) || !draft.trim()}
            title="后台执行"
            aria-label="后台执行"
          >
            {isBackgrounding ? <Loader2 size={15} /> : <CornerDownLeft size={15} />}
          </button>
          <button
            className={`send-btn composer-send${draft.trim() ? ' active' : ''}${isSending ? ' stopping' : ''}`}
            type="button"
            onClick={isSending ? stopSending : sendMessage}
            disabled={!isSending && (!draft.trim() || isSendDisabled(connectionState))}
            title={isSending ? '停止并撤回本轮' : '发送'}
          >
            {isSending ? <X size={15} /> : <ArrowUp size={15} />}
          </button>
        </div>
      </div>
    </div>
    </>
  )

  if (isHome) {
    return (
      <div className="chat-home">
        <div className="home-centerpiece">
          <ArcherRing large living />
          <p className="home-title">{homeGreeting}</p>
          <div className="starter-row" aria-label="快捷开场">
            {homeStarters.map((starter) => (
              <button key={starter.label} type="button" onClick={() => useStarter(starter)}>
                {starter.label}
              </button>
            ))}
          </div>
          {sessionLoadState === 'loading' && <LoadingState stage="fetching" hint="读取会话中…" compact />}
          {sessionLoadState === 'error' && <div className="session-source-banner warning">{sessionLoadError || '会话读取失败'}</div>}
          {chatError && (
            <ErrorRecovery
              failureType="unknown_failure"
              detail={chatError}
              traceId={recentTraceId}
              onViewTrace={() => openTraceDiagnostics()}
            />
          )}
          {tracePanel && <TracePanel diagnostics={tracePanel} onClose={() => setTracePanel(null)} />}
          {composerEl}
        </div>
      </div>
    )
  }

  return (
    <div className={`chat-layout${workspaceContextOpen ? ' with-workspace-context' : ''}`}>
      {workspaceContextOpen && (
        <WorkspaceContextPanel
          activeExpertTitle={activeExpertTitle}
          isHistorySession={Boolean(activeSession)}
          modelButtonLabel={modelButtonLabel}
          memoryMode={memoryMode}
          obsidianMode={obsidianMode}
          sidebarJobs={sidebarJobs}
          workspaceJobsState={workspaceJobsState}
          activeSidebarJobCount={activeSidebarJobCount}
          homeStarters={homeStarters}
          onUseStarter={useStarter}
          onNavigate={onNavigate}
          canControlInitiative={data.status.adapter === 'local'}
          onRefresh={onRefresh}
          onClose={() => setWorkspaceContextOpen(false)}
        />
      )}
      <div className="conversation">
        {activeSession && (
          <div className="session-source-banner">
            <span>已恢复历史会话</span>
            <strong>{activeSession.title}</strong>
            <em>
              {activeSession.date} · {activeSession.turns} 轮
              {activeSession.expertLabel ? ` · ${activeSession.expertLabel}` : ''}
              {' · '}继续发送会续写当前会话
            </em>
          </div>
        )}
        {sessionLoadState === 'error' && <div className="session-source-banner warning">{sessionLoadError || '会话读取失败'}</div>}
        {messages.map((message) => {
          const canAct = message.text.trim().length > 0
          const isAssistantLike = message.role === 'assistant' || message.role === 'system'
          const isCollapsed = Boolean(collapsedMessages[message.id])
          const displayText = isCollapsed && message.text.length > 220 ? `${message.text.slice(0, 220).trim()}…` : message.text
          return (
            <div key={message.id} className={`message-row ${message.role}${canAct ? ' has-actions' : ''}${isCollapsed ? ' is-collapsed' : ''}`}>
	              {message.role === 'assistant' && (
                <div className="avatar"><ArcherRing small /></div>
              )}
	              <div className="message-stack">
                {message.role === 'user' && message.fileRefs?.length ? (
                  <AttachmentUpload variant="message" files={message.fileRefs} />
                ) : null}
	                <div className={`message-bubble${message.role === 'assistant' && !message.text.trim() && (message.mutter || isTyping) ? ' typing-brand' : ''}`}>
	                  {message.role === 'system' && message.detail ? (
	                    <span title={message.detail}>{displayText}</span>
	                  ) : message.role === 'assistant' && !message.text.trim() && message.mutter ? (
	                    <ThinkingMutter text={message.mutter} />
                  ) : message.role === 'assistant' && !message.text.trim() && isTyping ? (
                    <ThinkingDots />
                  ) : isAssistantLike ? <MarkdownMessage text={displayText} /> : message.text}
                </div>
                {canAct && (
                  <div className="message-actions" aria-label="消息操作">
                    <button
                      type="button"
                      className="msg-action-btn"
                      onClick={() => copyMessageText(message)}
                      title={copiedMessageId === message.id ? '已复制' : '复制'}
                      aria-label={copiedMessageId === message.id ? '已复制' : '复制'}
                    >
                      <Copy size={13} />
                    </button>
                    {message.role === 'user' ? (
                      <button
                        type="button"
                        className="msg-action-btn"
                        onClick={() => editUserMessage(message)}
                        title="重新编辑"
                        aria-label="重新编辑"
                      >
                        <Edit3 size={13} />
                      </button>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="msg-action-btn"
                          onClick={() => useMessageAsDraft(message)}
                          title="放入输入框"
                          aria-label="放入输入框"
                        >
                          <CornerDownLeft size={13} />
                        </button>
                        <button
                          type="button"
                          className="msg-action-btn"
                          onClick={() => void regenerateAssistantMessage(message)}
                          disabled={isSending}
                          title="重新生成"
                          aria-label="重新生成"
                        >
                          <RotateCcw size={13} />
                        </button>
                      </>
                    )}
                    {isAssistantLike && message.text.length > 220 && (
                      <button
                        type="button"
                        className="msg-action-btn"
                        onClick={() => toggleMessageCollapsed(message.id)}
                        title={isCollapsed ? '展开' : '收起'}
                        aria-label={isCollapsed ? '展开' : '收起'}
                      >
                        {isCollapsed ? <ChevronDown size={13} /> : <ChevronDown size={13} style={{ transform: 'rotate(180deg)' }} />}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        })}

        {runtimeJobs.map((job) => (
          <JobEventCard
            key={job.jobId}
            job={job}
            onCancel={() => void cancelRuntimeJob(job)}
            onRetry={() => void retryRuntimeJob(job)}
            onApprove={(decision) => void decideJobTool(job, decision)}
          />
        ))}

        {runtimePlans.map((plan) => (
          <PlanEventCard
            key={plan.id}
            plan={plan}
            busy={isBackgrounding}
            onAccept={() => void executeConfirmedPlan(plan)}
            onSplit={plan.steps.length > 1 ? () => void executePlanAsChildJobs(plan) : undefined}
            onDismiss={() => dismissPlan(plan)}
          />
        ))}

        {approvalToolEvents.map((event) => (
          <ToolEventCard
            key={event.id}
            event={event}
            decision={runtimeState.toolResults[event.id]?.decision}
            onDecide={(nextDecision) => decideTool(event.id, nextDecision)}
          />
        ))}

        {displayToolEvents
          .map((event) => (
            <ToolEventCard
              key={event.id}
              event={event}
              decision={runtimeState.toolResults[event.id]?.decision}
              onDecide={(nextDecision) => decideTool(event.id, nextDecision)}
            />
          ))}

        {chatError && (
          <ErrorRecovery
            failureType="unknown_failure"
            detail={chatError}
            traceId={recentTraceId}
            onViewTrace={() => openTraceDiagnostics()}
          />
        )}
        <div ref={bottomRef} />
      </div>

      <div className="conversation-divider" />
      {tracePanel && <TracePanel diagnostics={tracePanel} onClose={() => setTracePanel(null)} />}
      {composerEl}
    </div>
  )
}

function restoreRuntimeState(sessionId: string, eventLog: EventLog | null) {
  return restoreRuntimeStateFromEvents(sessionId, eventLog?.all() ?? [])
}

function mergeWorkspaceJobs(runtimeJobs: JobEvent[], workspaceJobs: BackgroundJob[]): WorkspaceJobSummary[] {
  const merged = new Map<string, WorkspaceJobSummary>()
  for (const job of workspaceJobs) {
    merged.set(job.id, {
      id: job.id,
      title: job.title,
      status: job.status,
      kind: job.kind,
      preview: job.result || job.error || job.prompt,
      createdAt: job.createdAt,
    })
  }
  for (const job of runtimeJobs) {
    merged.set(job.jobId, {
      id: job.jobId,
      title: job.title,
      status: job.status,
      kind: 'runtime',
      preview: job.detail,
      createdAt: job.createdAt,
    })
  }
  return Array.from(merged.values()).sort((a, b) => b.createdAt.localeCompare(a.createdAt))
}

/** Convert a runtime ToolRequestEvent to display-friendly ToolEvent for ToolEventCard rendering */
function isHiddenToolEvent(name: string): boolean {
  return ['obsidian_search', 'obsidian_read', 'memory.retrieve', 'memory-retrieve', 'file.reference'].includes(name)
}

function isCompletedHugoToolEvent(event: ToolEvent): boolean {
  return event.name === 'hugo_blog' && event.status === 'complete'
}

function toolEventFromRuntimeRequest(req: import('../../../agent').ToolRequestEvent): ToolEvent {
  return {
    id: req.id,
    name: req.toolName,
    status: req.requiresApproval ? 'waiting' : (req.blocked ? 'blocked' : 'complete'),
    risk: req.risk,
    summary: req.summary,
    detail: req.detail,
    requiresApproval: req.requiresApproval,
    draft: {
      skillName: req.toolName,
      displayName: req.displayName,
      args: req.args,
      blocked: req.blocked,
      ...req.draft,
    },
  }
}

function toolEventWithRuntimeResult(event: ToolEvent, result?: ApprovalResultEvent): ToolEvent {
  if (!result) return event
  const output = result.output
    ? `output: ${result.output.slice(0, 500)}${result.output.length > 500 ? '…(已截断)' : ''}`
    : result.message
  return {
    ...event,
    status: result.decision === 'denied' ? 'denied' : result.executed ? 'complete' : 'blocked',
    summary: result.message || event.summary,
    detail: output,
    requiresApproval: false,
    receipt: result.receipt,
  }
}

function JobEventCard({
  job,
  onCancel,
  onRetry,
  onApprove
}: {
  job: JobEvent
  onCancel: () => void
  onRetry: () => void
  onApprove?: (decision: 'approved' | 'denied') => void
}) {
  const isActive = job.status === 'queued' || job.status === 'running' || job.status === 'waiting_approval'
  const canRetry = job.status === 'failed' || job.status === 'cancelled'
  const needsApproval = job.status === 'waiting_approval'

  return (
    <article className={`job-event-card ${job.status}`}>
      <div className="job-event-summary">
        {isActive && !needsApproval ? <Loader2 size={14} /> : needsApproval ? <Loader2 size={14} /> : <Check size={14} />}
        <span>{job.title || '后台任务'}</span>
        <em>{jobStatusLabel(job.status, job.stale)}</em>
        {isActive && !needsApproval && (
          <button type="button" onClick={onCancel} title="取消后台任务" aria-label="取消后台任务">
            <X size={13} />
          </button>
        )}
        {needsApproval && onApprove && (
          <>
            <button type="button" className="button-primary-compact" onClick={() => onApprove('approved')} title="批准并执行" aria-label="批准">
              <Check size={13} />
            </button>
            <button type="button" className="button-danger-compact" onClick={() => onApprove('denied')} title="拒绝" aria-label="拒绝">
              <X size={13} />
            </button>
          </>
        )}
        {canRetry && (
          <button type="button" onClick={onRetry} title="重试后台任务" aria-label="重试后台任务">
            <RotateCcw size={13} />
          </button>
        )}
      </div>
      {job.detail && (
        <div className="job-event-detail">
          {job.detail.length > 180 ? `${job.detail.slice(0, 180).trim()}...` : job.detail}
        </div>
      )}
      {needsApproval && job.detail && (
        <div className="approval-actions compact">
          <span className="approval-hint">此任务需要您确认后才能继续</span>
        </div>
      )}
    </article>
  )
}

function PlanEventCard({
  plan,
  busy = false,
  onAccept,
  onSplit,
  onDismiss,
}: {
  plan: PlanEvent
  busy?: boolean
  onAccept?: () => void
  onSplit?: () => void
  onDismiss?: () => void
}) {
  const isProposed = plan.status === 'proposed'
  return (
    <article className={`plan-event-card ${plan.status}`}>
      <div className="plan-event-summary">
        <FileText size={14} />
        <span>{plan.title || '任务计划'}</span>
        <em>{plan.status === 'proposed' ? '待确认' : plan.status === 'accepted' ? '已确认' : '已忽略'}</em>
      </div>
      {plan.detail && <div className="plan-event-detail">{plan.detail}</div>}
      <ol className="plan-event-steps">
        {plan.steps.map((step) => (
          <li key={step.id}>
            <span>{step.action}</span>
            <em>{step.tool}{step.requiresApproval ? ' · 需确认' : ''}</em>
          </li>
        ))}
      </ol>
      {isProposed && onAccept && onDismiss && (
        <div className="plan-event-actions">
          <button className="quiet-button" type="button" disabled={busy} onClick={onDismiss}>
            忽略
          </button>
          {onSplit && (
            <button className="quiet-button" type="button" disabled={busy} onClick={onSplit}>
              拆分子任务
            </button>
          )}
          <button className="quiet-button strong" type="button" disabled={busy} onClick={onAccept}>
            {onSplit ? '整包执行' : '按计划执行'}
          </button>
        </div>
      )}
    </article>
  )
}

function ToolEventCard({
  event,
  decision,
  onDecide,
  defaultExpanded = false
}: {
  event: ToolEvent
  decision?: 'approved' | 'denied'
  onDecide: (decision: 'approved' | 'denied') => void
  defaultExpanded?: boolean
}) {
  const needsApproval = Boolean(event.requiresApproval && !decision)
  const kind = toolKind(event)
  let Icon = FileText
  if (kind === 'shell') Icon = Terminal
  else if (kind === 'github') Icon = Github
  else if (kind === 'publish') Icon = Send
  const [expanded, setExpanded] = React.useState(defaultExpanded || needsApproval)

  return (
    <article className={`tool-event-card ${event.status} ${kind} risk-${event.risk} ${expanded ? 'expanded' : 'collapsed'}`}>
      <button className="tool-event-summary" type="button" onClick={() => setExpanded((value) => !value)}>
        <Icon size={14} />
        <span>{toolCompactText(event, kind)}</span>
        <em>{statusLabel(event.status, needsApproval)}</em>
        <ChevronDown size={13} />
      </button>

      {needsApproval && !event.draft?.workIntent && (
        <div className="approval-actions compact">
          <button className="button-primary" type="button" onClick={() => onDecide('approved')} title={(() => { if (kind === 'shell' || kind === 'github') return '执行'; if (kind === 'publish') return '发布'; return '写入'; })()}>
            <Check size={13} />
          </button>
          <button className="button-danger" type="button" onClick={() => onDecide('denied')} title="放弃">
            <X size={13} />
          </button>
        </div>
      )}

      {expanded && (
        <div className="tool-event-detail">
          <p>{event.summary}</p>
          {event.receipt ? (
            <WorkReceiptComponent receipt={event.receipt} />
          ) : null}
          <ToolEventBody
            event={event}
            kind={kind}
            needsApproval={needsApproval}
            onDecide={onDecide}
          />
        </div>
      )}
    </article>
  )
}

function toolCompactText(event: ToolEvent, kind: 'shell' | 'github' | 'file' | 'publish'): string {
  if (kind === 'shell') return event.draft?.command ? `$ ${event.draft.command}` : event.summary || event.name
  if (kind === 'github') return [event.draft?.action, event.draft?.repo, event.draft?.title].filter(Boolean).join(' · ') || event.summary || event.name
  if (kind === 'publish') return event.draft?.title || event.draft?.path || '博客发布'
  return event.draft?.title || event.draft?.path || event.summary || toolTitle(event)
}

function toolDisplayName(kind: 'shell' | 'github' | 'file' | 'publish', event: ToolEvent): string {
  if (kind === 'shell') return 'Shell 执行'
  if (kind === 'github') return 'GitHub 操作'
  if (kind === 'publish') return '博客发布'
  if (event.name === 'file.reference') return '文件引用'
  if (event.name === 'obsidian_write' || event.name === 'obsidian.read') return 'Obsidian 写入'
  return '文件操作'
}

function toolTargetPreview(event: ToolEvent): { path?: string; url?: string; command?: string } | undefined {
  if (event.draft?.path) return { path: event.draft.path }
  if (event.draft?.targetUrl) return { url: event.draft.targetUrl }
  if (event.draft?.command) return { command: event.draft.command }
  return undefined
}

function ToolEventBody({
  event,
  kind,
  needsApproval,
  onDecide,
}: {
  event: ToolEvent
  kind: 'shell' | 'github' | 'file' | 'publish'
  needsApproval: boolean
  onDecide: (decision: 'approved' | 'denied') => void
}) {
  const output = event.detail.startsWith('output: ') ? event.detail.slice(8) : ''
  const workIntent = event.draft?.workIntent
  if (workIntent) {
    if (needsApproval) {
      return (
        <ConfirmationCard
          workIntent={workIntent}
          toolEventId={event.id}
          risk={event.risk}
          toolDisplayName={toolDisplayName(kind, event)}
          targetPreview={toolTargetPreview(event)}
          onApprove={() => onDecide('approved')}
          onReject={() => onDecide('denied')}
        />
      )
    }
    return <WorkIntentBlock intent={workIntent} fallbackDetail={event.detail} />
  }

  if (kind === 'shell') {
    return (
      <div className="tool-terminal-block">
        {event.draft?.command && <code>$ {event.draft.command}</code>}
        <pre>{output || event.detail}</pre>
      </div>
    )
  }

  if (kind === 'github') {
    return (
      <div className="tool-path-block">
        <strong>{[event.draft?.action, event.draft?.repo, event.draft?.title].filter(Boolean).join(' · ') || event.name}</strong>
        {event.detail && <span>{event.detail}</span>}
      </div>
    )
  }

  if (kind === 'publish') {
    return (
      <div className="tool-path-block">
        <strong>{event.draft?.title || event.draft?.path || '博客文章'}</strong>
        {event.detail && <span>{event.detail}</span>}
      </div>
    )
  }

  if (event.name === 'file.reference') {
    if (event.status === 'blocked') {
      return (
        <PermissionPrompt
          level="read"
          reason={event.detail || '文件引用被阻止'}
          target={event.draft?.path ? { path: event.draft.path } : undefined}
        />
      )
    }
    return (
      <div className="tool-path-block">
        <strong>{event.draft?.title || event.draft?.path || event.detail || event.name}</strong>
        {event.draft?.path && <span>{event.draft.path}</span>}
        {event.draft?.injectedChars !== undefined && (
          <span>
            已注入 {event.draft.injectedChars} 字符
            {event.draft.truncated ? ' · 已截断' : ''}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="tool-path-block">
      <strong>{event.draft?.path || event.detail || event.name}</strong>
      {event.draft?.contentPreview && <span>{event.draft.contentPreview}</span>}
      {!event.draft?.contentPreview && event.detail && <span>{event.detail}</span>}
      {event.draft?.beforeText !== undefined && event.draft?.afterText !== undefined && (
        <div className="obsidian-diff-preview">
          {event.draft.previewExists && event.draft.beforeText ? (
            <div className="diff-side diff-before">
              <em>写入前</em>
              <pre>{event.draft.beforeText}</pre>
            </div>
          ) : (
            <div className="diff-side diff-empty">
              <em>笔记不存在，将新建</em>
            </div>
          )}
          <div className="diff-side diff-after">
            <em>写入后（{event.draft.previewMode || 'append'}）</em>
            <pre>{event.draft.afterText}</pre>
          </div>
        </div>
      )}
    </div>
  )
}

function WorkIntentBlock({ intent, fallbackDetail }: { intent: WorkIntent; fallbackDetail: string }) {
  const targets = Array.isArray(intent.targets) ? intent.targets : []
  const steps = Array.isArray(intent.steps) ? intent.steps : []
  return (
    <div className="tool-path-block">
      <strong>{[intent.workflowName, intent.action].filter(Boolean).join(' · ') || '工作确认'}</strong>
      {targets.map((target, index) => (
        <span key={`${target.label || 'target'}-${index}`}>
          {[target.label, target.path || target.url].filter(Boolean).join('：')}
        </span>
      ))}
      {steps.length > 0 && <span>预计步骤：{steps.join(' → ')}</span>}
      {intent.verifyPlan && <span>验证：{intent.verifyPlan}</span>}
      {intent.rollbackPlan && <span>回滚：{intent.rollbackPlan}</span>}
      {!targets.length && fallbackDetail && <span>{fallbackDetail}</span>}
    </div>
  )
}

function toolKind(event: ToolEvent): 'shell' | 'github' | 'file' | 'publish' {
  if (event.name === 'shell' || event.name === 'shell.execute') return 'shell'
  if (event.name === 'github' || event.name === 'github_ops') return 'github'
  if (event.name === 'hugo_blog') return 'publish'
  return 'file'
}

function toolTitle(event: ToolEvent): string {
  if (event.name === 'memory.compact') return '已整理记忆'
  if (event.name === 'shell' || event.name === 'shell.execute') return 'Shell 命令'
  if (event.name === 'github' || event.name === 'github_ops') return 'GitHub 操作'
  if (event.name === 'hugo_blog') return '博客发布'
  if (event.name === 'file.reference') return isObsidianMarkdownPath(String(event.draft?.path || '')) ? 'Obsidian 文稿引用' : '本地文件引用'
  if (event.name === 'obsidian_read') return 'Obsidian 读取'
  if (event.name === 'obsidian_write') return 'Obsidian 写入'
  if (event.name.includes('obsidian')) return 'Obsidian 文档'
  return event.name
}

function toolTarget(event: ToolEvent, kind: 'shell' | 'github' | 'file'): string {
  if (kind === 'shell') return event.draft?.command || event.detail || 'Shell 命令'
  if (kind === 'github') return [event.draft?.repo, event.draft?.title].filter(Boolean).join(' · ') || event.detail || 'GitHub'
  if (event.name === 'file.reference') return event.draft?.title || event.draft?.path || event.detail || '本地文件'
  return event.draft?.path || event.detail || '本地文件'
}

function riskLabel(risk: ToolEvent['risk']): string {
  if (risk === 'critical') return '极高'
  if (risk === 'high') return '高'
  if (risk === 'medium') return '中'
  return '低'
}

function statusLabel(status: ToolEvent['status'], needsApproval: boolean): string {
  if (needsApproval) return '等待确认'
  if (status === 'running') return '执行中'
  if (status === 'waiting') return '等待中'
  if (status === 'complete') return '已完成'
  if (status === 'blocked') return '失败或已阻止'
  if (status === 'denied') return '已放弃'
  return status
}

function jobStatusLabel(status: JobEvent['status'], stale?: boolean): string {
  if (status === 'queued') return '等待中'
  if (status === 'running') return '执行中'
  if (status === 'waiting_approval') return '等待确认'
  if (status === 'complete') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'cancelled' && stale) return '已取消（无进展超时）'
  if (status === 'cancelled') return '已取消'
  return status
}

function backgroundRouteReasonLabel(reason: string): string {
  if (reason === 'large request') return '内容较长，适合后台持续处理'
  if (reason === 'implementation-style request') return '这是实现/修改类任务，适合后台执行'
  return '适合后台执行'
}

function messageWantsHugoPublish(text: string): boolean {
  const lowered = text.toLowerCase()
  const publishSignal = /部署|上线|发布|枫弋|札记|博客|iver\.yivxer|yivxer-blog/.test(lowered)
  const localMarkdownArticle = /\/users\/.+\.md/.test(lowered) && /文章|笔记/.test(lowered)
  return publishSignal || localMarkdownArticle
}

function isTextLikeFile(path: string): boolean {
  return /\.(md|txt|json|toml|ya?ml|py|tsx?|jsx?|css|html|csv|log)$/i.test(path)
}

function isObsidianMarkdownPath(path: string): boolean {
  return /\.md$/i.test(path) && (/iCloud~md~obsidian|Obsidian|\/Documents\/个人知识管理系统\//i.test(path))
}

function extractMarkdownPathRefs(text: string): FileRef[] {
  const matches = text.match(/(?:~|\/Users)\/[^\n\r]+?\.md\b/g) || []
  return matches.map((raw) => {
    const path = raw.trim()
    return {
      path,
      name: path.split(/[\\/]/).pop() || path,
      attachStatus: 'reading' as const,
      attachDetail: '读取中…',
    }
  })
}

function shouldLetBackendReadExplicitMarkdownPath(text: string): boolean {
  if (!extractMarkdownPathRefs(text).length) return false
  return /(?:枫弋札记|博客|博文|部署|发布|上传|发到|写到博客|hugo|yivxer-blog)/i.test(text)
}

function isExplicitMarkdownPath(text: string, path: string): boolean {
  return extractMarkdownPathRefs(text).some((ref) => ref.path === path)
}

function dedupeFileRefs(refs: FileRef[]): FileRef[] {
  const byPath = new Map<string, FileRef>()
  for (const ref of refs) {
    if (!ref.path || byPath.has(ref.path)) continue
    byPath.set(ref.path, ref)
  }
  return [...byPath.values()]
}

function fileAttachLabel(file: FileRef): string {
  if (file.attachStatus === 'reading') return file.attachDetail || '读取中…'
  if (file.attachStatus === 'ok') return file.attachDetail || '已读取'
  if (file.attachStatus === 'failed') return file.attachDetail || '读取失败'
  if (file.attachStatus === 'ready') return file.attachDetail || '待发送'
  return formatFileSize(file.size)
}

function formatFileSize(size?: number): string {
  if (!size) return '未知大小'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
