import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MemoryItem, MemoryStats } from '../../types'

const api = vi.hoisted(() => ({
  batchResolvePendingMemory: vi.fn(),
  evolveMemory: vi.fn(),
  fetchMemoryGroups: vi.fn(),
  fetchMemoryItems: vi.fn(),
  fetchMemoryStats: vi.fn(),
  resolvePendingMemory: vi.fn(),
  updateMemory: vi.fn(),
}))

vi.mock('../../adapters/localArcher', () => api)

import {
  batchResolvePendingMemoryAction,
  evolveMemoryAction,
  getMemoryStoreState,
  loadAllMemory,
  resetMemoryStore,
  resolvePendingMemoryAction,
  updateMemoryAction,
} from '../memoryStore'
import { clearStoreEventBus, onStoreEvent, type StoreEvent } from '../storeEventBus'

const confirmedMemory: MemoryItem = {
  id: 7,
  status: 'confirmed',
  type: 'insight',
  content: '服务端权威记忆',
  confidence: '0.9',
  source: 'test',
}

const stats: MemoryStats = {
  dbPath: '/tmp/archer.db',
  activeCount: 1,
  pendingCount: 0,
  rejectedCount: 0,
  groups: { insight: 1 },
  contradictions: 0,
  stale: 0,
}

describe('memoryStore 领域级刷新', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    clearStoreEventBus()
    resetMemoryStore()
    api.fetchMemoryItems.mockResolvedValue([confirmedMemory])
    api.fetchMemoryStats.mockResolvedValue(stats)
    api.fetchMemoryGroups.mockResolvedValue({
      insight: {
        label: 'insight',
        icon: 'brain',
        types: ['insight'],
        question: '测试问题',
        count: 1,
        memories: [confirmedMemory],
      },
    })
    api.batchResolvePendingMemory.mockResolvedValue({ ok: true, count: 1 })
    api.evolveMemory.mockResolvedValue({ ok: true, id: confirmedMemory.id })
    api.resolvePendingMemory.mockResolvedValue({ ok: true, id: confirmedMemory.id })
    api.updateMemory.mockResolvedValue({ ok: true, id: confirmedMemory.id })
  })

  it('loadAllMemory 从 memory 端点重载 items，而不是复用旧 store 快照', async () => {
    await loadAllMemory()

    expect(api.fetchMemoryItems).toHaveBeenCalledOnce()
    expect(getMemoryStoreState().items).toEqual([confirmedMemory])
    expect(getMemoryStoreState().stats).toEqual(stats)
  })

  it('batch resolve 后重载 memory 领域并发出投影事件', async () => {
    const events: StoreEvent[] = []
    onStoreEvent('memory:batch-resolved', (event) => events.push(event))

    await batchResolvePendingMemoryAction(true)

    expect(api.fetchMemoryItems).toHaveBeenCalledOnce()
    expect(getMemoryStoreState().items).toEqual([confirmedMemory])
    expect(events).toEqual([{ type: 'memory:batch-resolved', accepted: true }])
  })

  it('evolve 后重载 memory 领域并发出投影事件', async () => {
    const events: StoreEvent[] = []
    onStoreEvent('memory:evolved', (event) => events.push(event))

    await evolveMemoryAction(confirmedMemory.id, '更新后的记忆')

    expect(api.fetchMemoryItems).toHaveBeenCalledOnce()
    expect(getMemoryStoreState().items).toEqual([confirmedMemory])
    expect(events).toEqual([{ type: 'memory:evolved', id: confirmedMemory.id }])
  })

  it('update 后更新 memoryStore 并发出投影事件', async () => {
    await loadAllMemory()
    const events: StoreEvent[] = []
    onStoreEvent('memory:updated', (event) => events.push(event))

    await updateMemoryAction(confirmedMemory.id, '更新后的长期记忆')

    expect(getMemoryStoreState().items[0].content).toBe('更新后的长期记忆')
    expect(events).toEqual([{ type: 'memory:updated', id: confirmedMemory.id }])
  })

  it('服务端拒绝 resolve 时保留本地 memory 快照', async () => {
    await loadAllMemory()
    api.resolvePendingMemory.mockResolvedValueOnce({ ok: false })

    await expect(resolvePendingMemoryAction(confirmedMemory.id, true)).rejects.toThrow('无待处理记忆被更新')

    expect(getMemoryStoreState().items).toEqual([confirmedMemory])
  })

  it('服务端拒绝 update 时不覆盖本地内容', async () => {
    await loadAllMemory()
    api.updateMemory.mockResolvedValueOnce({ ok: false, id: confirmedMemory.id })

    await expect(updateMemoryAction(confirmedMemory.id, '不应写入的内容')).rejects.toThrow('记忆更新失败')

    expect(getMemoryStoreState().items).toEqual([confirmedMemory])
  })
})
