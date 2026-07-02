import React from 'react'
import ReactDOM from 'react-dom/client'
import {
  Brain,
  ChevronRight,
  Folder,
  FolderPlus,
  MessageSquare,
  PanelLeft,
  SquarePen,
  UserRoundCog,
  Wrench,
  X,
} from 'lucide-react'
import { fetchLocalExpertWorkbench, loadLocalSession, switchLocalExpert } from './adapters/localArcher'
import { connectionStatusLabel, expertShortLabel, modelProfileShortLabel } from './lib/conversationPersona'
import { mergeInitiativeShadowEvent } from './lib/initiativeShadow'
import { createOfflineLocalShell, syncBrainData, wasBrainEverLinked } from './lib/brainConnection'
import { useConnectionState, type ConnectionStateSnapshot } from './lib/useConnectionState'
import { ConnectionBadge } from './components/ConnectionBadge'
import { mockArcher } from './adapters/mockArcher'
import { ArcherRing, ErrorBoundary } from './components/common'
import { ChatPage } from './pages/ChatPage'
import { MemoryPage } from './pages/MemoryPage'
import { ReviewPage } from './pages/ReviewPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { SettingsPage } from './pages/SettingsPage'
import { SkillsPage } from './pages/SkillsPage'
import { SoulPage } from './pages/SoulPage'
import { TasksPage } from './pages/TasksPage'
import { TodayPage } from './pages/TodayPage'
import type {
  ArcherAdapter,
  ApiConnectionState,
  ConversationMode,
  MemoryContextMode,
  ObsidianContextMode,
  Route,
  SavedSession,
  SessionDetail,
  Theme
} from './types'
import {
  buildSidebarTaskGroups,
  createSidebarProject,
  readSidebarProjects,
  writeSidebarProjects,
  type ProjectRecord,
} from './lib/sidebarProjects'
import type { InitiativeEvent } from '../../agent/contracts'
import './styles.css'

