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

vi.mock('../../adapters/memoryAdapter', () => api)

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
    vi.resetAllMocks()
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

  it('batch resolve 后重载 memory 领域并发出领域事件', async () => {
    const events: StoreEvent[] = []
    onStoreEvent('memory:batch-resolved', (event) => events.push(event))

    await batchResolvePendingMemoryAction(true)

    expect(api.fetchMemoryItems).toHaveBeenCalledOnce()
    expect(getMemoryStoreState().items).toEqual([confirmedMemory])
    expect(events).toEqual([{ type: 'memory:batch-resolved', accepted: true }])
  })

  it('evolve 后重载 memory 领域并发出领域事件', async () => {
    const events: StoreEvent[] = []
    onStoreEvent('memory:evolved', (event) => events.push(event))

    await evolveMemoryAction(confirmedMemory.id, '更新后的记忆')

    expect(api.fetchMemoryItems).toHaveBeenCalledOnce()
    expect(getMemoryStoreState().items).toEqual([confirmedMemory])
    expect(events).toEqual([{ type: 'memory:evolved', id: confirmedMemory.id }])
  })

  it('update 后更新 memoryStore 并发出领域事件', async () => {
    await loadAllMemory()
    const events: StoreEvent[] = []
    onStoreEvent('memory:updated', (event) => events.push(event))

    api.fetchMemoryItems.mockResolvedValueOnce([{ ...confirmedMemory, content: '更新后的长期记忆' }])
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

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

describe('memory snapshot ordering', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    resetMemoryStore()
    clearStoreEventBus()
    api.fetchMemoryItems.mockResolvedValue([confirmedMemory])
    api.fetchMemoryStats.mockResolvedValue(stats)
    api.fetchMemoryGroups.mockResolvedValue({})
    api.resolvePendingMemory.mockResolvedValue({ ok: true })
    api.updateMemory.mockResolvedValue({ ok: true })
  })

  it('coalesces concurrent ordinary loads', async () => {
    const old = deferred<MemoryItem[]>()
    api.fetchMemoryItems.mockReturnValueOnce(old.promise)
    const first = loadAllMemory()
    const second = loadAllMemory()
    expect(first).toBe(second)
    expect(api.fetchMemoryItems).toHaveBeenCalledOnce()
    old.resolve([])
    await Promise.all([first, second])
  })

  it('forced refresh discards an older successful snapshot', async () => {
    const old = deferred<MemoryItem[]>()
    api.fetchMemoryItems.mockReturnValueOnce(old.promise)
    const first = loadAllMemory()
    await loadAllMemory({ force: true })
    old.resolve([])
    await first
    expect(getMemoryStoreState().items).toEqual([confirmedMemory])
  })

  it('older failure cannot overwrite a successful refresh', async () => {
    const old = deferred<MemoryItem[]>()
    api.fetchMemoryItems.mockReturnValueOnce(old.promise)
    const first = loadAllMemory()
    await loadAllMemory({ force: true })
    old.reject(new Error('stale failure'))
    await first
    expect(getMemoryStoreState().loadState).toBe('ready')
    expect(getMemoryStoreState().error).toBe('')
  })

  it('reset invalidates pending reads', async () => {
    const old = deferred<MemoryItem[]>()
    api.fetchMemoryItems.mockReturnValueOnce(old.promise)
    const first = loadAllMemory()
    resetMemoryStore()
    old.resolve([confirmedMemory])
    await first
    expect(getMemoryStoreState().items).toEqual([])
    expect(getMemoryStoreState().loadState).toBe('idle')
  })

  it('failed refresh retains the last complete snapshot', async () => {
    await loadAllMemory()
    const previous = getMemoryStoreState()
    api.fetchMemoryGroups.mockRejectedValueOnce(new Error('groups unavailable'))
    api.fetchMemoryItems.mockResolvedValueOnce([])
    await loadAllMemory({ force: true })
    expect(getMemoryStoreState().items).toBe(previous.items)
    expect(getMemoryStoreState().stats).toBe(previous.stats)
    expect(getMemoryStoreState().groups).toBe(previous.groups)
    expect(getMemoryStoreState().loadState).toBe('error')
  })

  it('accepted memory remains in the authoritative list and groups', async () => {
    api.fetchMemoryItems.mockResolvedValueOnce([{ ...confirmedMemory, status: 'pending' }])
    await loadAllMemory()
    api.fetchMemoryGroups.mockResolvedValueOnce({ insight: { label: 'insight', icon: 'brain', types: ['insight'], question: '', count: 1, memories: [confirmedMemory] } })
    await resolvePendingMemoryAction(confirmedMemory.id, true)
    expect(getMemoryStoreState().items).toEqual([confirmedMemory])
    expect(getMemoryStoreState().groups[0].memories).toEqual([confirmedMemory])
    expect(getMemoryStoreState().busyIds.size).toBe(0)
  })

  it('edit refreshes group content as well as the list', async () => {
    await loadAllMemory()
    const edited = { ...confirmedMemory, content: '服务端更新后的记忆内容' }
    api.fetchMemoryItems.mockResolvedValueOnce([edited])
    api.fetchMemoryGroups.mockResolvedValueOnce({ insight: { label: 'insight', icon: 'brain', types: ['insight'], question: '', count: 1, memories: [edited] } })
    await updateMemoryAction(edited.id, edited.content)
    expect(getMemoryStoreState().items).toEqual([edited])
    expect(getMemoryStoreState().groups[0].memories).toEqual([edited])
  })

  it('write completion supersedes an in-flight old read', async () => {
    const old = deferred<MemoryItem[]>()
    api.fetchMemoryItems.mockReturnValueOnce(old.promise)
    const first = loadAllMemory()
    await resolvePendingMemoryAction(confirmedMemory.id, true)
    old.resolve([{ ...confirmedMemory, status: 'pending' }])
    await first
    expect(getMemoryStoreState().items).toEqual([confirmedMemory])
  })

  it('successful write and failed reload stay distinguishable', async () => {
    await loadAllMemory()
    api.fetchMemoryItems.mockRejectedValueOnce(new Error('refresh unavailable'))
    const events: StoreEvent[] = []
    onStoreEvent('memory:resolved', event => events.push(event))
    await expect(resolvePendingMemoryAction(confirmedMemory.id, true)).resolves.toBeUndefined()
    expect(getMemoryStoreState().loadState).toBe('error')
    expect(events).toEqual([{ type: 'memory:resolved', id: confirmedMemory.id, accepted: true }])
    expect(getMemoryStoreState().busyIds.size).toBe(0)
  })
})
