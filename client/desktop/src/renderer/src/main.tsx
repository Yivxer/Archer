import React from 'react'
import ReactDOM from 'react-dom/client'
import {
  Brain,
  ChevronRight,
  History,
  ListChecks,
  Layers,
  Moon,
  MessageSquare,
  PanelLeft,
  Settings,
  SquarePen,
  Sun,
  X,
} from 'lucide-react'
import { checkLocalApiHealth, getDesktopApiToken, loadLocalArcher, loadLocalSession } from './adapters/localArcher'
import { connectionStatusLabel, modeLabelFromId, modelLabelFromStatus, personaPresetFromMode } from './lib/conversationPersona'
import { mockArcher } from './adapters/mockArcher'
import { ArcherRing, EmptyDetail, ErrorBoundary, SearchBox } from './components/common'
import { ChatPage } from './pages/ChatPage'
import { MemoryPage } from './pages/MemoryPage'
import { SettingsPage } from './pages/SettingsPage'
import { SkillsPage } from './pages/SkillsPage'
import { SoulPage } from './pages/SoulPage'
import { TasksPage } from './pages/TasksPage'
import type {
  ArcherAdapter,
  ApiConnectionState,
  ConversationMode,
  MemoryContextMode,
  ObsidianContextMode,
  Route,
  SessionDetail,
  Theme
} from './types'
import './styles.css'