function App() {
  const [route, setRoute] = React.useState<Route>('Chat')
  const [sidebarOpen, setSidebarOpen] = React.useState(() => {
    const saved = localStorage.getItem('archer-sidebar-open')
    return saved === null ? true : saved === '1'
  })
  const [chatKey, setChatKey] = React.useState(0)
  const [data, setData] = React.useState<ArcherAdapter>(() => (
    wasBrainEverLinked() ? createOfflineLocalShell() : mockArcher
  ))
  const [apiState, setApiState] = React.useState<ApiConnectionState>('loading')
  const [apiReason, setApiReason] = React.useState('')
  const [apiBannerDismissed, setApiBannerDismissed] = React.useState(false)
  // L0.4: 崩溃恢复提示
  const [crashInfo, setCrashInfo] = React.useState<{
    isCrash: boolean
    reason: string
    crashCount: number
    lastTraceId: string | null
    startedAt: string | null
  } | null>(null)
  const [crashBannerDismissed, setCrashBannerDismissed] = React.useState(false)
  const [activeSession, setActiveSession] = React.useState<SessionDetail | null>(null)
  const [sessionLoadState, setSessionLoadState] = React.useState<'idle' | 'loading' | 'error'>('idle')
  const [sessionLoadError, setSessionLoadError] = React.useState('')
  const [profileOpen, setProfileOpen] = React.useState(false)
  const [projects, setProjects] = React.useState<ProjectRecord[]>(() => readSidebarProjects())
  const [selectedProjectId, setSelectedProjectId] = React.useState('')
  const [profileName] = React.useState(() => {
    return localStorage.getItem('archer-profile-name') || 'Archer'
  })
  const [profileAvatarUrl, setProfileAvatarUrl] = React.useState(() => {
    return localStorage.getItem('archer-profile-avatar-url') || ''
  })
  const [theme, setTheme] = React.useState<Theme>(() => {
    return (localStorage.getItem('archer-desktop-theme') as Theme) || 'light'
  })
  const [conversationMode, setConversationMode] = React.useState<ConversationMode>(() => {
    return (localStorage.getItem('archer-conversation-mode') as ConversationMode) || 'auto'
  })
  const [memoryMode, setMemoryMode] = React.useState<MemoryContextMode>(() => {
    return (localStorage.getItem('archer-memory-context') as MemoryContextMode) || 'conservative'
  })
  const [obsidianMode, setObsidianMode] = React.useState<ObsidianContextMode>(() => {
    return (localStorage.getItem('archer-obsidian-context') as ObsidianContextMode) || 'summary'
  })

  // L1.2.5：第 1 层连接状态机（5s 心跳 + 30s doctor + 1s tick）
  const connection = useConnectionState()

  function newChat() {
    setActiveSession(null)
    setSessionLoadState('idle')
    setSessionLoadError('')
    setChatKey((k) => k + 1)
    setRoute('Chat')
  }

  async function openSession(session: ArcherAdapter['sessions'][number]) {
    setRoute('Chat')
    setSessionLoadError('')
    if (data.status.adapter !== 'local' && !wasBrainEverLinked()) {
      setActiveSession({
        ...session,
        messages: [
          {
            id: 1,
            role: 'assistant',
            text: `这是「${session.title}」的示例会话。连接本地 API 后可以读取完整消息。`
          }
        ]
      })
      setSessionLoadState('idle')
      return
    }
    setActiveSession(null)
    setSessionLoadState('loading')
    try {
      const detail = await loadLocalSession(session.id)
      setActiveSession(detail)
      setSessionLoadState('idle')
      if (
        detail.expertId
        && detail.expertId !== (data.experts?.current || data.status.expertId)
        && data.status.adapter === 'local'
      ) {
        try {
          await switchLocalExpert(detail.expertId)
          await patchExpertWorkbench()
        } catch {
          // Keep session readable even if expert restore fails.
        }
      }
    } catch (error) {
      setSessionLoadState('error')
      setSessionLoadError(error instanceof Error ? error.message : '无法读取这个历史会话')
    }
  }

  React.useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('archer-desktop-theme', theme)
  }, [theme])

  React.useEffect(() => {
    localStorage.setItem('archer-memory-context', memoryMode)
  }, [memoryMode])

  React.useEffect(() => {
    localStorage.setItem('archer-obsidian-context', obsidianMode)
  }, [obsidianMode])

  React.useEffect(() => {
    localStorage.setItem('archer-profile-name', profileName)
  }, [profileName])

  React.useEffect(() => {
    if (profileAvatarUrl) {
      localStorage.setItem('archer-profile-avatar-url', profileAvatarUrl)
    } else {
      localStorage.removeItem('archer-profile-avatar-url')
    }
  }, [profileAvatarUrl])

  React.useEffect(() => {
    localStorage.setItem('archer-conversation-mode', conversationMode)
  }, [conversationMode])

  React.useEffect(() => {
    localStorage.setItem('archer-sidebar-open', sidebarOpen ? '1' : '0')
  }, [sidebarOpen])

  const connectInFlightRef = React.useRef<Promise<void> | null>(null)

  async function connectLocalApi(options: { silent?: boolean } = {}) {
    if (connectInFlightRef.current) {
      await connectInFlightRef.current
      return
    }

    const run = (async () => {
      if (!options.silent) {
        setApiState('loading')
        setApiReason('')
      }
      const result = await syncBrainData({ previous: data, silent: options.silent })
      if (result.adapter) {
        setData(result.adapter)
        if (result.state === 'connected') {
          setConversationMode(result.adapter.modes.current || 'auto')
        }
      } else if (!wasBrainEverLinked()) {
        setData(mockArcher)
      }
      setApiState(result.state)
      setApiReason(result.reason || '')
      if (result.state === 'connected') {
        setApiBannerDismissed(false)
        // L0.4: 连接成功后读崩溃信息 (只读一次)
        try {
          const info = await window.archerDesktop?.getCrashInfo?.()
          if (info && info.isCrash) {
            setCrashInfo(info)
            setCrashBannerDismissed(false)
          }
        } catch {
          // getCrashInfo 失败不影响主流程
        }
      }
    })()

    connectInFlightRef.current = run
    try {
      await run
    } finally {
      if (connectInFlightRef.current === run) {
        connectInFlightRef.current = null
      }
    }
  }

  async function patchExpertWorkbench() {
    const snapshot = await fetchLocalExpertWorkbench()
    setData((current) => ({
      ...current,
      experts: snapshot.experts,
      status: {
        ...current.status,
        ...snapshot.status,
        adapter: 'local',
      },
      settings: {
        ...current.settings,
        activeExpert: snapshot.experts.current,
        experts: snapshot.experts.experts,
      },
    }))
  }

  function patchMemoryItems(memory: ArcherAdapter['memory']) {
    setData((current) => ({
      ...current,
      memory,
      status: {
        ...current.status,
        pendingMemoryCount: memory.filter((item) => item.status === 'pending').length,
        memoryCount: memory.filter((item) => item.status === 'confirmed').length,
      },
    }))
  }

  function handleInitiativeEvent(event: InitiativeEvent) {
    setData((current) => ({
      ...current,
      initiativeShadow: mergeInitiativeShadowEvent(current.initiativeShadow, event),
    }))
  }

  const pendingMemoryCount = data.memory.filter((m) => m.status === 'pending').length
  const sidebarTaskGroups = React.useMemo(() => buildSidebarTaskGroups(data.sessions, projects, data.threads), [data.sessions, projects, data.threads])

  const sidebarNavItems: Array<{ route: Route; icon: React.ElementType; label: string; touchCount?: number }> = [
    { route: 'Chat', icon: MessageSquare, label: '对话' },
    { route: 'Memory', icon: Brain, label: '记忆', touchCount: pendingMemoryCount || undefined },
    { route: 'Skills', icon: Wrench, label: '技能' },
    { route: 'Projects', icon: Folder, label: '项目' },
  ]

  function createProject() {
    const nextProjects = writeSidebarProjects(createSidebarProject(projects, '新项目'))
    setProjects(nextProjects)
    const nextProject = nextProjects[nextProjects.length - 1]
    setSelectedProjectId(nextProject?.id || '')
    setRoute('Projects')
  }

  function buildSessionDetailFromSave(messages: SessionDetail['messages'], savedSession: SavedSession): SessionDetail {
    const firstUser = messages.find((message) => message.role === 'user')?.text.trim().replace(/\s+/g, ' ') || savedSession.id
    return {
      id: savedSession.id,
      title: firstUser.slice(0, 42),
      date: savedSession.id.slice(0, 8),
      turns: Math.max(1, Math.floor(messages.filter((message) => message.role !== 'system').length / 2)),
      tone: 'saved',
      threadId: savedSession.threadId,
      messages,
    }
  }

  function upsertSavedSessionSnapshot(messages: SessionDetail['messages'], savedSession: SavedSession) {
    const detail = buildSessionDetailFromSave(messages, savedSession)
    setData((current) => {
      const sessionItem = {
        id: detail.id,
        title: detail.title,
        date: detail.date,
        turns: detail.turns,
        tone: detail.tone,
        threadId: detail.threadId,
        preview: messages.find((message) => message.role === 'user')?.text.slice(0, 60),
      }
      const nextSessions = current.sessions.some((session) => session.id === detail.id)
        ? current.sessions.map((session) => session.id === detail.id ? { ...session, ...sessionItem } : session)
        : [sessionItem, ...current.sessions]
      if (!detail.threadId) {
        return { ...current, sessions: nextSessions }
      }
      const summary = summarizeThreadMessages(messages)
      const existingThread = current.threads.find((thread) => thread.id === detail.threadId)
      const thread = {
        id: detail.threadId,
        title: existingThread?.title || detail.title,
        summary,
        createdAt: existingThread?.createdAt || new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        sessionIds: Array.from(new Set([...(existingThread?.sessionIds || []), detail.id])),
        projectId: existingThread?.projectId,
        archived: existingThread?.archived,
      }
      return {
        ...current,
        sessions: nextSessions,
        threads: existingThread
          ? current.threads.map((item) => item.id === thread.id ? thread : item)
          : [thread, ...current.threads],
      }
    })
  }

  React.useEffect(() => {
    const timer = setTimeout(() => { void connectLocalApi() }, 200)
    return () => clearTimeout(timer)
  }, [])

  React.useEffect(() => {
    if (apiState === 'connected' || apiState === 'loading') return
    const timer = setInterval(() => { void connectLocalApi({ silent: true }) }, 3000)
    return () => clearInterval(timer)
  }, [apiState])

  React.useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
        event.preventDefault()
        newChat()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])


  return (
    <div className={`app-shell ${sidebarOpen ? 'has-sidebar' : 'focus-mode'}`}>
      <div className="window-drag-strip" aria-hidden="true" />
      <div className="app-title-tools" aria-label="窗口工具">
        <button
          type="button"
          aria-label={sidebarOpen ? '收起侧边栏' : '打开侧边栏'}
          onMouseDown={(event) => {
            event.stopPropagation()
          }}
          onClick={() => setSidebarOpen((value) => !value)}
          title={sidebarOpen ? '收起侧边栏' : '打开侧边栏'}
          className={`app-title-button${sidebarOpen ? ' active' : ''}`}
        >
          <PanelLeft size={18} />
        </button>
        <button
          className="app-title-button"
          type="button"
          onMouseDown={(event) => {
            event.stopPropagation()
          }}
          onClick={newChat}
          title="新建对话"
        >
          <SquarePen size={18} />
        </button>
      </div>

      {/* ── Sidebar ── */}
      <aside className={`sidebar ${sidebarOpen ? '' : 'closed'}`}>
        <div className="sidebar-head">
          <button className="sidebar-brand" type="button" onClick={newChat} title="新建对话">
            <ArcherRing living />
            <span className="sidebar-brand-wordmark" aria-label="Archer">
              {['A', 'r', 'c', 'h', 'e', 'r'].map((letter, index) => (
                <span aria-hidden="true" key={`${letter}-${index}`}>{letter}</span>
              ))}
            </span>
          </button>
        </div>

        <div className="sidebar-body">
          <nav className="sidebar-main-nav" aria-label="主导航">
            {sidebarNavItems.map((item) => {
              const Icon = item.icon
              return (
                <button
                  key={item.route}
                  className={`sidebar-nav-item ${route === item.route ? 'active' : ''}`}
                  type="button"
                  onClick={() => setRoute(item.route)}
                >
                  <Icon size={17} />
                  <span>
                    <strong>{item.label}</strong>
                  </span>
                  {Boolean(item.touchCount) && <small className="sidebar-nav-badge">{item.touchCount}</small>}
                </button>
              )
            })}
          </nav>

          <section className="sidebar-task-list" aria-label="任务列表">
            <div className="sidebar-list-head">
              <span>任务列表</span>
              <small>{sidebarTaskGroups.unassignedThreads.length}</small>
            </div>
            <div className="sidebar-rows">
              {sidebarTaskGroups.unassignedThreads.map((thread) => (
                <button
                  key={thread.id}
                  className={`sidebar-session-row ${thread.id === activeSession?.threadId || thread.sessionIds.includes(activeSession?.id || '') ? 'active' : ''}`}
                  type="button"
                  onClick={() => void openSession(thread.latestSession)}
                  title={thread.title}
                >
                  <span>{thread.title}</span>
                  <em>{thread.sessions.length > 1 ? `${thread.sessions.length} 次` : thread.date}</em>
                </button>
              ))}
              {!sidebarTaskGroups.unassignedThreads.length && (
                <p className="sidebar-empty-hint">没有未归属项目的对话</p>
              )}
            </div>
          </section>

          <section className="sidebar-project-list" aria-label="项目文件夹">
            <div className="sidebar-list-head">
              <span>文件夹</span>
              <button type="button" onClick={createProject} title="创建项目" aria-label="创建项目">
                <FolderPlus size={14} />
              </button>
            </div>
            <div className="sidebar-rows">
              {projects.map((project) => (
                <button
                  key={project.id}
                  className={`sidebar-project-row ${route === 'Projects' && selectedProjectId === project.id ? 'active' : ''}`}
                  type="button"
                  onClick={() => {
                    setSelectedProjectId(project.id)
                    setRoute('Projects')
                  }}
                  title={project.name}
                >
                  <Folder size={15} />
                  <span>{project.name}</span>
                  <em>{project.threadIds.length || project.sessionIds.length}</em>
                </button>
              ))}
              {!projects.length && (
                <button className="sidebar-project-empty" type="button" onClick={createProject}>
                  <FolderPlus size={15} />
                  创建项目
                </button>
              )}
            </div>
          </section>
        </div>

        <footer className="sidebar-footer">
          {apiState !== 'connected' && apiState !== 'loading' && !apiBannerDismissed && (
            <div className="api-error" role="status">
              <span>
                <strong>本地 API 未连接</strong>
                <em>{apiReason || '需要启动本地 API'}</em>
              </span>
              <button type="button" onClick={() => setApiBannerDismissed(true)} title="隐藏连接提示">
                隐藏连接提示
              </button>
            </div>
          )}
          {connection.state !== 'ready' && (
            <ConnectionBadge
              state={connection.state}
              reason={connection.snapshot.degradedReason}
              deadReason={connection.snapshot.deadReason}
              size="footer"
              onClick={connection.state === 'dead' ? connection.recover : connection.refresh}
            />
          )}
          <button
            type="button"
            className="profile-footer"
            onClick={() => setProfileOpen((open) => !open)}
            title="个人中心"
          >
            <ProfileAvatar avatarUrl={profileAvatarUrl} size="footer" />
            <span className="profile-footer-copy">
              <strong>{profileName}</strong>
              <em>{connection.badge.label}</em>
            </span>
          </button>
          {profileOpen && (
            <ProfilePanel
              data={data}
              apiState={apiState}
              profileName={profileName}
              profileAvatarUrl={profileAvatarUrl}
              setProfileAvatarUrl={setProfileAvatarUrl}
              theme={theme}
              setTheme={setTheme}
              onClose={() => setProfileOpen(false)}
              onNavigate={(nextRoute) => {
                setRoute(nextRoute)
                setProfileOpen(false)
              }}
            />
          )}
        </footer>
      </aside>

      {/* ── Main workspace ── */}
      <main className="workspace">
        <section className="page-frame">
          {/* L0.4: 崩溃恢复提示 banner */}
          {crashInfo && crashInfo.isCrash && !crashBannerDismissed && (
            <div className="crash-banner" role="status">
              <span>
                <strong>Archer 上次未正常退出</strong>
                <em>
                  {crashInfo.crashCount >= 3
                    ? `近期已异常退出 ${crashInfo.crashCount} 次，建议检查日志`
                    : `原因：${crashReasonLabel(crashInfo.reason)}`}
                </em>
              </span>
              <button
                type="button"
                onClick={() => setCrashBannerDismissed(true)}
                title="关闭提示"
              >
                知道了
              </button>
            </div>
          )}
          {route === 'Chat' && (
            <ChatPage
              key={chatKey}
              data={data}
              memoryMode={memoryMode}
              obsidianMode={obsidianMode}
              activeSession={activeSession}
              sessionLoadState={sessionLoadState}
              sessionLoadError={sessionLoadError}
              resetRuntimeOnMount={chatKey > 0 && !activeSession}
              connectionState={connection.state}
              connectionDeadReason={connection.snapshot.deadReason}
              connectionActions={{
                start: connection.start,
                recover: connection.recover,
                quit: connection.quit,
                refresh: connection.refresh,
              }}
              onNavigate={setRoute}
              onInitiativeEvent={handleInitiativeEvent}
              onRefresh={connectLocalApi}
              onExpertSwitch={patchExpertWorkbench}
              onSessionAppended={(messages, savedSession) => {
                if (savedSession) upsertSavedSessionSnapshot(messages, savedSession)
                setActiveSession((current) => {
                  if (current) {
                    return {
                      ...current,
                      threadId: savedSession?.threadId || current.threadId,
                      messages,
                      turns: Math.max(1, Math.floor(messages.filter((message) => message.role !== 'system').length / 2)),
                    }
                  }
                  return savedSession ? buildSessionDetailFromSave(messages, savedSession) : current
                })
              }}
            />
          )}
          {route === 'Sessions' && (
            <ReviewPage
              data={data}
              onRefresh={connectLocalApi}
              onOpenSession={openSession}
              onNavigate={setRoute}
              onMemoryItemsChange={patchMemoryItems}
            />
          )}
          {route === 'Today' && <TodayPage data={data} onRefresh={connectLocalApi} />}
          {route === 'Tasks' && <TasksPage data={data} />}
          {route === 'Memory' && <MemoryPage
            data={data}
            onRefresh={connectLocalApi}
            onMemoryItemsChange={patchMemoryItems}
          />}
          {route === 'Skills' && <SkillsPage data={data} onRefresh={connectLocalApi} />}
          {route === 'Projects' && (
            <ProjectsPage
              data={data}
              projects={projects}
              selectedProjectId={selectedProjectId}
              onProjectsChange={setProjects}
              onProjectSelect={setSelectedProjectId}
              onOpenSession={(session) => void openSession(session)}
              onCreateProject={createProject}
            />
          )}
          {route === 'Soul' && <SoulPage data={data} onRefresh={connectLocalApi} />}
          {route === 'Settings' && (
            <SettingsPage
              data={data}
              theme={theme}
              setTheme={setTheme}
              memoryMode={memoryMode}
              setMemoryMode={setMemoryMode}
              obsidianMode={obsidianMode}
              setObsidianMode={setObsidianMode}
              conversationMode={conversationMode}
              setConversationMode={setConversationMode}
              connectionState={connection.state}
              connectionDeadReason={connection.snapshot.deadReason}
              connectionActions={{
                start: connection.start,
                recover: connection.recover,
                quit: connection.quit,
                refresh: connection.refresh,
              }}
              onRefresh={connectLocalApi}
              onNavigate={setRoute}
            />
          )}
        </section>
      </main>
    </div>
  )
}

