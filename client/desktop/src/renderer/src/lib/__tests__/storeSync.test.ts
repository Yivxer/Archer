/**
 * L3.9d — storeSync 单元测试
 *
 * 验证 syncStoresFromAdapter 后，6 个领域 store 的 state 与 adapter 一致。
 * 用 mockArcher 作为完整 adapter 夹具。
 */

import { describe, expect, it, beforeEach } from 'vitest'
import { mockArcher } from '../../adapters/mockArcher'
import { projectMemoryStoreToAdapter, projectSoulStoreToAdapter, syncStoresFromAdapter } from '../storeSync'
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

  it('memory 领域事件只投影 memory 与计数，不替换其他 adapter 领域', () => {
    const memory = mockArcher.memory.slice(1)

    const next = projectMemoryStoreToAdapter(mockArcher, memory)

    expect(next).not.toBe(mockArcher)
    expect(next.memory).toBe(memory)
    expect(next.status.memoryCount).toBe(memory.filter((item) => item.status === 'confirmed').length)
    expect(next.status.pendingMemoryCount).toBe(memory.filter((item) => item.status === 'pending').length)
    expect(next.sessions).toBe(mockArcher.sessions)
    expect(next.soulProfile).toBe(mockArcher.soulProfile)
    expect(next.initiativeShadow).toBe(mockArcher.initiativeShadow)
  })

  it('soul 领域事件只投影 profile/files，不替换 memory 与 sessions', () => {
    const profile = { empty: false, sections: [] }
    const files = { ...mockArcher.soulFiles, 'SOUL.md': '# Updated Soul' }

    const next = projectSoulStoreToAdapter(mockArcher, { profile, files })

    expect(next.soulProfile).toBe(profile)
    expect(next.soulFiles).toBe(files)
    expect(next.memory).toBe(mockArcher.memory)
    expect(next.sessions).toBe(mockArcher.sessions)
    expect(next.initiativeShadow).toBe(mockArcher.initiativeShadow)
  })
})
