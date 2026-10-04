import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readLocalSettings, switchLocalActiveProfile, saveLocalSettings } from '../../adapters/settingsAdapter'
import { mockSettings } from '../../adapters/mockSettings'
import { getSettingsStoreState, loadSettings, readConfirmedSettings, resetSettingsStore, saveSettings, switchSettingsProfile } from '../settingsStore'
import { createSettingsSession } from '../settingsSession'
const credentials = vi.hoisted(() => ({ token: 'synthetic' }))
vi.mock('../../adapters/settingsAdapter', () => ({ readLocalSettings: vi.fn(), switchLocalActiveProfile: vi.fn(), saveLocalSettings: vi.fn(), saveLocalProfileSettings: vi.fn() }))
vi.mock('../../adapters/localArcher', () => ({ getDesktopApiToken: () => credentials.token }))
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r }); return { resolve, promise } }
beforeEach(() => { vi.clearAllMocks(); credentials.token = 'synthetic'; resetSettingsStore(); vi.mocked(readLocalSettings).mockResolvedValue(mockSettings) })
describe('Settings server projection', () => {
  it('coalesces reads and never keeps a plaintext key', async () => {
    vi.mocked(readLocalSettings).mockResolvedValue({ ...mockSettings, apiKey: 'synthetic-secret' })
    await Promise.all([loadSettings(), loadSettings()])
    expect(readLocalSettings).toHaveBeenCalledTimes(1)
    expect(getSettingsStoreState()).toMatchObject({ loadState: 'ready', settings: { apiKey: '' } })
  })
  it('retains the last confirmed configuration on failure and recovers', async () => {
    await loadSettings(); vi.mocked(readLocalSettings).mockRejectedValueOnce(new Error('offline'))
    await expect(loadSettings()).rejects.toThrow('offline')
    expect(getSettingsStoreState()).toMatchObject({ loadState: 'error', settings: { model: mockSettings.model } })
    await loadSettings(); expect(getSettingsStoreState().loadState).toBe('ready')
  })
  it('ignores forced-overlap and reset responses', async () => {
    const old = deferred<typeof mockSettings>(); vi.mocked(readLocalSettings).mockReturnValueOnce(old.promise)
    const first = loadSettings().catch(() => undefined)
    await loadSettings({ force: true }); old.resolve({ ...mockSettings, model: 'old' }); await first
    expect(getSettingsStoreState().settings?.model).toBe(mockSettings.model)
    const late = deferred<typeof mockSettings>(); vi.mocked(readLocalSettings).mockReturnValueOnce(late.promise)
    const pending = loadSettings().catch(() => undefined); resetSettingsStore(); late.resolve(mockSettings); await pending
    expect(getSettingsStoreState()).toMatchObject({ settings: null, loadState: 'idle' })
  })
  it('publishes a profile only after a confirmed GET and blocks duplicate switches', async () => {
    await loadSettings(); const write = deferred<{ ok: boolean }>(); vi.mocked(switchLocalActiveProfile).mockReturnValueOnce(write.promise)
    const pending = switchSettingsProfile('max'); await expect(switchSettingsProfile('pro')).rejects.toThrow()
    expect(getSettingsStoreState().settings?.activeProfile).toBe('lite')
    vi.mocked(readLocalSettings).mockResolvedValue({ ...mockSettings, activeProfile: 'max' }); write.resolve({ ok: true }); await pending
    expect(getSettingsStoreState()).toMatchObject({ busy: false, settings: { activeProfile: 'max' } })
  })
  it('does not reread or change the profile on rejected writes', async () => {
    await loadSettings(); vi.mocked(switchLocalActiveProfile).mockResolvedValue({ ok: false, error: 'rejected' })
    await expect(switchSettingsProfile('max')).rejects.toThrow('rejected')
    expect(readLocalSettings).toHaveBeenCalledTimes(1)
    expect(getSettingsStoreState().settings?.activeProfile).toBe('lite')
  })
  it('separates a successful switch from a failed read without repeating the POST', async () => {
    await loadSettings(); vi.mocked(switchLocalActiveProfile).mockResolvedValue({ ok: true })
    vi.mocked(readLocalSettings).mockRejectedValueOnce(new Error('offline'))
    await expect(switchSettingsProfile('max')).rejects.toThrow('已提交')
    expect(switchLocalActiveProfile).toHaveBeenCalledTimes(1)
    expect(getSettingsStoreState().loadState).toBe('error')
    await loadSettings(); expect(switchLocalActiveProfile).toHaveBeenCalledTimes(1)
  })
  it('uses the observed profile when a successful switch does not take effect', async () => {
    await loadSettings(); vi.mocked(switchLocalActiveProfile).mockResolvedValue({ ok: true })
    vi.mocked(readLocalSettings).mockResolvedValue({ ...mockSettings, activeProfile: 'pro' })
    await expect(switchSettingsProfile('max')).rejects.toThrow('当前模型档位仍是 pro')
    expect(getSettingsStoreState().settings?.activeProfile).toBe('pro')
  })
  it('isolates an old credential read and clears its retained projection', async () => {
    await loadSettings(); const old = deferred<typeof mockSettings>()
    vi.mocked(readLocalSettings).mockReturnValueOnce(old.promise)
    const first = loadSettings().catch(() => undefined)
    credentials.token = 'replacement'
    const next = deferred<typeof mockSettings>(); vi.mocked(readLocalSettings).mockReturnValueOnce(next.promise)
    const second = loadSettings()
    expect(getSettingsStoreState().settings).toBeNull()
    old.resolve({ ...mockSettings, model: 'old credential' }); await first
    expect(getSettingsStoreState().settings).toBeNull()
    next.resolve({ ...mockSettings, model: 'new credential' }); await second
    expect(getSettingsStoreState().settings?.model).toBe('new credential')
  })
  it('reset isolates a pending write, its follow-up read and busy cleanup', async () => {
    await loadSettings(); const write = deferred<{ ok: boolean }>()
    vi.mocked(switchLocalActiveProfile).mockReturnValueOnce(write.promise)
    const first = switchSettingsProfile('max')
    resetSettingsStore(); write.resolve({ ok: true })
    await expect(first).rejects.toThrow('配置连接已改变')
    expect(readLocalSettings).toHaveBeenCalledTimes(1)
    expect(getSettingsStoreState()).toMatchObject({ settings: null, busy: false, loadState: 'idle' })
  })
  it('publishes a successful save even after the editing page leaves', async () => {
    const session = createSettingsSession(mockSettings, { settings: loadSettings, savedSettings: readConfirmedSettings, schedules: async () => ({ ok: true, tasks: [] }) })
    session.connect(true); await session.refreshSettings()
    const submitted = { ...mockSettings, model: 'saved-after-navigation' }
    const write = deferred<Awaited<ReturnType<typeof saveLocalSettings>>>()
    vi.mocked(saveLocalSettings).mockReturnValueOnce(write.promise)
    const pending = session.run('save', async () => { await saveSettings(submitted); return { notice: 'saved', savedDraft: submitted, refresh: 'settings' as const } }, 'settings')
    session.connect(false)
    vi.mocked(readLocalSettings).mockResolvedValue(submitted)
    write.resolve({ ok: true, savedFields: ['model'], restartRequired: false, message: 'saved' })
    await pending
    expect(getSettingsStoreState()).toMatchObject({ busy: false, loadState: 'ready', settings: { model: submitted.model } })
    expect(session.getState()).toMatchObject({ connected: false, notice: '', settingsReady: false })
  })
  it('keeps save success separate from read failure and refuses another POST until GET succeeds', async () => {
    await loadSettings()
    vi.mocked(saveLocalSettings).mockResolvedValue({ ok: true, savedFields: ['model'], restartRequired: false, message: 'saved' })
    vi.mocked(readLocalSettings).mockRejectedValueOnce(new Error('after-write offline'))
    await expect(saveSettings(mockSettings)).resolves.toMatchObject({ ok: true })
    await expect(readConfirmedSettings()).rejects.toThrow('after-write offline')
    await expect(saveSettings(mockSettings)).rejects.toThrow('请先重新读取')
    await loadSettings()
    expect(saveLocalSettings).toHaveBeenCalledTimes(1)
  })

})
