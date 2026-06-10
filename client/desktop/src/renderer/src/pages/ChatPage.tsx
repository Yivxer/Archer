import React from 'react'
import { ArrowUp, Check, ChevronDown, Copy, CornerDownLeft, Crop, Edit3, FileText, Github, Infinity, Loader2, Mic, Monitor, Paperclip, RotateCcw, Send, Terminal, UserRoundCog, X } from 'lucide-react'
import { appendLocalSession, approveJobToolEvent, cancelBackgroundJobEvent, createBackgroundJobEvent, fetchBackgroundJob, pollBackgroundJobEvents, retryBackgroundJobEvent, saveLocalSession, streamLocalChat, submitToolApprovalEvent, switchLocalMode } from '../adapters/localArcher'
import { extendedConversationModes, PERSONA_PRESETS, personaIdFromMode } from '../lib/conversationPersona'
import type { ArcherAdapter, ChatMessage, FileRef, MemoryContextMode, ObsidianContextMode, SessionDetail, ToolEvent } from '../types'
import { ArcherRing, MarkdownMessage, ThinkingDots } from '../components/common'
import { createInitialRuntimeState, createPersistentEventLog, reduceRuntimeEvent, routeTaskForRuntime, jobSnapshotToAgentEvent } from '../../../agent'
import type { AgentEvent, EventLog, JobEvent } from '../../../agent'

const CHAT_STARTERS = [
  { label: '先听我说', prompt: '我先说一段，你不用急着给方案。' },
  { label: '有点卡住', prompt: '我现在有点卡住，想先说一段。' },
  { label: '轻轻复盘', prompt: '帮我轻轻复盘一下刚才这件事。' },
  { label: '继续那条线', prompt: '我们继续刚才那条线。' },
]

const MODEL_OPTIONS = [
  { id: 'auto', label: '自动模型', note: '当前由 Archer 自动选择' },
]

const PERSONA_OPTIONS = PERSONA_PRESETS
const extendedPersonaModes = (modes: ArcherAdapter['modes']['modes']) =>
  extendedConversationModes(modes)