function App() {
  const [route, setRoute] = React.useState<Route>('Chat')
  const [sidebarOpen, setSidebarOpen] = React.useState(() => {
    const saved = localStorage.getItem('archer-sidebar-open')
    return saved === null ? true : saved === '1'
  })
  const [chatKey, setChatKey] = React.useState(0)
  const [data, setData] = React.useState<ArcherAdapter>(mockArcher)
  const [apiState, setApiState] = React.useState<ApiConnectionState>('idle')
  const [apiBannerDismissed, setApiBannerDismissed] = React.useState(false)
  const [activeSession, setActiveSession] = React.useState<SessionDetail | null>(null)
  const [sessionLoadState, setSessionLoadState] = React.useState<'idle' | 'loading' | 'error'>('idle')
  const [sessionLoadError, setSessionLoadError] = React.useState('')
  const [profileOpen, setProfileOpen] = React.useState(false)
  const [profileName, setProfileName] = React.useState(() => {
    return localStorage.getItem('archer-profile-name') || 'Archer'
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
    if (data.status.adapter !== 'local') {
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
    localStorage.setItem('archer-conversation-mode', conversationMode)
  }, [conversationMode])

  React.useEffect(() => {
    localStorage.setItem('archer-sidebar-open', sidebarOpen ? '1' : '0')
  }, [sidebarOpen])

  async function connectLocalApi() {
    setApiState('loading')
    try {
      const ensured = await window.archerDesktop?.ensureApi?.()
      if (ensured && !ensured.ok) {
        if (ensured.reason === 'token_mismatch') {
          setApiState(getDesktopApiToken() ? 'bad_token' : 'missing_token')
          return
        }
        if (ensured.reason === 'missing_python') {
          setApiState('error')
          return
        }
        setApiState('api_offline')
        return
      }
      const adapter = await loadLocalArcher()
      setData(adapter)
      setConversationMode(adapter.modes.current || 'auto')
      setApiState('connected')
    } catch (error) {
      setData((current) => (current.status.adapter === 'local' ? current : mockArcher))
      const message = error instanceof Error ? error.message : ''
      if (message.includes('[unauthorized]')) setApiState(getDesktopApiToken() ? 'bad_token' : 'missing_token')
      else if (message.includes('[missing_token]')) setApiState('missing_token')
      else if (message.includes('[network]')) setApiState('api_offline')
      else setApiState('error')
    }
  }

  const pendingMemoryCount = data.memory.filter((m) => m.status === 'pending').length

  const sidebarNavItems: Array<{ route: Route; icon: React.ElementType; label: string; hint: string; touchCount?: number }> = [
    { route: 'Chat', icon: MessageSquare, label: '对话', hint: activeSession ? '查看中' : '' },
    { route: 'Sessions', icon: History, label: '会话', hint: `${data.sessions.length} 条` },
    { route: 'Tasks', icon: ListChecks, label: '任务', hint: data.status.adapter === 'local' ? '后台' : '' },
    { route: 'Memory', icon: Brain, label: '记忆', hint: `${pendingMemoryCount ? `${pendingMemoryCount} 待确认 · ` : ''}${data.memory.filter((m) => m.status === 'confirmed').length} 已保存`, touchCount: pendingMemoryCount || undefined },
    { route: 'Soul', icon: Layers, label: 'Soul', hint: '人格档案' },
    { route: 'Settings', icon: Settings, label: '设置', hint: '' },
  ]

  React.useEffect(() => {
    const timer = setTimeout(connectLocalApi, 800)
    return () => clearTimeout(timer)
  }, [])

  React.useEffect(() => {
    setApiBannerDismissed(false)
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

  const showApiError = (apiState === 'bad_token' || apiState === 'error' || apiState === 'api_offline' || apiState === 'missing_token') && !apiBannerDismissed

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

        <div className="sidebar-body" aria-label="主导航">
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
                  <em>{item.hint}</em>
                </span>
                                {Boolean(item.touchCount) && <small className="sidebar-nav-badge">{item.touchCount}</small>}
              </button>
            )
          })}
        </div>

        <footer className="sidebar-footer">
          <button
            type="button"
            className="profile-footer"
            onClick={() => setProfileOpen((open) => !open)}
            title="连接与模型状态"
          >
            <span>
              <strong>{connectionStatusLabel(apiState, data.status.adapter === 'local')}</strong>
              <em>
                {modelLabelFromStatus(data.status.model)}
                {' · '}
                {modeLabelFromId(data.status.mode || data.modes.current, data.modes.modes)}
              </em>
            </span>
            <span className={`conn-dot ${apiState === 'connected' ? 'live' : ''}`} aria-hidden="true" />
          </button>
        </footer>
      </aside>

      {/* ── Main workspace ── */}
      <main className="workspace">
        <section className="page-frame">
          {showApiError && (
            <div className="api-error">
              <span>
                <strong>{apiStateLabel(apiState)}</strong>
                <em>{apiStateHelp(apiState)}</em>
              </span>
              <button type="button" onClick={connectLocalApi}>重试</button>
              <button type="button" onClick={() => setRoute('Settings')}>设置</button>
              <button type="button" onClick={() => setApiBannerDismissed(true)} aria-label="隐藏连接提示">
                <X size={13} />
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
              onNavigate={setRoute}
              onRefresh={connectLocalApi}
              onSessionAppended={(messages) => {
                setActiveSession((current) =>
                  current
                    ? { ...current, messages, turns: Math.max(1, Math.floor(messages.filter((message) => message.role !== 'system').length / 2)) }
                    : current
                )
              }}
            />
          )}
          {route === 'Sessions' && <SessionsPage data={data} onRefresh={connectLocalApi} onOpenSession={openSession} />}
          {route === 'Tasks' && <TasksPage data={data} />}
          {route === 'Memory' && <MemoryPage data={data} onRefresh={connectLocalApi} />}
          {route === 'Skills' && <SkillsPage data={data} onRefresh={connectLocalApi} />}
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
              apiState={apiState}
              onRefresh={connectLocalApi}
              onNavigate={setRoute}
            />
          )}
        </section>
        {profileOpen && (
          <ProfilePanel
            data={data}
            apiState={apiState}
            profileName={profileName}
            setProfileName={setProfileName}
            theme={theme}
            setTheme={setTheme}
            onClose={() => setProfileOpen(false)}
            onNavigate={(nextRoute) => {
              setRoute(nextRoute)
              setProfileOpen(false)
            }}
          />
        )}
      </main>
    </div>
  )
}

