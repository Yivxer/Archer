import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SoulFiles, SoulProfileSummary, VaultReflection } from '../../types'

const api = vi.hoisted(() => ({
  fetchSoulFiles: vi.fn(),
  fetchSoulProfile: vi.fn(),
  fetchVaultReflections: vi.fn(),
  importSoul: vi.fn(),
  triggerVaultReflection: vi.fn(),
}))

vi.mock('../../adapters/soulAdapter', () => api)

import {
  getSoulStoreState,
  importSoulAction,
  loadAllSoul,
  resetSoulStore,
  triggerReflectionAction,
} from '../soulStore'
import { clearStoreEventBus, onStoreEvent, type StoreEvent } from '../storeEventBus'

const profile: SoulProfileSummary = { empty: false, sections: [] }
const files = { 'SOUL.md': '# Soul' } as SoulFiles
const reflection = { id: 1, note_path: 'note.md' } as VaultReflection

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

describe('soulStore 生产 actions', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    clearStoreEventBus()
    resetSoulStore()
    api.fetchSoulProfile.mockResolvedValue(profile)
    api.fetchSoulFiles.mockResolvedValue(files)
    api.fetchVaultReflections.mockResolvedValue({ ok: true, reflections: [reflection] })
    api.importSoul.mockResolvedValue({ ok: true, imported: 2, pendingIds: [1, 2], message: '已导入 2 条' })
    api.triggerVaultReflection.mockResolvedValue({ ok: true, pending_ids: [3] })
  })

  it('loadAllSoul 只从 soul 端点重载 profile、files 和 reflections', async () => {
    await loadAllSoul()

    expect(api.fetchSoulProfile).toHaveBeenCalledOnce()
    expect(api.fetchSoulFiles).toHaveBeenCalledOnce()
    expect(api.fetchVaultReflections).toHaveBeenCalledOnce()
    expect(getSoulStoreState()).toMatchObject({ profile, files, reflections: [reflection], loadState: 'ready' })
  })

  it('coalesces concurrent reloads into one domain request', async () => {
    const pending = deferred<SoulProfileSummary>()
    api.fetchSoulProfile.mockReturnValueOnce(pending.promise)
    const first = loadAllSoul()
    const second = loadAllSoul()
    expect(api.fetchSoulProfile).toHaveBeenCalledOnce()
    pending.resolve(profile)
    await Promise.all([first, second])
    expect(getSoulStoreState().loadState).toBe('ready')
  })

  it('ignores a superseded response after a forced refresh', async () => {
    const older = deferred<SoulProfileSummary>()
    api.fetchSoulProfile.mockReturnValueOnce(older.promise)
    const first = loadAllSoul()
    const latest = { empty: false, sections: [{ id: 'new', label: '当前', items: ['最新档案'] }] }
    api.fetchSoulProfile.mockResolvedValueOnce(latest)
    await loadAllSoul({ force: true })
    older.resolve({ empty: true, sections: [] })
    await first
    expect(getSoulStoreState().profile).toEqual(latest)
  })

  it('invalidates a pending response when the store is reset', async () => {
    const pending = deferred<SoulProfileSummary>()
    api.fetchSoulProfile.mockReturnValueOnce(pending.promise)
    const request = loadAllSoul()
    resetSoulStore()
    pending.resolve(profile)
    await request
    expect(getSoulStoreState().profile).toBeNull()
    expect(getSoulStoreState().loadState).toBe('idle')
  })

  it('does not turn a successful newer load into an error when an old request fails', async () => {
    const older = deferred<SoulProfileSummary>()
    api.fetchSoulProfile.mockReturnValueOnce(older.promise)
    const first = loadAllSoul()
    await loadAllSoul({ force: true })
    older.reject(new Error('旧请求超时'))
    await first
    expect(getSoulStoreState()).toMatchObject({ profile, loadState: 'ready', error: '' })
  })

  it('retains the last coherent snapshot when one endpoint fails', async () => {
    await loadAllSoul()
    api.fetchSoulFiles.mockRejectedValueOnce(new Error('文件读取失败'))
    api.fetchSoulProfile.mockResolvedValueOnce({ empty: true, sections: [] })
    await loadAllSoul()
    expect(getSoulStoreState()).toMatchObject({ profile, files, loadState: 'error', error: '文件读取失败' })
  })

  it('does not report ready when the reflection endpoint returns ok=false', async () => {
    api.fetchVaultReflections.mockResolvedValueOnce({ ok: false, reflections: [] })
    await loadAllSoul()
    expect(getSoulStoreState().loadState).toBe('error')
    expect(getSoulStoreState().profile).toBeNull()
  })

  it('refreshes after import even when a pre-import read is still pending', async () => {
    const older = deferred<SoulProfileSummary>()
    api.fetchSoulProfile.mockReturnValueOnce(older.promise)
    const beforeImport = loadAllSoul()
    const imported = { empty: false, sections: [{ id: 'imported', label: '已导入', items: ['新依据'] }] }
    api.fetchSoulProfile.mockResolvedValueOnce(imported)
    await importSoulAction({ initialAnswers: { sample: '合成答案' } })
    older.resolve({ empty: true, sections: [] })
    await beforeImport
    expect(getSoulStoreState().profile).toEqual(imported)
    expect(getSoulStoreState().importing).toBe(false)
  })

  it('import 成功后重载 soul 自域并只发出跨 memory 事件', async () => {
    const events: StoreEvent[] = []
    onStoreEvent('soul:imported', (event) => events.push(event))

    await importSoulAction({ soulAnswers: [] })

    expect(api.fetchSoulProfile).toHaveBeenCalledOnce()
    expect(getSoulStoreState().importing).toBe(false)
    expect(events).toEqual([{ type: 'soul:imported', imported: 2 }])
  })

  it('reflection 成功后刷新 Soul 域并发出跨 memory 事件', async () => {
    const events: StoreEvent[] = []
    onStoreEvent('soul:reflection-triggered', (event) => events.push(event))

    await triggerReflectionAction({ days: 7 })

    expect(api.fetchSoulProfile).toHaveBeenCalledOnce()
    expect(api.fetchVaultReflections).toHaveBeenCalledOnce()
    expect(getSoulStoreState().reflections).toEqual([reflection])
    expect(events).toEqual([{ type: 'soul:reflection-triggered' }])
  })

  it('服务端拒绝 import 时不发出跨域事件', async () => {
    const events: StoreEvent[] = []
    onStoreEvent('soul:imported', (event) => events.push(event))
    api.importSoul.mockResolvedValueOnce({ ok: false, imported: 0, pendingIds: [], message: '导入失败' })

    await expect(importSoulAction({ soulAnswers: [] })).rejects.toThrow('导入失败')

    expect(api.fetchSoulProfile).not.toHaveBeenCalled()
    expect(events).toEqual([])
  })

  it('does not refresh or emit a completion event when reflection is rejected', async () => {
    const events: StoreEvent[] = []
    onStoreEvent('soul:reflection-triggered', (event) => events.push(event))
    api.triggerVaultReflection.mockResolvedValueOnce({ ok: false })
    await expect(triggerReflectionAction({ days: 7 })).rejects.toThrow('笔记结晶触发失败')
    expect(api.fetchSoulProfile).not.toHaveBeenCalled()
    expect(events).toEqual([])
  })

  it('keeps successful import acknowledgement separate from a failed refresh', async () => {
    const events: StoreEvent[] = []
    onStoreEvent('soul:imported', (event) => events.push(event))
    api.fetchSoulFiles.mockRejectedValueOnce(new Error('导入后刷新失败'))
    await importSoulAction({ initialAnswers: {} })
    expect(getSoulStoreState()).toMatchObject({ importing: false, importMessage: '已导入 2 条', loadState: 'error', error: '导入后刷新失败' })
    expect(events).toEqual([{ type: 'soul:imported', imported: 2 }])
  })
})