export function ChatPage({
  data,
  memoryMode,
  obsidianMode,
  activeSession,
  sessionLoadState = 'idle',
  sessionLoadError = '',
  onNavigate,
  onRefresh,
  onSessionAppended
}: {
  data: ArcherAdapter
  memoryMode: MemoryContextMode
  obsidianMode: ObsidianContextMode
  activeSession?: SessionDetail | null
  sessionLoadState?: 'idle' | 'loading' | 'error'
  sessionLoadError?: string
  onNavigate?: (route: 'Chat' | 'Sessions' | 'Tasks' | 'Memory' | 'Soul' | 'Skills' | 'Settings') => void
  onRefresh?: () => Promise<void>
  onSessionAppended?: (messages: ChatMessage[]) => void
}) {
  const [messages, setMessages] = React.useState<ChatMessage[]>(activeSession?.messages ?? data.chat.initialMessages)
  const [draft, setDraft] = React.useState('')
  const [draftCollapsed, setDraftCollapsed] = React.useState(false)
  const [isTyping, setIsTyping] = React.useState(false)
  const bottomRef = React.useRef<HTMLDivElement>(null)
  const composerRef = React.useRef<HTMLDivElement>(null)
  const draftTextareaRef = React.useRef<HTMLTextAreaElement>(null)
  const abortControllerRef = React.useRef<AbortController | null>(null)
  const backgroundJobAbortRef = React.useRef<AbortController | null>(null)
  const composingRef = React.useRef(false)
  const [isSending, setIsSending] = React.useState(false)
  const [isBackgrounding, setIsBackgrounding] = React.useState(false)
  const [chatError, setChatError] = React.useState('')
  const [saveState, setSaveState] = React.useState('')
  const [toolEvents, setToolEvents] = React.useState<ToolEvent[]>(data.chat.toolEvents)
  const [toolNotice, setToolNotice] = React.useState('')
  const [fileRefs, setFileRefs] = React.useState<FileRef[]>([])
  const [activeComposerMenu, setActiveComposerMenu] = React.useState<'attach' | 'screenshot' | 'model' | 'persona' | null>(null)
  const [captureSources, setCaptureSources] = React.useState<Array<{ id: string; name: string; kind: 'screen' | 'window'; thumbnailEmpty?: boolean; screenStatus?: string }>>([])
  const [captureSourcesState, setCaptureSourcesState] = React.useState<'idle' | 'loading' | 'error'>('idle')
  const [selectedModel, setSelectedModel] = React.useState('auto')
  const [selectedPersona, setSelectedPersona] = React.useState('default')
  const activeConversationMode = data.modes.current || data.status.mode || 'auto'
  const morePersonaModes = extendedPersonaModes(data.modes.modes)

  React.useEffect(() => {
    setSelectedPersona(personaIdFromMode(data.modes.current))
  }, [data.modes.current])
  const [copiedMessageId, setCopiedMessageId] = React.useState<number | null>(null)
  const [collapsedMessages, setCollapsedMessages] = React.useState<Record<number, boolean>>({})
  const runtimeSessionId = activeSession?.id || 'desktop-session'
  const eventLogRef = React.useRef<EventLog | null>(null)
  if (eventLogRef.current === null) {
    eventLogRef.current = createPersistentEventLog(window.localStorage)
  }
  const [runtimeState, setRuntimeState] = React.useState(() => restoreRuntimeState(runtimeSessionId, eventLogRef.current))
  const runtimeJobs = Object.values(runtimeState.jobs).sort((a, b) => b.createdAt.localeCompare(a.createdAt))

  function recordAgentEvent(event: AgentEvent) {
    eventLogRef.current?.append(event)
    setRuntimeState((current) => reduceRuntimeEvent(current, event))
  }

  React.useEffect(() => {
    setMessages(activeSession?.messages ?? data.chat.initialMessages)
    setIsTyping(false)
    setIsSending(false)
    setIsBackgrounding(false)
    setChatError('')
    setSaveState('')
    setToolEvents(activeSession ? [] : data.chat.toolEvents)
    setToolNotice('')
    setFileRefs([])
    setActiveComposerMenu(null)
    setDraftCollapsed(false)
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
  }, [messages, toolEvents, runtimeJobs.length, isTyping])

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
    if (draftCollapsed) {
      textarea.style.height = ''
      textarea.style.overflowY = 'hidden'
      return
    }
    textarea.style.height = 'auto'
    const lineHeight = parseFloat(window.getComputedStyle(textarea).lineHeight) || 23
    const maxHeight = Math.round(lineHeight * 10 + 20)
    const nextHeight = Math.min(textarea.scrollHeight, maxHeight)
    textarea.style.height = `${nextHeight}px`
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }, [draft, draftCollapsed])

  // 自动清理已完成的工具事件
  React.useEffect(() => {
    const staleIds = toolEvents
      .filter((e) => e.status === 'complete' || e.status === 'denied' || e.status === 'blocked')
      .map((e) => e.id)
    if (!staleIds.length) return
    const timer = setTimeout(() => {
      setToolEvents((current) => current.filter((e) => !staleIds.includes(e.id)))
    }, 3000)
    return () => clearTimeout(timer)
  }, [toolEvents])

  // 键盘快捷键
  React.useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const isMod = e.metaKey || e.ctrlKey

      // Cmd/Ctrl+K: 清空对话
      if (isMod && e.key === 'k') {
        e.preventDefault()
        setMessages(data.chat.initialMessages)
        setDraft('')
        setDraftCollapsed(false)
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
        setDraftCollapsed(false)
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

  async function sendMessage() {
    const text = draft.trim()
    if (!text || isSending || isBackgrounding) return
    const sentFileRefs = fileRefs
    if (data.status.adapter === 'local') {
      const route = routeTaskForRuntime({ text, fileCount: sentFileRefs.length })
      if (route.mode === 'background') {
        await sendBackgroundJob(text, {
          reason: route.reason,
          timeoutSeconds: route.timeoutSeconds,
          title: route.title,
          autoRouted: true,
        })
        return
      }
    }
    const previousMessages = messages
    const nextId = messages.length + 1
    const userMessage: ChatMessage = { id: nextId, role: 'user', text }
    const nextMessages = [...messages, userMessage]
    setMessages(nextMessages)
    setDraft('')
    setDraftCollapsed(false)
    setFileRefs([])
    setChatError('')
    setSaveState('')
    setToolEvents([])
    setToolNotice('')
    eventLogRef.current?.clearSession(runtimeSessionId)
    setRuntimeState(createInitialRuntimeState(runtimeSessionId))
    setIsSending(true)

    if (data.status.adapter !== 'local') {
      const fileNote = sentFileRefs.length ? '\n\n本地文件引用会在连接本地 API 后注入当前对话。' : ''
      setMessages([...nextMessages, { id: nextId + 1, role: 'assistant', text: data.chat.mockReply + fileNote }])
      setIsTyping(false)
      setIsSending(false)
      return
    }

    setIsTyping(true)
    const controller = new AbortController()
    abortControllerRef.current = controller
    try {
      const ensured = await window.archerDesktop?.ensureApi?.()
      if (ensured && !ensured.ok && ensured.reason !== 'reused' && ensured.reason !== 'owned' && ensured.reason !== 'started') {
        throw new Error('[network] 本地大脑进程未运行，请点侧栏「重试」')
      }
      const assistantId = nextId + 1
      const requestMessages = nextMessages.map((message) => ({ role: message.role, content: message.text }))
      setMessages([...nextMessages, { id: assistantId, role: 'assistant', text: '' }])
      let reply = ''
      await streamLocalChat(
        requestMessages,
        memoryMode,
        obsidianMode,
        sentFileRefs,
        (chunk) => {
          reply += chunk
          setMessages([...nextMessages, { id: assistantId, role: 'assistant', text: reply }])
        },
        (event) => {
          setToolEvents((current) => {
            const existing = current.findIndex((item) => item.id === event.id)
            if (existing === -1) return [...current, event]
            return current.map((item) => (item.id === event.id ? event : item))
          })
        },
        recordAgentEvent,
        controller.signal
      )
      if (!reply) {
        setMessages([...nextMessages, { id: assistantId, role: 'assistant', text: '（模型无回复）' }])
      } else {
        try {
          const finalMessages: ChatMessage[] = [...nextMessages, { id: assistantId, role: 'assistant', text: reply }]
          if (activeSession) {
            await appendLocalSession(activeSession.id, [
              { role: 'user', content: text },
              { role: 'assistant', content: reply }
            ])
            onSessionAppended?.(finalMessages)
            setSaveState('已续写当前会话')
          } else {
            await saveLocalSession([...requestMessages, { role: 'assistant', content: reply }])
            setSaveState('已保存到历史会话')
          }
          await onRefresh?.()
        } catch (error) {
          setSaveState('保存失败')
          setChatError(error instanceof Error ? error.message : '保存失败')
        }
      }
    } catch (error) {
      const aborted = (error instanceof DOMException && error.name === 'AbortError') || (error instanceof Error && error.name === 'AbortError')
      if (aborted) {
        setMessages(previousMessages)
        setDraft(text)
        setDraftCollapsed(false)
        setToolEvents([])
        setToolNotice('已停止发送，内容已放回输入框')
      } else {
        setChatError(error instanceof Error ? error.message : '请求失败')
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
        ? `这个请求我已自动放入后台执行，完成后会把结果贴回来。${options.reason ? `\n\n原因：${backgroundRouteReasonLabel(options.reason)}` : ''}`
        : '已放入后台执行，完成后我会把结果贴回来。',
    }
    const nextMessages = [...messages, userMessage, pendingAssistant]
    const controller = new AbortController()

    backgroundJobAbortRef.current?.abort()
    backgroundJobAbortRef.current = controller
    setMessages(nextMessages)
    setDraft('')
    setDraftCollapsed(false)
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
        message.id === assistantId ? { ...message, text: reply } : message
      )
      setMessages((current) => current.map((message) =>
        message.id === assistantId ? { ...message, text: reply } : message
      ))
      try {
        if (activeSession) {
          await appendLocalSession(activeSession.id, [
            { role: 'user', content: text },
            { role: 'assistant', content: reply }
          ])
          onSessionAppended?.(finalMessages)
          setSaveState('后台结果已续写当前会话')
        } else {
          const requestMessages = [...messages, userMessage].map((message) => ({ role: message.role, content: message.text }))
          await saveLocalSession([...requestMessages, { role: 'assistant', content: reply }])
          setSaveState('后台结果已保存到历史会话')
        }
        await onRefresh?.()
      } catch (error) {
        setSaveState('保存失败')
        setChatError(error instanceof Error ? error.message : '保存失败')
      }
    } catch (error) {
      const aborted = (error instanceof DOMException && error.name === 'AbortError') || (error instanceof Error && error.name === 'AbortError')
      if (!aborted) {
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
        const aborted = (error instanceof DOMException && error.name === 'AbortError') || (error instanceof Error && error.name === 'AbortError')
        if (!aborted) setToolNotice(error instanceof Error ? error.message : '后台任务轮询失败')
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
    try {
      const { result, event: approvalEvent } = await submitToolApprovalEvent(runtimeSessionId, eventId, decision)
      // Runtime state is the single source of truth for approval decisions.
      // recordAgentEvent persists the approval.result and updates runtimeState.toolResults,
      // which the UI reads to determine decision state for each tool card.
      recordAgentEvent(approvalEvent)
      setToolEvents((current) =>
        current.map((event) => {
          if (event.id !== eventId) return event
          if (decision === 'denied') {
            return { ...event, status: 'denied', summary: '草稿已放弃', detail: result.message, requiresApproval: false }
          }
          if (event.name === 'shell.execute') {
            return {
              ...event,
              status: result.executed ? 'complete' : 'blocked',
              summary: result.executed ? 'Shell 命令已执行' : `命令执行失败：${event.draft?.command || ''}`,
              detail: result.output ? `output: ${result.output.slice(0, 300)}${result.output.length > 300 ? '…(已截断)' : ''}` : result.message,
              requiresApproval: false,
            }
          }
          if (event.name === 'github') {
            return {
              ...event,
              status: result.executed ? 'complete' : 'blocked',
              summary: result.executed ? 'GitHub 操作已完成' : 'GitHub 操作失败',
              detail: result.output ? `output: ${result.output.slice(0, 300)}${result.output.length > 300 ? '…(已截断)' : ''}` : result.message,
              requiresApproval: false,
            }
          }
          if (event.name === 'hugo_blog') {
            return {
              ...event,
              status: result.executed ? 'complete' : 'blocked',
              summary: result.executed ? '博客发布已执行' : '博客发布失败或未执行',
              detail: result.output ? `output: ${result.output.slice(0, 500)}${result.output.length > 500 ? '…(已截断)' : ''}` : result.message,
              requiresApproval: false,
            }
          }
          return {
            ...event,
            status: result.executed ? 'complete' : 'blocked',
            summary: result.executed ? '已写入本地 Obsidian' : '写入未执行',
            detail: result.validatedPath ? `executed: ${result.executed}, path: ${result.validatedPath}` : result.message,
            requiresApproval: false,
          }
        })
      )
      setToolNotice(result.message)
    } catch (error) {
      setToolNotice(error instanceof Error ? error.message : '审批失败')
    }
  }

  const isHome = messages.length === 0 && !isTyping && !isSending && !activeSession
  const draftLineCount = Math.max(1, draft.split('\n').length)
  const shouldCollapseDraft = (text: string) => text.split('\n').length > 8 || text.length > 1800

  function updateDraftText(text: string) {
    setDraft(text)
    if (shouldCollapseDraft(text)) setDraftCollapsed(true)
    if (!text.trim()) setDraftCollapsed(false)
  }

  function handleDraftPaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    const pasted = event.clipboardData.getData('text')
    if (!shouldCollapseDraft(pasted)) return
    event.preventDefault()
    setDraft(pasted)
    setDraftCollapsed(true)
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
      setFileRefs((current) => {
        const known = new Set(current.map((item) => item.path))
        const next = [...current]
        for (const item of picked) {
          if (known.has(item.path)) continue
          next.push(item)
          known.add(item.path)
        }
        return next.slice(0, 5)
      })
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

  function toggleMessageCollapsed(messageId: number) {
    setCollapsedMessages((current) => ({ ...current, [messageId]: !current[messageId] }))
  }

  function editUserMessage(message: ChatMessage) {
    setMessages((current) => current.slice(0, current.findIndex((item) => item.id === message.id)))
    setDraft(message.text)
    setDraftCollapsed(shouldCollapseDraft(message.text))
    setToolEvents([])
    setToolNotice('已放回输入框，可重新编辑发送')
    window.setTimeout(() => draftTextareaRef.current?.focus(), 0)
  }

  function useMessageAsDraft(message: ChatMessage) {
    setDraft(message.text)
    setDraftCollapsed(shouldCollapseDraft(message.text))
    setToolNotice(message.role === 'assistant' ? '回答已放入输入框，可继续编辑' : '问题已放入输入框')
    window.setTimeout(() => draftTextareaRef.current?.focus(), 0)
  }

  function useStarter(starter: (typeof CHAT_STARTERS)[number]) {
    setDraft(starter.prompt)
    setDraftCollapsed(false)
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
    const pendingAssistant: ChatMessage = { id: assistantId, role: 'assistant', text: '' }
    const requestMessages = baseMessages.map((item) => ({ role: item.role, content: item.text }))

    setMessages([...baseMessages, pendingAssistant])
    setDraft('')
    setDraftCollapsed(false)
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
      let reply = ''
      await streamLocalChat(
        requestMessages,
        memoryMode,
        obsidianMode,
        [],
        (chunk) => {
          reply += chunk
          setMessages([...baseMessages, { id: assistantId, role: 'assistant', text: reply }])
        },
        (event) => {
          setToolEvents((current) => {
            const existing = current.findIndex((item) => item.id === event.id)
            if (existing === -1) return [...current, event]
            return current.map((item) => (item.id === event.id ? event : item))
          })
        },
        recordAgentEvent,
        controller.signal
      )
      const finalMessages: ChatMessage[] = [
        ...baseMessages,
        { id: assistantId, role: 'assistant', text: reply || '（模型无回复）' }
      ]
      setMessages(finalMessages)
      if (reply) {
        if (activeSession) {
          onSessionAppended?.(finalMessages)
          setSaveState('已重新生成当前回答')
        } else {
          await saveLocalSession([...requestMessages, { role: 'assistant', content: reply }])
          setSaveState('已保存到历史会话')
        }
        await onRefresh?.()
      }
    } catch (error) {
      const aborted = (error instanceof DOMException && error.name === 'AbortError') || (error instanceof Error && error.name === 'AbortError')
      if (aborted) {
        setMessages(previousMessages)
        setToolNotice('已停止重新生成')
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

  const composerPlaceholder = draftCollapsed
    ? '长文本已折叠，回车发送完整内容。'
    : isHome
      ? '想说点什么…'
      : activeSession
        ? '接着这段聊…'
        : '继续说…'

  const composerEl = (
    <div className="composer" ref={composerRef}>
      {fileRefs.length > 0 && (
        <div className="file-ref-row" aria-label="已引用文件">
          {fileRefs.map((file) => (
            <span className={`file-ref-chip${file.previewDataUrl ? ' has-preview' : ''}`} key={file.path} title={file.path}>
              {file.previewDataUrl ? (
                <img src={file.previewDataUrl} alt="" />
              ) : (
                <FileText size={13} />
              )}
              <span>
                <strong>{file.name}</strong>
                <em>{formatFileSize(file.size)}</em>
              </span>
              <button type="button" onClick={() => removeFileRef(file.path)} aria-label={`移除 ${file.name}`}>
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
        <div className={`draft-collapse-card-placeholder ${draftCollapsed ? 'visible' : ''}`}>
          {draftCollapsed && (
            <>
              <span>已折叠 {draftLineCount} 行长文本</span>
              <button type="button" onClick={() => setDraftCollapsed(false)}>展开</button>
              <button type="button" onClick={() => { setDraft(''); setDraftCollapsed(false) }}>移除</button>
            </>
          )}
        </div>
      <textarea
        ref={draftTextareaRef}
        className={draftCollapsed ? 'is-collapsed' : ''}
        value={draftCollapsed ? '' : draft}
        readOnly={draftCollapsed}
        onChange={(e) => updateDraftText(e.target.value)}
        onPaste={handleDraftPaste}
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
      />
      {toolNotice && <div className="composer-notice">{toolNotice}</div>}
      <div className="composer-toolbar" aria-label="输入工具栏">
        <div className="composer-left">
          <div className="composer-menu-wrapper">
            <button
              className={`composer-tool-btn${activeComposerMenu === 'attach' ? ' active' : ''}`}
              type="button"
              onClick={() => setActiveComposerMenu((current) => (current === 'attach' ? null : 'attach'))}
              disabled={isSending}
              title="添加附件"
              aria-label="添加附件"
            >
              <Paperclip size={17} />
            </button>
            {activeComposerMenu === 'attach' && (
              <div className="composer-popover attach-menu">
                <button type="button" onClick={pickLocalFiles}>
                  <FileText size={15} />
                  <span>
                    <strong>文件</strong>
                    <em>文档、图片、视频</em>
                  </span>
                </button>
                <button type="button" onClick={pickLocalFiles}>
                  <Paperclip size={15} />
                  <span>
                    <strong>照片或视频</strong>
                    <em>从本地选择</em>
                  </span>
                </button>
              </div>
            )}
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
              className={`composer-tool-btn${activeComposerMenu === 'model' ? ' active' : ''}`}
              type="button"
              onClick={() => setActiveComposerMenu((current) => (current === 'model' ? null : 'model'))}
              title="模型选择"
              aria-label="模型选择"
            >
              <Infinity size={18} />
            </button>
            {activeComposerMenu === 'model' && (
              <div className="composer-popover choice-menu">
                {MODEL_OPTIONS.map((option) => (
                  <button
                    className={selectedModel === option.id ? 'active' : ''}
                    type="button"
                    key={option.id}
                    onClick={() => {
                      setSelectedModel(option.id)
                      setActiveComposerMenu(null)
                      setToolNotice(`${option.label} 已启用`)
                    }}
                  >
                    <span>
                      <strong>{option.label}</strong>
                      <em>{option.note}</em>
                    </span>
                    {selectedModel === option.id && <Check size={14} />}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="composer-menu-wrapper">
            <button
              className={`composer-tool-btn${activeComposerMenu === 'persona' || activeConversationMode !== 'auto' ? ' active' : ''}`}
              type="button"
              onClick={() => setActiveComposerMenu((current) => (current === 'persona' ? null : 'persona'))}
              title="人格模型"
              aria-label="人格模型"
            >
              <UserRoundCog size={17} />
            </button>
            {activeComposerMenu === 'persona' && (
              <div className="composer-popover choice-menu persona-menu">
                <p className="composer-menu-section-label">快捷人格</p>
                {PERSONA_OPTIONS.map((option) => (
                  <button
                    className={activeConversationMode === option.mode ? 'active' : ''}
                    type="button"
                    key={option.id}
                    onClick={() => {
                      void (async () => {
                        setActiveComposerMenu(null)
                        if (data.status.adapter === 'local') {
                          try {
                            const result = await switchLocalMode(option.mode)
                            setSelectedPersona(option.id)
                            setToolNotice(`已切换到 ${result.label}`)
                            await onRefresh?.()
                            return
                          } catch (error) {
                            setToolNotice(error instanceof Error ? error.message : '模式切换失败')
                            return
                          }
                        }
                        setSelectedPersona(option.id)
                        setToolNotice(`${option.label} 已选择（连接本地后可写入模式）`)
                      })()
                    }}
                  >
                    <span>
                      <strong>{option.label}</strong>
                      <em>{option.note}</em>
                    </span>
                    {activeConversationMode === option.mode && <Check size={14} />}
                  </button>
                ))}
                {morePersonaModes.length > 0 && (
                  <>
                    <p className="composer-menu-section-label">全部姿态</p>
                    {morePersonaModes.map((mode) => (
                      <button
                        className={activeConversationMode === mode.id ? 'active' : ''}
                        type="button"
                        key={mode.id}
                        onClick={() => {
                          void (async () => {
                            setActiveComposerMenu(null)
                            if (data.status.adapter === 'local') {
                              try {
                                const result = await switchLocalMode(mode.id)
                                setSelectedPersona(personaIdFromMode(mode.id))
                                setToolNotice(`已切换到 ${result.label}`)
                                await onRefresh?.()
                                return
                              } catch (error) {
                                setToolNotice(error instanceof Error ? error.message : '模式切换失败')
                                return
                              }
                            }
                            setToolNotice(`${mode.label} 已选择（连接本地后可写入模式）`)
                          })()
                        }}
                      >
                        <span>
                          <strong>{mode.label}</strong>
                          <em>{mode.id}</em>
                        </span>
                        {activeConversationMode === mode.id && <Check size={14} />}
                      </button>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>
        </div>
        <div className="composer-right">
          <button
            className={`composer-background${isBackgrounding ? ' active' : ''}`}
            type="button"
            onClick={() => void sendBackgroundJob()}
            disabled={isSending || isBackgrounding || data.status.adapter !== 'local' || !draft.trim()}
            title="后台执行"
            aria-label="后台执行"
          >
            {isBackgrounding ? <Loader2 size={15} /> : <CornerDownLeft size={15} />}
          </button>
          <button
            className={`send-btn composer-send${draft.trim() ? ' active' : ''}${isSending ? ' stopping' : ''}`}
            type="button"
            onClick={isSending ? stopSending : sendMessage}
            disabled={!isSending && !draft.trim()}
            title={isSending ? '停止并撤回本轮' : '发送'}
          >
            {isSending ? <X size={15} /> : <ArrowUp size={15} />}
          </button>
        </div>
      </div>
    </div>
  )

  if (isHome) {
    return (
      <div className="chat-home">
        <div className="home-centerpiece">
          <ArcherRing large />
          <p className="home-title">今天怎么样？</p>
          {sessionLoadState === 'loading' && <div className="session-source-banner">读取会话中…</div>}
          {sessionLoadState === 'error' && <div className="session-source-banner warning">{sessionLoadError || '会话读取失败'}</div>}
          {chatError && <div className="chat-error">{chatError}</div>}
          {composerEl}
        </div>
      </div>
    )
  }

  return (
    <div className="chat-layout">
      <div className="conversation">
        {activeSession && (
          <div className="session-source-banner">
            <span>已恢复历史会话</span>
            <strong>{activeSession.title}</strong>
            <em>{activeSession.date} · {activeSession.turns} 轮 · 继续发送会续写当前会话</em>
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
                <div className={`message-bubble${message.role === 'assistant' && !message.text.trim() && isTyping ? ' typing-brand' : ''}`}>
                  {message.role === 'assistant' && !message.text.trim() && isTyping ? (
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

        {toolEvents.filter((event) => {
          // 隐藏信息检索类工具卡片（记忆、搜索、文件引用），只保留需要用户交互的
          const lowInterest = ['obsidian_search', 'obsidian_read', 'memory.retrieve', 'memory-retrieve', 'file.reference', 'hugo_blog']
          return !lowInterest.includes(event.name) || event.requiresApproval
        }).map((event) => {
          // Derive decision from runtimeState.toolResults (single source of truth for approvals)
          const toolResult = runtimeState.toolResults[event.id]
          const decision = toolResult?.decision
          return (
            <ToolEventCard
              key={event.id}
              event={event}
              decision={decision}
              onDecide={(nextDecision) => decideTool(event.id, nextDecision)}
            />
          )
        })}

        {/* Pending approvals from runtime state — ensures approval cards survive page refresh / eventLog restore */}
        {runtimeState.pendingApprovals
          .filter((req) => !toolEvents.some((e) => e.id === req.id))
          .map((req) => {
            const toolResult = runtimeState.toolResults[req.id]
            const decision = toolResult?.decision
            const syntheticEvent = toolEventFromRuntimeRequest(req)
            return (
              <ToolEventCard
                key={req.id}
                event={syntheticEvent}
                decision={decision}
                onDecide={(nextDecision) => decideTool(req.id, nextDecision)}
              />
            )
          })}

        {chatError && <div className="chat-error">{chatError}</div>}
        <div ref={bottomRef} />
      </div>

      <div className="conversation-divider" />
      {composerEl}
    </div>
  )
}

function restoreRuntimeState(sessionId: string, eventLog: EventLog | null) {
  const state = createInitialRuntimeState(sessionId)
  if (!eventLog) return state
  return eventLog
    .forSession(sessionId)
    .reduce((current, event) => reduceRuntimeEvent(current, event), state)
}

/** Convert a runtime ToolRequestEvent to display-friendly ToolEvent for ToolEventCard rendering */
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
        <em>{jobStatusLabel(job.status)}</em>
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

function ToolEventCard({
  event,
  decision,
  onDecide
}: {
  event: ToolEvent
  decision?: 'approved' | 'denied'
  onDecide: (decision: 'approved' | 'denied') => void
}) {
  const needsApproval = Boolean(event.requiresApproval && !decision)
  const kind = toolKind(event)
  let Icon = FileText
  if (kind === 'shell') Icon = Terminal
  else if (kind === 'github') Icon = Github
  else if (kind === 'publish') Icon = Send
  const [expanded, setExpanded] = React.useState(false)

  return (
    <article className={`tool-event-card ${event.status} ${kind} risk-${event.risk} ${expanded ? 'expanded' : 'collapsed'}`}>
      <button className="tool-event-summary" type="button" onClick={() => setExpanded((value) => !value)}>
        <Icon size={14} />
        <span>{toolCompactText(event, kind)}</span>
        <em>{statusLabel(event.status, needsApproval)}</em>
        <ChevronDown size={13} />
      </button>

      {needsApproval && (
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
          <ToolEventBody event={event} kind={kind} />
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

function ToolEventBody({ event, kind }: { event: ToolEvent; kind: 'shell' | 'github' | 'file' | 'publish' }) {
  const output = event.detail.startsWith('output: ') ? event.detail.slice(8) : ''

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
        {event.status === 'blocked' && event.detail && <span>{event.detail}</span>}
      </div>
    )
  }

  return (
    <div className="tool-path-block">
      <strong>{event.draft?.path || event.detail || event.name}</strong>
      {event.draft?.contentPreview && <span>{event.draft.contentPreview}</span>}
      {!event.draft?.contentPreview && event.detail && <span>{event.detail}</span>}
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
  if (event.name === 'shell' || event.name === 'shell.execute') return 'Shell 命令'
  if (event.name === 'github' || event.name === 'github_ops') return 'GitHub 操作'
  if (event.name === 'hugo_blog') return '博客发布'
  if (event.name === 'file.reference') return '本地文件引用'
  if (event.name.includes('obsidian')) return 'Obsidian 写入'
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

function jobStatusLabel(status: JobEvent['status']): string {
  if (status === 'queued') return '等待中'
  if (status === 'running') return '执行中'
  if (status === 'waiting_approval') return '等待确认'
  if (status === 'complete') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'cancelled') return '已取消'
  return status
}

function backgroundRouteReasonLabel(reason: string): string {
  if (reason === 'large request') return '内容较长，适合后台持续处理'
  if (reason === 'implementation-style request') return '这是实现/修改类任务，适合后台执行'
  return '适合后台执行'
}

function formatFileSize(size?: number): string {
  if (!size) return '未知大小'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
