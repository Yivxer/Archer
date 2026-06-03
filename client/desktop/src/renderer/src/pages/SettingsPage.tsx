import React from 'react'
import { ArrowLeft, Clipboard, Database, Eye, KeyRound, Moon, Palette, Settings2, SlidersHorizontal, Sun, Terminal, X } from 'lucide-react'
import type { ApiConnectionState, ArcherAdapter, ConversationMode, MemoryContextMode, ObsidianContextMode, Route, Theme } from '../types'
import { FormField } from '../components/common'
import { clearDesktopApiToken, getDesktopApiToken, resolveDesktopApiToken, saveDesktopApiToken, saveLocalSettings, switchLocalMode } from '../adapters/localArcher'

type SettingsTab = 'model' | 'context' | 'local' | 'appearance'

export function SettingsPage({
  data,
  theme,
  setTheme,
  memoryMode,
  setMemoryMode,
  obsidianMode,
  setObsidianMode,
  conversationMode,
  setConversationMode,
  apiState,
  onRefresh,
  onNavigate,
}: {
  data: ArcherAdapter
  theme: Theme
  setTheme: (theme: Theme) => void
  memoryMode: MemoryContextMode
  setMemoryMode: (mode: MemoryContextMode) => void
  obsidianMode: ObsidianContextMode
  setObsidianMode: (mode: ObsidianContextMode) => void
  conversationMode: ConversationMode
  setConversationMode: (mode: ConversationMode) => void
  apiState: ApiConnectionState
  onRefresh: () => Promise<void>
  onNavigate?: (route: Route) => void
}) {
  const [activeTab, setActiveTab] = React.useState<SettingsTab>('local')
  const [draft, setDraft] = React.useState(data.settings)
  const [apiToken, setApiToken] = React.useState(() => getDesktopApiToken())
  const [notice, setNotice] = React.useState('')
  const [noticeWarning, setNoticeWarning] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [modeSaving, setModeSaving] = React.useState('')
  const [commandCopied, setCommandCopied] = React.useState(false)

  React.useEffect(() => {
    setDraft(data.settings)
    setNotice('')
  }, [data.settings])

  React.useEffect(() => {
    if (apiToken) return
    resolveDesktopApiToken().then((token) => {
      if (token) setApiToken(token)
    }).catch(() => {})
  }, [apiToken])

  // Esc 返回 Chat
  React.useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && onNavigate) {
        e.preventDefault()
        onNavigate('Chat')
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onNavigate])

  function updateDraft(key: keyof typeof draft, value: string) {
    setDraft((current) => ({ ...current, [key]: value }))
    setNotice('')
  }

  function resetDraft() {
    setDraft(data.settings)
    setNotice('已恢复为当前读取到的配置。')
  }

  async function saveToken() {
    saveDesktopApiToken(apiToken)
    setNotice(apiToken.trim() ? 'API token 已保存。' : 'API token 已清除。')
    await onRefresh()
  }

  async function clearToken() {
    setApiToken('')
    clearDesktopApiToken()
    setNotice('API token 已清除。')
    await onRefresh()
  }

  async function saveDraft() {
    if (data.status.adapter !== 'local') {
      setNotice('需要本地 API 连接才能保存设置。')
      return
    }
    setSaving(true)
    setNotice('')
    try {
      const result = await saveLocalSettings(draft)
      if (result.ok) {
        const restartMsg = result.restartRequired ? '；请重启 Archer API 使路径变更生效' : ''
        setNotice(`已保存 ${result.savedFields.length} 个字段到 archer.toml${restartMsg}。`)
        setNoticeWarning(Boolean(result.restartRequired))
      } else {
        setNotice(`保存失败：${result.errors?.join('；')}`)
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '设置保存失败')
    } finally {
      setSaving(false)
    }
  }

  async function chooseConversationMode(mode: string) {
    setNotice('')
    if (data.status.adapter !== 'local') {
      setConversationMode(mode)
      setNotice('需要本地 API 连接才能写入模式配置。')
      return
    }
    setModeSaving(mode)
    try {
      const result = await switchLocalMode(mode)
      setConversationMode(result.current)
      setNotice(`已切换到 ${result.label} 模式。`)
      await onRefresh()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '模式切换失败')
    } finally {
      setModeSaving('')
    }
  }

  async function copyStartCommand() {
    const tokenPart = apiToken.trim() || '<你的口令>'
    const command = `cd ~/Projects/Archer && .venv/bin/python terminal/archer_api.py --port 8765 --token ${tokenPart}`
    try {
      await navigator.clipboard.writeText(command)
      setCommandCopied(true)
      window.setTimeout(() => setCommandCopied(false), 1200)
    } catch {
      setNotice('复制失败，请手动复制启动命令。')
    }
  }

  const tabs: Array<{ id: SettingsTab; icon: React.ElementType; label: string; desc: string }> = [
    { id: 'local', icon: Database, label: '连接', desc: 'API、Token、路径' },
    { id: 'model', icon: KeyRound, label: '模型', desc: '服务商与模型' },
    { id: 'context', icon: SlidersHorizontal, label: '上下文', desc: '记忆与笔记' },
    { id: 'appearance', icon: Palette, label: '外观', desc: '主题' },
  ]
  const activeTabMeta = tabs.find((tab) => tab.id === activeTab) ?? tabs[0]

  const conversationModes = data.modes.modes.length
    ? data.modes.modes
    : [
      { id: 'listener', label: '倾听者', source: 'file' as const, active: true },
      { id: 'questioner', label: '追问者', source: 'file' as const, active: false },
    ]
  const activeConversationMode = data.status.adapter === 'local'
    ? data.modes.current || data.status.mode
    : conversationMode
  const canSaveDraft = activeTab === 'model' || activeTab === 'local'
  const saveLabel = activeTab === 'local' ? '保存路径配置' : '保存模型配置'

  return (
    <div className="settings-page">
      <aside className="settings-side-nav">
        <div className="settings-title-block">
          <h1>设置</h1>
          <p>本地连接、模型、上下文和显示偏好。</p>
        </div>
        <button className="settings-back" type="button" onClick={() => onNavigate?.('Chat')}>
          <ArrowLeft size={14} />
          返回对话
        </button>
        <div className="settings-tab-bar">
          {tabs.map((tab) => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                className={activeTab === tab.id ? 'active' : ''}
                type="button"
                onClick={() => setActiveTab(tab.id)}
              >
                <Icon size={13} />
                <span>
                  <strong>{tab.label}</strong>
                  <em>{tab.desc}</em>
                </span>
              </button>
            )
          })}
        </div>
      </aside>

      <div className="settings-tab-content">
        <header className="settings-content-head">
          <div>
            <h2>{activeTabMeta.label}</h2>
            <p>{activeTabMeta.desc}</p>
          </div>
          <button className="icon-button" type="button" onClick={() => onNavigate?.('Chat')} aria-label="关闭设置">
            <X size={15} />
          </button>
        </header>

        {activeTab === 'model' && (
          <SettingsGroup icon={Settings2} title="模型配置" note="保存到 archer.toml。密钥不回显。">
            <SettingRow title="服务商" description="当前模型提供方。">
              <FormField label="服务商" value={draft.provider} onChange={(value) => updateDraft('provider', value)} />
            </SettingRow>
            <SettingRow title="接口地址" description="兼容 OpenAI API 的 base URL。">
              <FormField label="接口地址" value={draft.baseUrl} onChange={(value) => updateDraft('baseUrl', value)} />
            </SettingRow>
            <SettingRow title="模型" description="聊天请求默认使用的模型名。">
              <FormField label="模型" value={draft.model} onChange={(value) => updateDraft('model', value)} />
            </SettingRow>
            <SettingRow title="API key" description="密钥只在本地配置里保存。">
              <FormField label="API key 状态" value={draft.apiKeyPreview} readOnly />
            </SettingRow>
          </SettingsGroup>
        )}

        {activeTab === 'context' && (
          <SettingsGroup icon={SlidersHorizontal} title="上下文偏好" note="控制记忆和笔记注入强度。">
            <SettingRow title="对话模式" description="Archer 的回应姿态。">
              <div className="segmented mode-segmented">
                {conversationModes.map((mode) => (
                  <button
                    key={mode.id}
                    className={activeConversationMode === mode.id ? 'active' : ''}
                    type="button"
                    disabled={Boolean(modeSaving)}
                    onClick={() => void chooseConversationMode(mode.id)}
                    title={mode.source === 'file' ? '文件模式' : '配置模式'}
                  >
                    {modeSaving === mode.id ? '切换中' : mode.label}
                  </button>
                ))}
              </div>
              <span className="settings-note">当前：{activeConversationMode || data.status.mode || '未读取'}</span>
            </SettingRow>
            <SettingRow title="记忆上下文" description="off / conservative / full。">
              <div className="segmented compact-segmented">
                {(['off', 'conservative', 'full'] as MemoryContextMode[]).map((mode) => (
                  <button key={mode} className={memoryMode === mode ? 'active' : ''} type="button" onClick={() => setMemoryMode(mode)}>
                    {mode}
                  </button>
                ))}
              </div>
            </SettingRow>
            <SettingRow title="笔记搜索" description="summary 摘要 / full 注入上下文。">
              <div className="segmented compact-segmented">
                {(['off', 'summary', 'full'] as ObsidianContextMode[]).map((mode) => (
                  <button key={mode} className={obsidianMode === mode ? 'active' : ''} type="button" onClick={() => setObsidianMode(mode)}>
                    {mode}
                  </button>
                ))}
              </div>
            </SettingRow>
          </SettingsGroup>
        )}

        {activeTab === 'local' && (
          <SettingsGroup icon={Database} title="本地连接" note="聊天、历史和文件引用依赖本机 API。">
            <div className="connection-guide">
              <div className={`connection-status ${apiState}`}>
                <span>连接状态</span>
                <strong>{apiStatusText(apiState, data.status.adapter === 'local')}</strong>
                <p>{apiStatusHelp(apiState, data.status.adapter === 'local')}</p>
              </div>
              <div className="connection-command">
                <Terminal size={15} />
                <code>cd /Users/Yivxer/Projects/Archer && .venv/bin/python terminal/archer_api.py --port 8765 --token &lt;你的口令&gt;</code>
                <button className="quiet-button" type="button" onClick={copyStartCommand}>
                  <Clipboard size={13} />
                  {commandCopied ? '已复制' : '复制命令'}
                </button>
              </div>
              <p className="settings-note">{localFixHint(apiState, data.status.adapter === 'local')}</p>
            </div>
            <SettingRow title="API Token" description="桌面端连接本机 API 的本地口令。">
              <label className="token-field">
                <span>连接口令</span>
                <input
                  type="password"
                  value={apiToken}
                  onChange={(event) => {
                    setApiToken(event.target.value)
                    setNotice('')
                  }}
                  placeholder="终端启动时显示的 token"
                />
              </label>
              <div className="token-actions">
                <button className="quiet-button strong" type="button" onClick={saveToken}>
                  保存并重连
                </button>
                <button className="quiet-button" type="button" onClick={clearToken}>
                  清除
                </button>
              </div>
            </SettingRow>
            <SettingRow title="本地路径" description="变更后需重启 API 生效。">
              <FormField label="配置文件" value={draft.configPath} onChange={(value) => updateDraft('configPath', value)} />
              <FormField label="记忆数据库" value={draft.memoryDbPath} onChange={(value) => updateDraft('memoryDbPath', value)} />
              <FormField label="历史会话" value={draft.sessionsPath} onChange={(value) => updateDraft('sessionsPath', value)} />
            </SettingRow>
            <div className="settings-policy">
              <strong>保存策略</strong>
              <span>只保存 provider / base URL / model / local paths 到 archer.toml。API key 不回显明文。</span>
            </div>
          </SettingsGroup>
        )}

        {activeTab === 'appearance' && (
          <SettingsGroup icon={Eye} title="外观" note="主题立即生效，保存在本地。">
            <SettingRow title="主题" description="立即生效，并保存在当前桌面端。">
              <div className="segmented theme-choice">
                <button className={theme === 'light' ? 'active' : ''} type="button" onClick={() => setTheme('light')}>
                  <Sun size={15} />
                  浅色
                </button>
                <button className={theme === 'dark' ? 'active' : ''} type="button" onClick={() => setTheme('dark')}>
                  <Moon size={15} />
                  深色
                </button>
              </div>
            </SettingRow>
            <SettingRow title="背景密度" description="第一轮固定为柔和，避免设置项过早膨胀。">
              <span className="setting-static-value">柔和</span>
            </SettingRow>
          </SettingsGroup>
        )}

        {canSaveDraft && (
          <div className="settings-actions settings-actions-fixed">
            <button className="quiet-button" type="button" onClick={resetDraft}>
              恢复当前配置
            </button>
            <button className="quiet-button strong" type="button" onClick={saveDraft} disabled={saving}>
              {saving ? '保存中' : saveLabel}
            </button>
          </div>
        )}
        {notice && <div className={`settings-notice${noticeWarning ? ' warning' : ''}`}>{notice}</div>}
      </div>
    </div>
  )
}

