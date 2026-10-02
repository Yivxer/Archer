/**
 * L3.9d — storeSync 单元测试
 *
 * 验证 syncStoresFromAdapter 后，兼容领域与 adapter 一致、Soul 状态不被快照覆盖。
 * 用 mockArcher 作为完整 adapter 夹具。
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import { mockArcher } from '../../adapters/mockArcher'
import { projectMemoryStoreToAdapter, syncStoresFromAdapter } from '../storeSync'
import { getMemoryStoreState, resetMemoryStore } from '../memoryStore'
import { getSoulStoreState, loadAllSoul, resetSoulStore } from '../soulStore'
import { getSessionStoreState, resetSessionStore } from '../sessionStore'
import { getInitiativeStoreState, resetInitiativeStore } from '../initiativeStore'
import { getThreadStoreState, resetThreadStore } from '../threadStore'

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

  it('sync 后 memoryStore.items 与 adapter.memory 一致', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getMemoryStoreState().items).toEqual(mockArcher.memory)
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
    expect(getMemoryStoreState().loadState).toBe('ready')
    expect(getSessionStoreState().loadState).toBe('ready')
    expect(getInitiativeStoreState().loadState).toBe('ready')
    expect(getThreadStoreState().loadState).toBe('ready')
  })

  it('二次 sync 替换而非追加', () => {
    syncStoresFromAdapter(mockArcher)
    syncStoresFromAdapter(mockArcher)
    expect(getMemoryStoreState().items).toEqual(mockArcher.memory)
    expect(getThreadStoreState().items).toEqual(mockArcher.threads)
  })

  it('sync 后 threadStore.currentThreadId 仍为 null（未设置活跃 thread）', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getThreadStoreState().currentThreadId).toBeNull()
  })

  it('memory 领域事件只投影 memory 与计数，不替换其他 adapter 领域', () => {
    const memory = mockArcher.memory.slice(1)

    const next = projectMemoryStoreToAdapter(mockArcher, memory)

    expect(next).not.toBe(mockArcher)
    expect(next.memory).toBe(memory)
    expect(next.status.memoryCount).toBe(memory.filter((item) => item.status === 'confirmed').length)
    expect(next.status.pendingMemoryCount).toBe(memory.filter((item) => item.status === 'pending').length)
    expect(next.sessions).toBe(mockArcher.sessions)
    expect(next.initiativeShadow).toBe(mockArcher.initiativeShadow)
  })

  it('ignores legacy Soul fields without overwriting the loaded store', async () => {
    await loadAllSoul()
    const previous = getSoulStoreState()
    const legacy = Object.assign({}, mockArcher, { soulProfile: { empty: true, sections: [] }, soulFiles: {} })
    syncStoresFromAdapter(legacy)
    expect(getSoulStoreState()).toBe(previous)
  })
})
