/**
 * L3.9d — storeSync 单元测试
 *
 * 验证 syncStoresFromAdapter 后，6 个领域 store 的 state 与 adapter 一致。
 * 用 mockArcher 作为完整 adapter 夹具。
 */

import { describe, expect, it, beforeEach } from 'vitest'
import { mockArcher } from '../../adapters/mockArcher'
import { syncStoresFromAdapter } from '../storeSync'
import { getMemoryStoreState, resetMemoryStore } from '../memoryStore'
import { getSoulStoreState, resetSoulStore } from '../soulStore'
import { getSessionStoreState, resetSessionStore } from '../sessionStore'
import { getInitiativeStoreState, resetInitiativeStore } from '../initiativeStore'
import { getThreadStoreState, resetThreadStore } from '../threadStore'

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

  it('sync 后 soulStore.profile 与 adapter.soulProfile 一致', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getSoulStoreState().profile).toEqual(mockArcher.soulProfile)
  })

  it('sync 后 soulStore.files 与 adapter.soulFiles 一致', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getSoulStoreState().files).toEqual(mockArcher.soulFiles)
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

  it('sync 后所有 store loadState 为 ready', () => {
    syncStoresFromAdapter(mockArcher)
    expect(getMemoryStoreState().loadState).toBe('ready')
    expect(getSoulStoreState().loadState).toBe('ready')
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
})
