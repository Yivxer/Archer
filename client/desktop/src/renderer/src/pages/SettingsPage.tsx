import React from 'react'
import { ArrowLeft, CalendarClock, CalendarDays, Clipboard, Database, Eye, KeyRound, Layers, ListChecks, Moon, Palette, Settings2, SlidersHorizontal, Sun, Terminal, X, Activity } from 'lucide-react'
import type { ApiConnectionState, ArcherAdapter, ConversationMode, MemoryContextMode, ObsidianContextMode, Route, ScheduledTask, Theme } from '../types'
import { FormField } from '../components/common'
import { addSchedule, clearDesktopApiToken, getDesktopApiToken, listSchedules, removeSchedule, resolveDesktopApiToken, restartLocalApi, runSchedule, saveDesktopApiToken, saveLocalProfileSettings, saveLocalSettings, setScheduleEnabled, switchLocalMode, testLocalModelProfile } from '../adapters/localArcher'
import { connectionStatusLabel, expertShortLabel, modeLabelFromId, modelProfileShortLabel, personaPresetFromMode } from '../lib/conversationPersona'

type SettingsTab = 'model' | 'context' | 'local' | 'appearance' | 'schedules' | 'diagnostics'

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
  apiReason,
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
  apiReason?: string
  onRefresh: () => Promise<void>
  onNavigate?: (route: Route) => void
}) {
  const [activeTab, setActiveTab] = React.useState<SettingsTab>(() => {
    const stored = sessionStorage.getItem('archer-settings-tab')
    sessionStorage.removeItem('archer-settings-tab')
    return stored === 'model' || stored === 'context' || stored === 'local' || stored === 'appearance' || stored === 'schedules' || stored === 'diagnostics'
      ? stored
      : 'model'
  })
  const [draft, setDraft] = React.useState(data.settings)
  const [apiToken, setApiToken] = React.useState(() => getDesktopApiToken())
  const [notice, setNotice] = React.useState('')
  const [noticeWarning, setNoticeWarning] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [testingModel, setTestingModel] = React.useState(false)
  const [restartingApi, setRestartingApi] = React.useState(false)
  const [modeSaving, setModeSaving] = React.useState('')
  const [commandCopied, setCommandCopied] = React.useState(false)
  const [scheduleTasks, setScheduleTasks] = React.useState<ScheduledTask[]>([])
  const [scheduleLoading, setScheduleLoading] = React.useState(false)
  const [scheduleSkill, setScheduleSkill] = React.useState('')
  const [scheduleInterval, setScheduleInterval] = React.useState('daily')
  const [scheduleLabel, setScheduleLabel] = React.useState('')
  const [scheduleBusyId, setScheduleBusyId] = React.useState<number | null>(null)

  React.useEffect(() => {
    setDraft({ ...data.settings, apiKey: '' })
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

  async function chooseModelProfile(profileId: 'lite' | 'pro' | 'max') {
    // 切换前先保存当前 profile 的配置，避免丢失当前填写的 apiKey 等字段
    const currentProfileId = draft.activeProfile
    if (currentProfileId && currentProfileId !== profileId) {
      // 只有当前 draft 有任何配置变更时才保存
      const hasChanges = draft.apiKey || draft.baseUrl || draft.model || draft.provider
      if (hasChanges) {
        try {
          await saveLocalProfileSettings({
            profileId: currentProfileId,
            provider: draft.provider,
            baseUrl: draft.baseUrl,
            model: draft.model,
            apiKey: draft.apiKey,
          })
        } catch (err) {
          // 保存失败不阻塞切换，但提示用户
          setNotice(`切换前保存 ${modelProfileShortLabel(currentProfileId)} 配置失败：${err instanceof Error ? err.message : String(err)}`)
        }
      }
    }

    const profile = draft.modelProfiles?.find((item) => item.id === profileId)
    setDraft((current) => ({
      ...current,
      activeProfile: profileId,
      provider: profile?.provider ?? current.provider,
      baseUrl: profile?.baseUrl ?? '',
      model: profile?.model ?? '',
      apiKey: '',
      apiKeyPreview: profile?.apiKeyPreview ?? '',
    }))
    setNotice('')
  }

  function resetDraft() {
    setDraft({ ...data.settings, apiKey: '' })
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

  async function restartApi() {
    setRestartingApi(true)
    setNotice('')
    setNoticeWarning(false)
    try {
      const result = await restartLocalApi()
      await onRefresh()
      if (result.ok) {
        setNotice('已重启本地大脑。')
      } else {
        setNotice(`重启本地大脑失败：${result.reason}`)
        setNoticeWarning(true)
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '重启本地大脑失败')
      setNoticeWarning(true)
    } finally {
      setRestartingApi(false)
    }
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

  async function testCurrentModelProfile() {
    if (data.status.adapter !== 'local') {
      setNotice('需要本地 API 连接后才能测试模型。')
      setNoticeWarning(true)
      return
    }
    setTestingModel(true)
    setSaving(true)
    setNotice('')
    setNoticeWarning(false)
    try {
      const saved = await saveLocalSettings(draft)
      if (!saved.ok) {
        setNotice(`保存失败，未测试：${saved.errors?.join('；')}`)
        setNoticeWarning(true)
        return
      }
      const result = await testLocalModelProfile(draft)
      if (result.ok) {
        setNotice(`${result.profile} / ${result.provider} 测试通过：${result.model} · ${result.latencyMs}ms`)
        setNoticeWarning(false)
      } else {
        setNotice(`${modelProfileShortLabel(draft.activeProfile)} 测试失败：${result.message}${result.errors?.length ? `；${result.errors[0]}` : ''}`)
        setNoticeWarning(true)
      }
      await onRefresh()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '模型测试失败')
      setNoticeWarning(true)
    } finally {
      setTestingModel(false)
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

  const loadScheduleTasks = React.useCallback(async () => {
    if (data.status.adapter !== 'local') {
      setScheduleTasks([])
      return
    }
    setScheduleLoading(true)
    try {
      const result = await listSchedules()
      setScheduleTasks(result.tasks || [])
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '读取定时任务失败')
    } finally {
      setScheduleLoading(false)
    }
  }, [data.status.adapter])

  React.useEffect(() => {
    if (activeTab !== 'schedules') return
    void loadScheduleTasks()
  }, [activeTab, loadScheduleTasks])

  async function submitSchedule() {
    if (data.status.adapter !== 'local') {
      setNotice('需要本地 API 连接才能管理定时任务。')
      return
    }
    if (!scheduleSkill.trim()) {
      setNotice('请填写技能名称。')
      return
    }
    setSaving(true)
    setNotice('')
    try {
      await addSchedule({
        skillName: scheduleSkill.trim(),
        interval: scheduleInterval.trim() || 'daily',
        label: scheduleLabel.trim(),
      })
      setScheduleSkill('')
      setScheduleLabel('')
      setNotice('定时任务已添加。')
      await loadScheduleTasks()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '添加定时任务失败')
    } finally {
      setSaving(false)
    }
  }

  async function toggleScheduleTask(task: ScheduledTask) {
    setScheduleBusyId(task.id)
    setNotice('')
    try {
      await setScheduleEnabled(task.id, !task.enabled)
      await loadScheduleTasks()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '更新任务状态失败')
    } finally {
      setScheduleBusyId(null)
    }
  }

  async function deleteScheduleTask(taskId: number) {
    setScheduleBusyId(taskId)
    setNotice('')
    try {
      await removeSchedule(taskId)
      setNotice('定时任务已删除。')
      await loadScheduleTasks()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '删除定时任务失败')
    } finally {
      setScheduleBusyId(null)
    }
  }

  async function runScheduleTask(taskId: number) {
    setScheduleBusyId(taskId)
    setNotice('')
    try {
      const result = await runSchedule(taskId)
      setNotice(result.ok ? `已执行：${result.summary || '完成'}` : `执行失败：${result.summary || result.error || '未知错误'}`)
      await loadScheduleTasks()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '执行任务失败')
    } finally {
      setScheduleBusyId(null)
    }
  }

  const tabs: Array<{ id: SettingsTab; icon: React.ElementType; label: string; desc: string }> = [
    { id: 'local', icon: Database, label: '连接', desc: 'API、Token、路径' },
    { id: 'schedules', icon: CalendarClock, label: '定时', desc: '技能定时执行' },
    { id: 'model', icon: KeyRound, label: '模型', desc: '服务商与模型' },
    { id: 'context', icon: SlidersHorizontal, label: '上下文', desc: '记忆与笔记' },
    { id: 'appearance', icon: Palette, label: '外观', desc: '主题' },
    { id: 'diagnostics', icon: Activity, label: '诊断', desc: '系统状态与审计' },
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
  const modelProfiles = draft.modelProfiles?.length
    ? draft.modelProfiles
    : [
      { id: 'lite' as const, label: 'DSK', provider: 'DeepSeek', configured: true },
      { id: 'pro' as const, label: 'KIM', provider: 'Kimi', configured: false },
      { id: 'max' as const, label: 'GLM', provider: 'GLM', configured: false },
    ]

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
            <SettingRow title="模型档位" description="选择后保存即可切换聊天默认模型；也可以在输入框的模型按钮里快速切换。">
              <div className="model-profile-grid">
                {modelProfiles.map((profile) => (
                  <button
                    key={profile.id}
                    className={`model-profile-card${draft.activeProfile === profile.id ? ' active' : ''}`}
                    type="button"
                    onClick={() => chooseModelProfile(profile.id)}
                    title={profile.configured ? `${modelProfileShortLabel(profile.id)} 已配置` : `${modelProfileShortLabel(profile.id)} 待配置`}
                  >
                    <span>{modelProfileShortLabel(profile.id)}</span>
                    <strong>{profile.provider}</strong>
                    <em>{profile.model || '未填写模型'}</em>
                    <small>{profile.configured ? '已配置 API' : '未配置 API'}</small>
                  </button>
                ))}
              </div>
              <span className="settings-note">
                当前模型：{modelProfileShortLabel(draft.activeProfile)} · {modelProfiles.find((item) => item.id === draft.activeProfile)?.provider || draft.provider}
              </span>
            </SettingRow>
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
              <FormField
                label="新 API key"
                value={draft.apiKey || ''}
                onChange={(value) => updateDraft('apiKey', value)}
                type="password"
                placeholder="留空则保留当前 key"
              />
            </SettingRow>
            <SettingRow title="连通测试" description="保存当前档位后，发送一次最短 ping 请求验证可用性。">
              <button className="quiet-button strong" type="button" onClick={() => void testCurrentModelProfile()} disabled={testingModel || saving}>
                {testingModel ? '测试中' : `测试 ${modelProfileShortLabel(draft.activeProfile)}`}
              </button>
              <span className="settings-note">会消耗极少量 API 额度；不会显示或返回密钥。</span>
            </SettingRow>
          </SettingsGroup>
        )}

        {activeTab === 'context' && (
          <SettingsGroup icon={SlidersHorizontal} title="上下文偏好" note="对话姿态（高级）与专家工作台（日常）是两层；专家管技能池与记忆偏好，模型档位在输入框单独切换。">
            <SettingRow title="对话姿态" description="高级选项：锁定 12 种姿态之一；自动 = 每轮按内容选姿态。日常场景请在聊天区切换专家。">
              <div className="segmented mode-segmented">
                <button
                  className={activeConversationMode === 'auto' ? 'active' : ''}
                  type="button"
                  disabled={Boolean(modeSaving)}
                  onClick={() => void chooseConversationMode('auto')}
                >
                  {modeSaving === 'auto' ? '切换中' : '自动'}
                </button>
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
              <span className="settings-note">
                当前：{modeLabelFromId(activeConversationMode || 'auto', conversationModes)}
                {activeConversationMode !== 'auto' && (
                  <> · 聊天人格：{personaPresetFromMode(activeConversationMode).label}</>
                )}
              </span>
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
            <SettingRow title="专家工作台" description="日常在聊天区切换；可在 archer.toml [experts.*] 或插件 experts/*.toml 添加自定义专家。">
              <div className="settings-note expert-settings-list">
                {(data.experts?.experts ?? []).map((expert) => (
                  <p key={expert.id}>
                    <strong>{expert.label}</strong>
                    {' · '}
                    {expert.note}
                    {' · '}
                    <em>
                      {expert.id}
                      {expert.custom ? ' · 自定义' : ''}
                      {expert.source && expert.source !== 'builtin' ? ` · ${expert.source}` : ''}
                    </em>
                  </p>
                ))}
              </div>
              <span className="settings-note">
                当前：{expertShortLabel(data.experts?.current || data.status.expertId, data.experts?.experts ?? [], data.status.expertLabel)}
                {' · '}模型档位在聊天输入框单独切换
              </span>
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
          <SettingsGroup icon={Database} title="本地连接" note="打开 Archer 会自动拉起本机大脑，无需手动拨号。">
            <div className="connection-guide">
              <div className={`connection-status ${apiState}`}>
                <span>连接状态</span>
                <strong>{apiStatusText(apiState, data.status.adapter === 'local', apiReason)}</strong>
                <p>{apiStatusHelp(apiState, data.status.adapter === 'local', apiReason)}</p>
              </div>
              <p className="settings-note">{localFixHint(apiState, data.status.adapter === 'local', apiReason)}</p>
            </div>
            <SettingRow title="大脑进程" description="连接异常时，可手动重启本地 API。">
              <button className="quiet-button strong" type="button" onClick={() => void restartApi()} disabled={restartingApi}>
                {restartingApi ? '重启中…' : '重启本地大脑'}
              </button>
            </SettingRow>
            <SettingRow title="权限审计" description="最近工具审批记录，只展示摘要。">
              <div className="settings-note expert-settings-list">
                {data.toolApprovalAudit.items.length === 0 && <p>暂无工具审批记录。</p>}
                {data.toolApprovalAudit.items.slice(0, 5).map((item) => (
                  <p key={`${item.eventId}-${item.timestamp}`}>
                    <strong>{item.skillName || 'unknown'}</strong>
                    {' · '}
                    {item.decision}
                    {' · '}
                    {item.permissionLevel || 'unknown'}
                    {' · '}
                    {item.executed ? '已执行' : '未执行'}
                    {' · '}
                    <em>{formatAuditTime(item.timestamp)}</em>
                  </p>
                ))}
              </div>
            </SettingRow>
            <SettingRow title="连接口令" description="由应用自动管理，一般不需要填写。只有手动调试 API 时才用。">
              <label className="token-field">
                <span>高级口令（可选）</span>
                <input
                  type="password"
                  value={apiToken}
                  onChange={(event) => {
                    setApiToken(event.target.value)
                    setNotice('')
                  }}
                  placeholder="留空 = 使用应用自动口令"
                />
              </label>
              <div className="token-actions">
                <button className="quiet-button strong" type="button" onClick={saveToken}>
                  保存并重连
                </button>
                <button className="quiet-button" type="button" onClick={clearToken}>
                  恢复自动
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
              <span>保存 provider / base URL / model / API key / local paths 到 archer.toml。API key 只写入本地，不回显明文。</span>
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
            <SettingRow title="次级入口" description="不放在主侧边栏。">
              <div className="settings-shortcut-row">
                <button className="quiet-button" type="button" onClick={() => onNavigate?.('Today')}>
                  <CalendarDays size={14} />
                  今日
                </button>
                <button className="quiet-button" type="button" onClick={() => onNavigate?.('Tasks')}>
                  <ListChecks size={14} />
                  任务
                </button>
                <button className="quiet-button" type="button" onClick={() => onNavigate?.('Soul')}>
                  <Layers size={14} />
                  人格
                </button>
              </div>
            </SettingRow>
          </SettingsGroup>
        )}

        {activeTab === 'schedules' && (
          <SettingsGroup icon={CalendarClock} title="定时任务" note="按间隔自动执行技能；终端也可用 /schedule。">
            {data.status.adapter !== 'local' && (
              <p className="schedule-empty">连接本地 API 后可查看与管理定时任务。</p>
            )}
            {data.status.adapter === 'local' && scheduleLoading && (
              <p className="schedule-empty">加载中…</p>
            )}
            {data.status.adapter === 'local' && !scheduleLoading && scheduleTasks.length === 0 && (
              <p className="schedule-empty">暂无定时任务。下方添加，或在终端使用 /schedule add。</p>
            )}
            {data.status.adapter === 'local' && scheduleTasks.length > 0 && (
              <div className="schedule-list">
                {scheduleTasks.map((task) => (
                  <div className="schedule-row" key={task.id}>
                    <div className="schedule-row-main">
                      <strong>{task.label || task.skillName}</strong>
                      <span>{task.skillName} · {task.intervalLabel}</span>
                      <div className="schedule-row-meta">
                        {task.enabled ? '启用' : '禁用'} · 下次 {task.nextRunAt.slice(0, 16)}
                      </div>
                    </div>
                    <div className="schedule-row-actions">
                      <button
                        className="quiet-button"
                        type="button"
                        disabled={scheduleBusyId === task.id}
                        onClick={() => void toggleScheduleTask(task)}
                      >
                        {task.enabled ? '禁用' : '启用'}
                      </button>
                      <button
                        className="quiet-button"
                        type="button"
                        disabled={scheduleBusyId === task.id}
                        onClick={() => void runScheduleTask(task.id)}
                      >
                        立即运行
                      </button>
                      <button
                        className="quiet-button"
                        type="button"
                        disabled={scheduleBusyId === task.id}
                        onClick={() => void deleteScheduleTask(task.id)}
                      >
                        删除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <SettingRow title="添加任务" description="interval 支持 daily、weekly、6h 等。">
              <div className="schedule-add-form">
                <FormField label="技能名" value={scheduleSkill} onChange={setScheduleSkill} />
                <FormField label="间隔" value={scheduleInterval} onChange={setScheduleInterval} />
                <FormField label="标签（可选）" value={scheduleLabel} onChange={setScheduleLabel} />
                <button className="quiet-button strong" type="button" onClick={() => void submitSchedule()} disabled={saving}>
                  {saving ? '添加中' : '添加定时任务'}
                </button>
              </div>
            </SettingRow>
          </SettingsGroup>
        )}

        {activeTab === 'diagnostics' && (
          <SettingsGroup icon={Activity} title="系统诊断" note="查看系统状态、工具审计和配置检查。">
            <SettingRow title="配置自检" description="/config/doctor 检查结果。">
              <div className="diagnostics-doctor">
                <div className="diagnostics-doctor-summary">
                  <span className={`diagnostics-badge diagnostics-badge-${data.configDoctor.summary.error > 0 ? 'error' : data.configDoctor.summary.warn > 0 ? 'warn' : 'ok'}`}>
                    {data.configDoctor.summary.error > 0 ? `${data.configDoctor.summary.error} 错误` : data.configDoctor.summary.warn > 0 ? `${data.configDoctor.summary.warn} 警告` : '全部通过'}
                  </span>
                  <span className="diagnostics-doctor-count">{data.configDoctor.summary.info} 提示</span>
                </div>
                {data.configDoctor.issues.length === 0 ? (
                  <p className="diagnostics-doctor-empty">配置检查通过，未发现问题。</p>
                ) : (
                  <ul className="diagnostics-doctor-list">
                    {data.configDoctor.issues.map((issue, index) => (
                      <li key={index} className={`diagnostics-doctor-item diagnostics-doctor-item-${issue.level}`}>
                        <span className={`diagnostics-doctor-level diagnostics-doctor-level-${issue.level}`}>
                          {issue.level === 'error' ? '错误' : issue.level === 'warn' ? '警告' : '提示'}
                        </span>
                        <span className="diagnostics-doctor-message">{issue.message}</span>
                        {issue.nextAction && <span className="diagnostics-doctor-action">{issue.nextAction}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </SettingRow>

            <SettingRow title="工具审批审计" description="最近工具调用的审批记录，按时间倒序。">
              <div className="diagnostics-audit">
                {data.toolApprovalAudit.items.length === 0 ? (
                  <p className="diagnostics-audit-empty">暂无工具审批记录。</p>
                ) : (
                  <table className="diagnostics-audit-table">
                    <thead>
                      <tr>
                        <th>时间</th>
                        <th>技能</th>
                        <th>权限</th>
                        <th>决策</th>
                        <th>执行</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.toolApprovalAudit.items.slice(0, 10).map((item) => (
                        <tr key={`${item.eventId}-${item.timestamp}`}>
                          <td className="diagnostics-audit-time">{formatAuditTime(item.timestamp)}</td>
                          <td className="diagnostics-audit-skill">{item.skillName}</td>
                          <td>
                            <span className={`diagnostics-permission diagnostics-permission-${item.permissionLevel || 'unknown'}`}>
                              {item.permissionLevel || 'unknown'}
                            </span>
                          </td>
                          <td>{item.decision}{item.reused ? ' (复用)' : ''}</td>
                          <td>{item.executed ? '是' : '否'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </SettingRow>

            <SettingRow title="系统状态" description="当前连接状态与核心指标。">
              <div className="diagnostics-status">
                <div className="diagnostics-status-row">
                  <span className="diagnostics-status-label">连接状态</span>
                  <span className={`diagnostics-status-value diagnostics-status-value-${apiState}`}>
                    {connectionStatusLabel(apiState, data.status.adapter === 'local')}
                  </span>
                </div>
                <div className="diagnostics-status-row">
                  <span className="diagnostics-status-label">适配器</span>
                  <span className="diagnostics-status-value">{data.status.adapter === 'local' ? '本地 API' : 'Mock'}</span>
                </div>
                <div className="diagnostics-status-row">
                  <span className="diagnostics-status-label">模型</span>
                  <span className="diagnostics-status-value">{data.status.model || '未配置'}</span>
                </div>
                <div className="diagnostics-status-row">
                  <span className="diagnostics-status-label">记忆条目</span>
                  <span className="diagnostics-status-value">{data.memory.length}</span>
                </div>
                <div className="diagnostics-status-row">
                  <span className="diagnostics-status-label">技能数</span>
                  <span className="diagnostics-status-value">{data.skills.length}</span>
                </div>
              </div>
            </SettingRow>

            <SettingRow title="权限矩阵" description="各技能的权限等级与调用统计。">
              <div className="diagnostics-permissions">
                <div className="diagnostics-permissions-summary">
                  {(['read-only', 'write-local', 'write-vault', 'deploy-remote'] as const).map((level) => {
                    const count = data.skills.filter((s) => (s.permissionLevel || 'unknown') === level).length
                    return (
                      <div key={level} className="diagnostics-permissions-summary-item">
                        <span className={`diagnostics-permission diagnostics-permission-${level}`}>{level}</span>
                        <span className="diagnostics-permissions-summary-count">{count} 个技能</span>
                      </div>
                    )
                  })}
                </div>
                <div className="diagnostics-permissions-grid">
                  {data.skills.slice(0, 20).map((skill) => (
                    <div key={skill.name} className="diagnostics-permissions-grid-item">
                      <span className="diagnostics-permissions-grid-name">{skill.name}</span>
                      <span className={`diagnostics-permission diagnostics-permission-${skill.permissionLevel || 'unknown'}`}>
                        {skill.permissionLevel || 'unknown'}
                      </span>
                    </div>
                  ))}
                  {data.skills.length > 20 && (
                    <div className="diagnostics-permissions-grid-item diagnostics-permissions-grid-more">
                      还有 {data.skills.length - 20} 个技能…
                    </div>
                  )}
                </div>
                <div className="diagnostics-permissions-audit-summary">
                  <div className="diagnostics-permissions-audit-row">
                    <span className="diagnostics-permissions-audit-label">审批决策</span>
                    <div className="diagnostics-permissions-audit-badges">
                      {(['allow', 'confirm', 'strong_confirm', 'deny'] as const).map((decision) => {
                        const count = data.toolApprovalAudit.items.filter((item) => item.decision === decision).length
                        if (count === 0) return null
                        return (
                          <span key={decision} className={`diagnostics-permissions-audit-badge diagnostics-permissions-audit-badge-${decision}`}>
                            {decision}: {count}
                          </span>
                        )
                      })}
                      {data.toolApprovalAudit.items.length === 0 && (
                        <span className="diagnostics-permissions-audit-badge diagnostics-permissions-audit-badge-empty">暂无记录</span>
                      )}
                    </div>
                  </div>
                  <div className="diagnostics-permissions-audit-row">
                    <span className="diagnostics-permissions-audit-label">已执行</span>
                    <span className="diagnostics-permissions-audit-value">
                      {data.toolApprovalAudit.items.filter((item) => item.executed).length} / {data.toolApprovalAudit.items.length}
                    </span>
                  </div>
                </div>
              </div>
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

function apiStatusText(apiState: ApiConnectionState, isLocal: boolean, reason = ''): string {
  if (isLocal || apiState === 'connected') return connectionStatusLabel(apiState, true)
  if (apiState === 'loading') return '连接中'
  if (reason === 'missing_python') return '找不到 Python 运行环境'
  if (reason === 'missing_script') return '找不到 Archer API 入口'
  if (reason === 'not_ready') return '大脑进程未就绪'
  if (reason === 'token_mismatch') return '连接口令不匹配'
  if (reason === 'port_down') return '大脑端口未启动'
  if (apiState === 'missing_token') return '需要本地连接口令'
  if (apiState === 'bad_token') return 'token 不匹配'
  if (apiState === 'api_offline') return '大脑进程未运行'
  return '本地 API 未连接'
}

function apiStatusHelp(apiState: ApiConnectionState, isLocal: boolean, reason = ''): string {
  if (isLocal || apiState === 'connected') return '可以读取本地会话、记忆、Soul 文件和设置。'
  if (apiState === 'loading') return '正在自动连接本机大脑。'
  if (reason === 'missing_python') return '当前配置的 Python 解释器不存在，检查 ARCHER_PYTHON_BIN 或项目 .venv。'
  if (reason === 'missing_script') return '当前配置的 API 脚本不存在，检查 ARCHER_API_SCRIPT 或 Archer 项目路径。'
  if (reason === 'not_ready') return '进程有响应但 readiness 未通过，应用会继续重试。'
  if (reason === 'token_mismatch') return '端口上已有 Archer API，但它使用了不同的桌面口令。'
  if (reason === 'port_down') return '本地 8765 端口暂未响应，应用会尝试自动拉起。'
  if (apiState === 'api_offline') return '应用会自动重试拉起大脑进程，通常无需手动操作。'
  return '暂时显示示例数据；连接恢复后会自动切回真实内容。'
}

function localFixHint(apiState: ApiConnectionState, isLocal: boolean, reason = ''): string {
  if (isLocal || apiState === 'connected') return '连接正常。可以恢复会话、引用本地文件。'
  if (reason === 'missing_python') return '先确认 `/Users/Yivxer/Projects/Archer/.venv/bin/python3` 存在，或设置 ARCHER_PYTHON_BIN。'
  if (reason === 'missing_script') return '先确认 `/Users/Yivxer/Projects/Archer/archer_api.py` 存在，或设置 ARCHER_API_SCRIPT。'
  if (reason === 'token_mismatch') return '可完全退出 Archer 后重开；应用会回收不匹配的本地端口。'
  if (apiState === 'error') return '请确认 ~/Projects/Archer/.venv 存在。重启 Archer 通常会恢复。'
  return '若长时间未连接，可重启 Archer；高级用户才需要手动改口令。'
}

function formatAuditTime(timestamp: number): string {
  if (!Number.isFinite(timestamp) || timestamp <= 0) return '时间未知'
  return new Date(timestamp * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
