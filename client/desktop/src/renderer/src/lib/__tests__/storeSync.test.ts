/**
 * L3.9d — storeSync 单元测试
 *
 * 验证 syncStoresFromAdapter 后，兼容领域与 adapter 一致、Soul 状态不被快照覆盖。
 * 用 mockArcher 作为完整 adapter 夹具。
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import { mockArcher } from '../../adapters/mockArcher'
import { syncStoresFromAdapter } from '../storeSync'
import { getMemoryStoreState, loadAllMemory, resetMemoryStore } from '../memoryStore'
import { getSoulStoreState, loadAllSoul, resetSoulStore } from '../soulStore'
import { getSessionStoreState, resetSessionStore } from '../sessionStore'
import { getInitiativeStoreState, resetInitiativeStore } from '../initiativeStore'
import { getThreadStoreState, resetThreadStore } from '../threadStore'

vi.mock('../../adapters/memoryAdapter', () => ({
  fetchMemoryItems: vi.fn(async () => []),
  fetchMemoryStats: vi.fn(async () => ({ activeCount: 0, pendingCount: 0 })),
  fetchMemoryGroups: vi.fn(async () => ({})),
}))

vi.mock('../../adapters/soulAdapter', () => ({
  fetchSoulProfile: vi.fn(async () => ({ empty: false, sections: [] })),
  fetchSoulFiles: vi.fn(async () => ({ 'SOUL.md': '# Current' })),
  fetchVaultReflections: vi.fn(async () => ({ ok: true, reflections: [] })),
}))

describe('storeSync — L3.9a syncStoresFromAdapter', () => {
  beforeEach(() => {
    resetMemoryStore()
    resetSoulStore()
    resetSessionStore()
    resetInitiativeStore()
    resetThreadStore()
  })

  it('compatibility snapshots do not initialize Memory authority', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getMemoryStoreState().items).toEqual([])
    expect(getMemoryStoreState().loadState).toBe('idle')
  })

  it('compatibility snapshots do not initialize Soul authority', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getSoulStoreState().profile).toBeNull()
    expect(getSoulStoreState().loadState).toBe('idle')
  })

  it('sync 后 sessionStore.items 与 adapter.sessions 一致', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getSessionStoreState().items).toEqual(mockArcher.sessions)
  })

  it('sync 后 initiativeStore.review 与 adapter.initiativeShadow 一致', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getInitiativeStoreState().review).toEqual(mockArcher.initiativeShadow)
  })

  it('sync 后 threadStore.items 与 adapter.threads 一致', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getThreadStoreState().items).toEqual(mockArcher.threads)
  })

  it('sync 后兼容 store loadState 为 ready', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getSessionStoreState().loadState).toBe('ready')
    expect(getInitiativeStoreState().loadState).toBe('ready')
    expect(getThreadStoreState().loadState).toBe('ready')
  })

  it('二次 sync 替换而非追加', () => {
    syncStoresFromAdapter(mockArcher)
    syncStoresFromAdapter(mockArcher)
    expect(getThreadStoreState().items).toEqual(mockArcher.threads)
  })

  it('sync 后 threadStore.currentThreadId 仍为 null（未设置活跃 thread）', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getThreadStoreState().currentThreadId).toBeNull()
  })

  it('ignores legacy memory fields without overwriting the loaded store', async () => {
    await loadAllMemory()
    const previous = getMemoryStoreState()
    syncStoresFromAdapter(Object.assign({}, mockArcher, { memory: [{ id: 777, content: 'stale' }] }))
    expect(getMemoryStoreState()).toBe(previous)
  })

  it('ignores legacy Soul fields without overwriting the loaded store', async () => {
    await loadAllSoul()
    const previous = getSoulStoreState()
    const legacy = Object.assign({}, mockArcher, { soulProfile: { empty: true, sections: [] }, soulFiles: {} })
    syncStoresFromAdapter(legacy)
    expect(getSoulStoreState()).toBe(previous)
  })
})
