import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SoulFiles, SoulProfileSummary, VaultReflection } from '../../types'

const api = vi.hoisted(() => ({
  fetchSoulFiles: vi.fn(),
  fetchSoulProfile: vi.fn(),
  fetchVaultReflections: vi.fn(),
  importSoul: vi.fn(),
  triggerVaultReflection: vi.fn(),
}))

vi.mock('../../adapters/localArcher', () => api)

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

describe('soulStore 生产 actions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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

  it('import 成功后重载 soul 自域并只发出跨 memory 事件', async () => {
    const events: StoreEvent[] = []
    onStoreEvent('soul:imported', (event) => events.push(event))

    await importSoulAction({ soulAnswers: [] })

    expect(api.fetchSoulProfile).toHaveBeenCalledOnce()
    expect(getSoulStoreState().importing).toBe(false)
    expect(events).toEqual([{ type: 'soul:imported', imported: 2 }])
  })

  it('reflection 成功后只重载 reflections 并发出跨 memory 事件', async () => {
    const events: StoreEvent[] = []
    onStoreEvent('soul:reflection-triggered', (event) => events.push(event))

    await triggerReflectionAction({ days: 7 })

    expect(api.fetchSoulProfile).not.toHaveBeenCalled()
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
})