function summarizeThreadMessages(messages: SessionDetail['messages']): string {
  const firstUser = messages.find((message) => message.role === 'user')?.text.trim()
  const recentUser = [...messages].reverse().find((message) => message.role === 'user')?.text.trim()
  const recentAssistant = [...messages].reverse().find((message) => message.role === 'assistant')?.text.trim()
  const parts: string[] = []
  if (firstUser) parts.push(`目标：${compactSummaryText(firstUser, 120)}`)
  if (recentUser && recentUser !== firstUser) parts.push(`最近问题：${compactSummaryText(recentUser, 120)}`)
  if (recentAssistant) parts.push(`最近结论：${compactSummaryText(recentAssistant, 180)}`)
  return parts.join('\n')
}

function compactSummaryText(value: string, limit: number): string {
  return value.replace(/\s+/g, ' ').trim().slice(0, limit)
}

/** L0.4: 崩溃原因转中文标签. */
function crashReasonLabel(reason: string): string {
  const map: Record<string, string> = {
    no_exit_status_and_heartbeat_stale: '进程意外终止',
    sigterm: '收到退出信号',
    crash: '崩溃',
    unclean_exit: '异常退出',
    init_failed: '初始化失败',
  }
  return map[reason] || reason
}

function ProfileAvatar({ avatarUrl, size = 'menu' }: { avatarUrl: string; size?: 'menu' | 'footer' }) {
  if (avatarUrl) {
    return <img className={`profile-avatar profile-avatar-${size}`} src={avatarUrl} alt="" />
  }
  return <ArcherRing living />
}