function ProfilePanel({
  data,
  apiState,
  profileName,
  setProfileName,
  theme,
  setTheme,
  onClose,
  onNavigate
}: {
  data: ArcherAdapter
  apiState: ApiConnectionState
  profileName: string
  setProfileName: (value: string) => void
  theme: Theme
  setTheme: (value: Theme) => void
  onClose: () => void
  onNavigate: (route: Route) => void
}) {
  const soulLoaded = Object.values(data.soulFiles).some((content) => content.trim().length > 0)
  const statusText = connectionStatusLabel(apiState, data.status.adapter === 'local')
  const modeText = modeLabelFromId(data.status.mode || data.modes.current, data.modes.modes)
  const personaNote = personaPresetFromMode(data.modes.current).label

  return (
    <aside className="profile-panel">
      <div className="panel-head">
        <div>
          <span className="panel-kicker">个人中心</span>
          <h2>本地 Archer</h2>
        </div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="关闭个人中心">
          <X size={15} />
        </button>
      </div>

      <label className="profile-field">
        <span>昵称</span>
        <input value={profileName} onChange={(event) => setProfileName(event.target.value)} placeholder="Archer 怎么称呼你？" />
      </label>

      <label className="profile-field">
        <span>邮箱</span>
        <input value={data.status.accountName || '本地模式未绑定邮箱'} readOnly aria-readonly />
      </label>

      <div className="profile-mode-row">
        <button className={theme === 'light' ? 'active' : ''} type="button" onClick={() => setTheme('light')}>
          <Sun size={14} />
          浅色
        </button>
        <button className={theme === 'dark' ? 'active' : ''} type="button" onClick={() => setTheme('dark')}>
          <Moon size={14} />
          深色
        </button>
      </div>

      <div className="profile-status-grid">
        <div>
          <span>连接</span>
          <strong>{statusText}</strong>
        </div>
        <div>
          <span>模型</span>
          <strong>{modelLabelFromStatus(data.status.model) || '未读取'}</strong>
        </div>
        <div>
          <span>姿态</span>
          <strong>{modeText}{data.modes.current === 'auto' ? '' : ` · ${personaNote}`}</strong>
        </div>
        <div>
          <span>记忆</span>
          <strong>{data.status.memoryCount}{data.status.pendingMemoryCount ? ` (+${data.status.pendingMemoryCount} 待确认)` : ''}</strong>
        </div>
      </div>

      <div className="panel-actions">
        <button type="button" onClick={() => onNavigate('Soul')}>
          <Layers size={14} />
          打开 Soul
        </button>
        <button type="button" onClick={() => onNavigate('Settings')}>
          <Settings size={14} />
          连接设置
        </button>
        <button type="button" onClick={() => onNavigate('Memory')}>
          <Brain size={14} />
          查看本地状态
        </button>
      </div>
    </aside>
  )
}

function apiStateLabel(apiState: ApiConnectionState, isLocal = false): string {
  return connectionStatusLabel(apiState, isLocal)
}

function apiStateHelp(apiState: ApiConnectionState): string {
  if (apiState === 'missing_token') return '在设置中填入本地 API 的连接口令。'
  if (apiState === 'bad_token') return '口令与终端启动参数不一致。'
  if (apiState === 'api_offline') return '点「重试」会自动从 ~/Projects/Archer 拉起大脑进程。'
  if (apiState === 'error') return '需要启动本地 API，或检查口令和模型配置。'
  return '大脑未连接，当前为示例数据。'
}

