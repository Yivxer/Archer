/** Page-scoped editing session; server reads never own an unsaved form. */
import type { ScheduledTask, SettingsDraft } from '../types'
import { createExternalStore } from './externalStore'

const clean = (settings: SettingsDraft): SettingsDraft => ({ ...settings, apiKey: '' })
const message = (error: unknown): string => error instanceof Error ? error.message : String(error)

export function rebaseSettings(draft: SettingsDraft, baseline: SettingsDraft, incoming: SettingsDraft): SettingsDraft {
  const next = clean(incoming)
  const profileFields = ['activeProfile', 'provider', 'baseUrl', 'model', 'apiKey', 'apiKeyPreview'] as const
  const profileChanged = profileFields.some(key => draft[key] !== baseline[key])
  for (const key of profileFields) {
    if (profileChanged || draft[key] !== baseline[key]) Object.assign(next, { [key]: draft[key] })
  }
  for (const key of ['memoryDbPath', 'sessionsPath'] as const) {
    if (draft[key] !== baseline[key]) next[key] = draft[key]
  }
  return next
}

type ActionResult = {
  notice: string
  warning?: boolean
  refresh?: 'settings' | 'schedules'
  savedDraft?: SettingsDraft
  draft?: SettingsDraft
}
interface SettingsReaders {
  settings: () => Promise<SettingsDraft>
  schedules: () => Promise<{ ok: boolean; tasks: ScheduledTask[] }>
}

export function createSettingsSession(initial: SettingsDraft, readers: SettingsReaders) {
  const store = createExternalStore({
    draft: clean(initial), baseline: clean(initial), connected: false,
    settingsReady: false, settingsLoading: false, settingsError: '',
    tasks: [] as ScheduledTask[], schedulesReady: false, scheduleLoading: false, scheduleError: '',
    busy: '', notice: '', warning: false,
  })
  let epoch = 0
  let settingsRead = 0
  let schedulesRead = 0
  const patch = (values: Partial<ReturnType<typeof store.getState>>): void => store.setState(s => ({ ...s, ...values }))

  async function readSettings(savedDraft?: SettingsDraft): Promise<boolean> {
    if (!store.getState().connected) return false
    const id = ++settingsRead
    patch({ settingsLoading: true, settingsError: '' })
    try {
      const incoming = await readers.settings()
      if (id !== settingsRead) return false
      store.setState(s => ({ ...s, draft: rebaseSettings(s.draft, savedDraft ?? s.baseline, incoming), baseline: clean(incoming), settingsReady: true }))
      return true
    } catch (error) {
      if (id === settingsRead) patch({ settingsReady: false, settingsError: message(error) })
      return false
    } finally {
      if (id === settingsRead) patch({ settingsLoading: false })
    }
  }

  async function readSchedules(): Promise<boolean> {
    if (!store.getState().connected) return false
    const id = ++schedulesRead
    patch({ scheduleLoading: true, scheduleError: '' })
    try {
      const result = await readers.schedules()
      if (!result.ok || !Array.isArray(result.tasks)) throw new Error('读取定时任务失败')
      if (id !== schedulesRead) return false
      patch({ tasks: result.tasks, schedulesReady: true })
      return true
    } catch (error) {
      if (id === schedulesRead) patch({ schedulesReady: false, scheduleError: message(error) })
      return false
    } finally {
      if (id === schedulesRead) patch({ scheduleLoading: false })
    }
  }

  function connect(connected: boolean): void {
    epoch++; settingsRead++; schedulesRead++
    patch({ connected, busy: '', settingsReady: false, schedulesReady: false, settingsLoading: false, scheduleLoading: false })
  }

  async function run(name: string, action: () => Promise<ActionResult>, requires?: 'settings' | 'schedules'): Promise<boolean> {
    const state = store.getState()
    if (!state.connected || state.busy || (requires === 'settings' && !state.settingsReady) || (requires === 'schedules' && !state.schedulesReady)) return false
    const generation = epoch
    settingsRead++; schedulesRead++
    patch({ busy: name, notice: '', warning: false, settingsLoading: false, scheduleLoading: false })
    try {
      const result = await action()
      if (generation !== epoch) return false
      patch({ notice: result.notice, warning: Boolean(result.warning) })
      if (result.draft) patch({ draft: result.draft })
      // A successful write stays successful even if its following GET fails.
      if (result.savedDraft) {
        store.setState(s => ({ ...s, baseline: clean(result.savedDraft!), draft: { ...s.draft, apiKey: s.draft.apiKey === result.savedDraft!.apiKey ? '' : s.draft.apiKey } }))
      }
      if (result.refresh === 'settings') await readSettings(result.savedDraft ? clean(result.savedDraft) : undefined)
      if (result.refresh === 'schedules') await readSchedules()
      return generation === epoch
    } catch (error) {
      if (generation === epoch) patch({ notice: message(error), warning: true })
      return false
    } finally {
      if (generation === epoch) patch({ busy: '' })
    }
  }

  return {
    ...store, connect, run,
    refreshSettings: (): Promise<boolean> => store.getState().busy ? Promise.resolve(false) : readSettings(),
    refreshSchedules: (): Promise<boolean> => store.getState().busy ? Promise.resolve(false) : readSchedules(),
    updateDraft: (key: keyof SettingsDraft, value: string): void => store.setState(s => ({ ...s, draft: { ...s.draft, [key]: value }, notice: '' })),
    resetDraft: (): void => { if (!store.getState().busy) patch({ draft: clean(store.getState().baseline), notice: '已恢复为当前读取到的配置。' }) },
    notify: (notice: string, warning = false): void => patch({ notice, warning }),
  }
}
