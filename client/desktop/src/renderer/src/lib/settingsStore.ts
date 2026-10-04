/** Last confirmed server configuration. Unsaved edits belong to settingsSession. */
import { readLocalSettings, switchLocalActiveProfile, saveLocalSettings, saveLocalProfileSettings } from '../adapters/settingsAdapter'
import { getDesktopApiToken } from '../adapters/localArcher'
import type { SettingsDraft, SettingsSaveResult } from '../types'
import { createExternalStore, useExternalStore, type LoadState } from './externalStore'

export const emptySettings: SettingsDraft = {
  activeProfile: 'lite', provider: '', baseUrl: '', model: '', apiKey: '', apiKeyPreview: '',
  configPath: '', memoryDbPath: '', sessionsPath: '', modelProfiles: [],
}
export interface SettingsStoreState {
  settings: SettingsDraft | null
  loadState: LoadState
  error: string
  busy: boolean
}
const initial: SettingsStoreState = { settings: null, loadState: 'idle', error: '', busy: false }
const store = createExternalStore<SettingsStoreState>(initial)
let generation = 0
let epoch = 0
let credential = ''
let pending: Promise<SettingsDraft> | null = null
export const getSettingsStoreState = store.getState
export const subscribeSettingsStore = store.subscribe
export function useSettingsStore<T>(selector: (state: SettingsStoreState) => T): T {
  return useExternalStore(store, selector)
}
export function resetSettingsStore(): void {
  generation++; epoch++; pending = null; credential = ''
  store.setState(() => initial)
}
export function loadSettings(options: { force?: boolean } = {}): Promise<SettingsDraft> {
  if (store.getState().busy) return Promise.reject(new Error('配置正在保存，请稍后刷新。'))
  return readSettings(options.force)
}
function readSettings(force = false): Promise<SettingsDraft> {
  const token = getDesktopApiToken()
  if (credential !== token) { resetSettingsStore(); credential = token }
  if (pending && !force) return pending
  const id = ++generation
  store.setState(s => ({ ...s, loadState: 'loading', error: '' }))
  pending = (async () => {
    try {
      const incoming = await readLocalSettings()
      if (id !== generation || token !== getDesktopApiToken()) throw new Error('配置读取已过期')
      const settings = { ...incoming, apiKey: '' }
      store.setState(s => ({ ...s, settings, loadState: 'ready', error: '' }))
      return settings
    } catch (error) {
      if (id === generation && token === getDesktopApiToken()) {
        store.setState(s => ({ ...s, loadState: 'error', error: error instanceof Error ? error.message : String(error) }))
      }
      throw error
    } finally {
      if (id === generation) pending = null
    }
  })()
  return pending
}
export function readConfirmedSettings(): Promise<SettingsDraft> {
  const state = store.getState()
  if (state.loadState !== 'ready' || !state.settings || credential !== getDesktopApiToken()) {
    return Promise.reject(new Error(state.error || '配置尚未回读确认，请重试读取。'))
  }
  return Promise.resolve(state.settings)
}

async function mutateSettings<T extends { ok: boolean }>(action: () => Promise<T>): Promise<T> {
  const state = store.getState()
  if (state.busy || state.loadState !== 'ready' || credential !== getDesktopApiToken()) {
    throw new Error('请先重新读取配置，再保存或切换模型。')
  }
  const currentEpoch = epoch
  const token = getDesktopApiToken()
  generation++; pending = null
  store.setState(s => ({ ...s, busy: true }))
  try {
    const result = await action()
    if (currentEpoch !== epoch || token !== getDesktopApiToken()) throw new Error('配置连接已改变，请重新读取。')
    // A successful POST stays successful when its following GET fails. The read
    // error remains in the store; consumers can retry GET without repeating POST.
    if (result.ok) await readSettings(true).catch(() => {})
    if (currentEpoch !== epoch || token !== getDesktopApiToken()) throw new Error('配置连接已改变，请重新读取。')
    return result
  } catch (error) {
    if (currentEpoch === epoch && token === getDesktopApiToken()) {
      store.setState(s => ({ ...s, loadState: 'error', error: error instanceof Error ? error.message : String(error) }))
    }
    throw error
  } finally {
    if (currentEpoch === epoch) store.setState(s => ({ ...s, busy: false }))
  }
}

export function saveSettings(settings: SettingsDraft): Promise<SettingsSaveResult> {
  return mutateSettings(() => saveLocalSettings(settings))
}
export function saveSettingsProfile(payload: Parameters<typeof saveLocalProfileSettings>[0]): ReturnType<typeof saveLocalProfileSettings> {
  return mutateSettings(() => saveLocalProfileSettings(payload))
}
export async function switchSettingsProfile(profileId: 'lite' | 'pro' | 'max'): Promise<void> {
  const result = await mutateSettings(() => switchLocalActiveProfile(profileId))
  if (!result.ok) throw new Error(result.error || result.message || '模型切换未保存')
  try {
    const settings = await readConfirmedSettings()
    if (settings.activeProfile !== profileId) throw new Error(`当前模型档位仍是 ${settings.activeProfile}`)
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    throw new Error(`模型切换已提交，但回读未确认：${reason}；请刷新配置，勿重复提交。`)
  }
}