function SessionsPage({
  data,
  onRefresh,
  onOpenSession
}: {
  data: ArcherAdapter
  onRefresh: () => Promise<void>
  onOpenSession: (session: ArcherAdapter['sessions'][number]) => void
}) {
  const [selectedId, setSelectedId] = React.useState(data.sessions[0]?.id ?? '')
  const [detail, setDetail] = React.useState<SessionDetail | null>(null)
  const [detailState, setDetailState] = React.useState<'idle' | 'loading' | 'error'>('idle')
  const [query, setQuery] = React.useState('')

  React.useEffect(() => {
    setSelectedId(data.sessions[0]?.id ?? '')
    setDetail(null)
    setDetailState('idle')
  }, [data])

  React.useEffect(() => {
    if (!selectedId || data.status.adapter !== 'local') {
      setDetail(null)
      setDetailState('idle')
      return
    }
    let cancelled = false
    setDetailState('loading')
    loadLocalSession(selectedId)
      .then((value) => {
        if (cancelled) return
        setDetail(value)
        setDetailState('idle')
      })
      .catch(() => {
        if (cancelled) return
        setDetail(null)
        setDetailState('error')
      })
    return () => {
      cancelled = true
    }
  }, [selectedId, data.status.adapter])

  const now = new Date()
  const todayStr = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
  const yd = new Date(now); yd.setDate(yd.getDate() - 1)
  const yesterdayStr = `${yd.getFullYear()}${String(yd.getMonth() + 1).padStart(2, '0')}${String(yd.getDate()).padStart(2, '0')}`

  function groupLabel(date: string): string {
    if (date === todayStr || date === '今天') return '今天'
    if (date === yesterdayStr || date === '昨天') return '昨天'
    return '更早'
  }

  const cleanQuery = query.trim().toLowerCase()
  const visibleSessions = React.useMemo(() => (
    cleanQuery
      ? data.sessions.filter((session) => {
        const haystack = [session.title, session.preview, session.date, session.tone].filter(Boolean).join(' ').toLowerCase()
        return haystack.includes(cleanQuery)
      })
      : data.sessions
  ), [cleanQuery, data.sessions])
  const selected = visibleSessions.find((session) => session.id === selectedId) ?? visibleSessions[0]

  React.useEffect(() => {
    if (visibleSessions.length && !visibleSessions.some((session) => session.id === selectedId)) {
      setSelectedId(visibleSessions[0].id)
    }
  }, [selectedId, visibleSessions])

  const grouped: { label: string; sessions: typeof data.sessions }[] = []
  for (const session of visibleSessions) {
    const label = groupLabel(session.date)
    const existing = grouped.find((g) => g.label === label)
    if (existing) existing.sessions.push(session)
    else grouped.push({ label, sessions: [session] })
  }

  return (
    <div className="split-page">
      <div className="list-column">
        <div className="sessions-head">
          <div>
            <h1>历史对话</h1>
            <p>{data.status.adapter === 'local' ? '本地会话' : '示例会话'}</p>
          </div>
          <span>{visibleSessions.length}</span>
        </div>
        <div className="list-toolbar">
          <SearchBox placeholder="搜索会话" value={query} onChange={setQuery} />
          <button className="quiet-button" type="button" onClick={onRefresh}>
            刷新
          </button>
        </div>
        {grouped.length ? grouped.map((group) => (
          <React.Fragment key={group.label}>
            <div className="session-group-label">{group.label}</div>
            {group.sessions.map((session) => (
              <button
                className={`list-row ${selected?.id === session.id ? 'active' : ''}`}
                key={session.id}
                type="button"
                onClick={() => setSelectedId(session.id)}
              >
                <div>
                  <strong>{session.title}</strong>
                  <span>
                    {session.turns} 轮 · {session.tone}
                  </span>
                  {session.preview && (
                    <span className="session-preview">"{session.preview}"</span>
                  )}
                </div>
                <ChevronRight size={16} />
              </button>
            ))}
          </React.Fragment>
        )) : (
          <div className="empty-inline">无匹配会话</div>
        )}
      </div>
      {selected ? (
        <div className="session-detail">
          <div className="session-detail-head">
            <div className="session-detail-icon"><History size={18} /></div>
            <div>
              <h2>{selected.title}</h2>
              <p>{data.status.adapter === 'local' ? '只读预览，恢复后可续写。' : '连接本地服务后读取完整消息。'}</p>
            </div>
            <button className="quiet-button strong session-open-button" type="button" onClick={() => onOpenSession(selected)}>
              恢复
            </button>
          </div>
          <dl>
            <div>
              <dt>日期</dt>
              <dd>{selected.date}</dd>
            </div>
            <div>
              <dt>轮次</dt>
              <dd>{selected.turns}</dd>
            </div>
            <div>
              <dt>模式</dt>
              <dd>{selected.tone}</dd>
            </div>
          </dl>
          {detailState === 'loading' && <p className="detail-muted">读取中…</p>}
          {detailState === 'error' && <p className="detail-error">会话读取失败</p>}
          {detail?.messages.length ? (
            <div className="session-message-list">
              {detail.messages.map((message) => (
                <article className={`session-message ${message.role}`} key={message.id}>
                  <span>{message.role}</span>
                  <p>{message.text}</p>
                </article>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <EmptyDetail icon={History} title="暂无会话" text="本地 sessions 目录为空。" />
      )}
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)
