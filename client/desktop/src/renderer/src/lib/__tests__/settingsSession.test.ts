import { describe, it, expect, vi } from 'vitest'
import { createSettingsSession } from '../settingsSession'
import { mockArcher } from '../../adapters/mockArcher'
import type { ScheduledTask, SettingsDraft } from '../../types'

const initial = { ...mockArcher.settings, apiKey: '', model: 'original' }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r }); return { promise, resolve } }
async function fixture() {
  const readers = { settings: vi.fn().mockResolvedValue(initial), schedules: vi.fn().mockResolvedValue({ ok: true, tasks: [] }) }
  const session = createSettingsSession(initial, readers)
  session.connect(true)
  await session.refreshSettings()
  await session.refreshSchedules()
  return { session, readers }
}

describe('Settings editing session', () => {
  it('preserves edited fields and secrets through refresh while accepting untouched fields', async () => {
    const { session, readers } = await fixture()
    session.updateDraft('model', 'unsaved')
    session.updateDraft('apiKey', 'synthetic-secret')
    readers.settings.mockResolvedValue({ ...initial, model: 'remote', sessionsPath: '/new' })
    await session.refreshSettings()
    expect(session.getState().draft).toMatchObject({ model: 'unsaved', apiKey: 'synthetic-secret', sessionsPath: '/new' })
  })
  it('retains state on failed reads, blocks writes, and recovers', async () => {
    const { session, readers } = await fixture()
    session.updateDraft('model', 'unsaved')
    readers.settings.mockRejectedValueOnce(new Error('read failed'))
    await session.refreshSettings()
    const write = vi.fn()
    await session.run('save', write, 'settings')
    expect(write).not.toHaveBeenCalled()
    expect(session.getState()).toMatchObject({ settingsReady: false, settingsError: 'read failed', draft: { model: 'unsaved' } })
    await session.refreshSettings()
    expect(session.getState().settingsReady).toBe(true)
  })
  it('isolates an older settings response and a response after disconnect', async () => {
    const { session, readers } = await fixture()
    const old = deferred<SettingsDraft>()
    readers.settings.mockReturnValueOnce(old.promise).mockResolvedValueOnce({ ...initial, model: 'new' })
    const first = session.refreshSettings()
    await session.refreshSettings()
    old.resolve({ ...initial, model: 'old' }); await first
    expect(session.getState().draft.model).toBe('new')
    const late = deferred<SettingsDraft>(); readers.settings.mockReturnValueOnce(late.promise)
    const pending = session.refreshSettings(); session.connect(false)
    late.resolve(initial); await pending
    expect(session.getState().draft.model).toBe('new')
  })
  it('synchronously prevents duplicate writes and reloads after success', async () => {
    const { session, readers } = await fixture()
    const done = deferred<{ notice: string; refresh: 'settings'; savedDraft: SettingsDraft }>()
    const action = vi.fn(() => done.promise)
    session.updateDraft('model', 'submitted'); session.updateDraft('apiKey', 'synthetic')
    const submitted = session.getState().draft
    const first = session.run('save', action, 'settings')
    await session.run('save', action, 'settings')
    session.updateDraft('model', 'typed while saving')
    readers.settings.mockResolvedValue({ ...submitted, model: 'normalized', apiKey: undefined })
    done.resolve({ notice: 'saved', refresh: 'settings', savedDraft: submitted }); await first
    expect(action).toHaveBeenCalledTimes(1)
    expect(readers.settings).toHaveBeenCalledTimes(2)
    expect(session.getState()).toMatchObject({ busy: '', notice: 'saved', draft: { model: 'typed while saving', apiKey: '' } })
  })
  it('keeps write success separate from refresh failure and clears saved secrets', async () => {
    const { session, readers } = await fixture()
    session.updateDraft('apiKey', 'synthetic')
    const submitted = session.getState().draft
    readers.settings.mockRejectedValueOnce(new Error('offline'))
    await session.run('save', async () => ({ notice: 'saved', refresh: 'settings', savedDraft: submitted }), 'settings')
    expect(session.getState()).toMatchObject({ notice: 'saved', settingsError: 'offline', settingsReady: false, draft: { apiKey: '' } })
  })
  it('does not lose edits or read again after rejected writes', async () => {
    const { session, readers } = await fixture()
    session.updateDraft('model', 'unsaved')
    await session.run('save', async () => { throw new Error('rejected') }, 'settings')
    expect(readers.settings).toHaveBeenCalledTimes(1)
    expect(session.getState()).toMatchObject({ busy: '', warning: true, notice: 'rejected', draft: { model: 'unsaved' } })
  })
  it('retains schedules on failed receipts and suppresses stale reads', async () => {
    const { session, readers } = await fixture()
    const tasks = [{ id: 1, label: 'current' }] as ScheduledTask[]
    readers.schedules.mockResolvedValueOnce({ ok: true, tasks }); await session.refreshSchedules()
    readers.schedules.mockResolvedValueOnce({ ok: false, tasks: [] }); await session.refreshSchedules()
    expect(session.getState()).toMatchObject({ tasks, schedulesReady: false })
    const old = deferred<{ ok: boolean; tasks: ScheduledTask[] }>()
    readers.schedules.mockReturnValueOnce(old.promise)
    const pending = session.refreshSchedules()
    await session.refreshSchedules()
    old.resolve({ ok: true, tasks }); await pending
    expect(session.getState().tasks).toEqual([])
  })
  it('disconnect isolates a pending write, its refresh, and its notice', async () => {
    const { session, readers } = await fixture()
    const done = deferred<{ notice: string; refresh: 'settings' }>()
    const pending = session.run('save', () => done.promise, 'settings')
    session.connect(false); session.connect(true)
    done.resolve({ notice: 'late saved', refresh: 'settings' }); await pending
    expect(session.getState()).toMatchObject({ busy: '', notice: '', settingsReady: false })
    expect(readers.settings).toHaveBeenCalledTimes(1)
  })
})