function SettingsGroup({
  icon: Icon,
  title,
  note,
  children
}: {
  icon: React.ElementType
  title: string
  note: string
  children: React.ReactNode
}) {
  return (
    <section className="settings-panel">
      <div className="settings-group-head">
        <span><Icon size={16} /></span>
        <div>
          <h3>{title}</h3>
          <p>{note}</p>
        </div>
      </div>
      <div className="settings-group-body">{children}</div>
    </section>
  )
}

function SettingRow({
  title,
  description,
  children
}: {
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <div className="setting-row">
      <div className="setting-row-copy">
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
      <div className="setting-row-control">{children}</div>
    </div>
  )
}

function apiStatusText(apiState: ApiConnectionState, isLocal: boolean): string {
  if (isLocal || apiState === 'connected') return '已连接'
  if (apiState === 'loading') return '连接中'
  if (apiState === 'missing_token') return '需要本地连接口令'
  if (apiState === 'bad_token') return 'token 不匹配'
  if (apiState === 'api_offline') return '本地 API 未启动'
  return '本地 API 未连接'
}

function apiStatusHelp(apiState: ApiConnectionState, isLocal: boolean): string {
  if (isLocal || apiState === 'connected') return '可以读取本地会话、记忆、Soul 文件和设置。'
  if (apiState === 'missing_token') return '本地服务已打开，但桌面端还没有保存连接口令。'
  if (apiState === 'bad_token') return '已保存的连接口令与本地 API 启动参数不一致。'
  if (apiState === 'api_offline') return '本地 API 未连接，启动后可读取历史、记忆和配置。'
  if (apiState === 'loading') return '正在检查本地 API 状态。'
  return '本地 API 未连接，显示的是示例数据，连接后可读取真实内容。'
}

function localFixHint(apiState: ApiConnectionState, isLocal: boolean): string {
  if (isLocal || apiState === 'connected') return '连接正常。可以恢复会话、引用本地文件。'
  if (apiState === 'missing_token') return '请在下方输入 API 启动时使用的口令，然后保存并重连。启动命令：python terminal/archer_api.py --token <你的口令>'
  if (apiState === 'bad_token') return '口令与终端启动参数不一致。覆盖后保存并重连。'
  if (apiState === 'api_offline') return '需要聊天、记忆读取或设置保存时，先启动本地 API：python terminal/archer_api.py --token <你的口令>'
  return '确认本地 API 已启动，再检查口令和模型配置。'
}