function ProfilePanel({
  data,
  apiState,
  profileName,
  profileAvatarUrl,
  setProfileAvatarUrl,
  theme,
  setTheme,
  onClose,
  onNavigate
}: {
  data: ArcherAdapter
  apiState: ApiConnectionState
  profileName: string
  profileAvatarUrl: string
  setProfileAvatarUrl: (value: string) => void
  theme: Theme
  setTheme: (value: Theme) => void
  onClose: () => void
  onNavigate: (route: Route) => void
}) {
  const avatarInputRef = React.useRef<HTMLInputElement>(null)
  const statusText = connectionStatusLabel(apiState, data.status.adapter === 'local')
  const expertText = expertShortLabel(
    data.experts?.current || data.status.expertId,
    data.experts?.experts ?? [],
    data.status.expertLabel,
  )
  const modelText = modelProfileShortLabel(data.settings.activeProfile || data.status.modelProfile)
  const themeLabel = theme === 'dark' ? '深色' : '亮色'

  function openSettings(tab: 'model' | 'context' | 'local' | 'appearance' | 'schedules' | 'diagnostics' = 'model') {
    sessionStorage.setItem('archer-settings-tab', tab)
    onNavigate('Settings')
  }

  function chooseAvatar(file: File | undefined) {
    if (!file || !file.type.startsWith('image/')) return
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        setProfileAvatarUrl(reader.result)
      }
    }
    reader.readAsDataURL(file)
  }

  return (
    <aside className="profile-panel">
      <div className="profile-menu-head">
        <ProfileAvatar avatarUrl={profileAvatarUrl} />
        <div className="profile-menu-identity">
          <strong>{profileName}</strong>
          <span>{expertText}</span>
        </div>
        <span className="profile-menu-pill">{modelText}</span>
        <button className="icon-button" type="button" onClick={onClose} aria-label="关闭个人中心">
          <X size={15} />
        </button>
      </div>

      <input
        ref={avatarInputRef}
        className="profile-avatar-input"
        type="file"
        accept="image/*"
        onChange={(event) => chooseAvatar(event.currentTarget.files?.[0])}
      />

      <button className="profile-account-card" type="button" onClick={() => avatarInputRef.current?.click()}>
        <UserRoundCog size={16} />
        <span>
          <strong>个人资料</strong>
          <em>修改头像与昵称</em>
        </span>
        <ChevronRight size={15} />
      </button>

      <div className="profile-menu-section">
        <button className="profile-menu-item" type="button" onClick={() => openSettings('local')}>
          <span>管理账号</span>
          <ChevronRight size={16} />
        </button>
      </div>

      <div className="profile-menu-section">
        <button className="profile-menu-item" type="button" onClick={() => openSettings('appearance')}>
          <span>语言</span>
          <strong>简体中文</strong>
          <ChevronRight size={16} />
        </button>
        <button className="profile-menu-item" type="button" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
          <span>主题</span>
          <strong>{themeLabel}</strong>
          <ChevronRight size={16} />
        </button>
        <button className="profile-menu-item" type="button" onClick={() => openSettings('model')}>
          <span>设置</span>
          <ChevronRight size={16} />
        </button>
        <button className="profile-menu-item" type="button" onClick={() => openSettings('diagnostics')}>
          <span>报告问题</span>
          <ChevronRight size={16} />
        </button>
      </div>

      <div className="profile-menu-status">
        <span>{statusText}</span>
        <span>记忆 {data.status.memoryCount}</span>
      </div>
    </aside>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)
