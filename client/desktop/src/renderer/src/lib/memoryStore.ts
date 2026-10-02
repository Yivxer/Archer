/**
 * L3.2 — memoryStore
 *
 * 真值来源：/memory + /memory/stats + /memory/groups + 审阅动作
 * 订阅者：MemoryPage、ReviewPage、导航计数、ProfilePanel、SettingsPage
 *
 * 契约：docs/api-contract.md §「memoryStore（L3.2）」
 */

import {
  batchResolvePendingMemory,
  evolveMemory,
  fetchMemoryGroups,
  fetchMemoryItems,
  fetchMemoryStats,
  resolvePendingMemory,
  updateMemory,
} from '../adapters/memoryAdapter'
import type { MemoryGroup, MemoryItem, MemoryStats } from '../types'
import { createExternalStore, useExternalStore, type LoadState } from './externalStore'
import { emitStoreEvent } from './storeEventBus'

// ───────────────────────── State ─────────────────────────

export type MemoryStoreState = {
  items: MemoryItem[]
  stats: MemoryStats | null
  groups: MemoryGroup[]
  loadState: LoadState
  error: string
  busyIds: Set<number>
}

const initialState: MemoryStoreState = {
  items: [],
  stats: null,
  groups: [],
  loadState: 'idle',
  error: '',
  busyIds: new Set(),
}

// ───────────────────────── Store 单例 ─────────────────────────

const store = createExternalStore<MemoryStoreState>(initialState)
let loadGeneration = 0
let pendingLoad: Promise<void> | null = null

export function getMemoryStoreState(): MemoryStoreState {
  return store.getState()
}

export function subscribeMemoryStore(listener: () => void): () => void {
  return store.subscribe(listener)
}

// ───────────────────────── Actions ─────────────────────────

/**
 * 全量加载 memory 数据（items + stats + groups 并发）。
 */
export function loadAllMemory(options: { force?: boolean } = {}): Promise<void> {
  if (pendingLoad && !options.force) return pendingLoad
  const generation = ++loadGeneration
  store.setState((s) => ({ ...s, loadState: 'loading', error: '' }))
  pendingLoad = readMemory(generation)
  return pendingLoad
}

async function readMemory(generation: number): Promise<void> {
  try {
    const [items, stats, groups] = await Promise.all([
      fetchMemoryItems(),
      fetchMemoryStats(),
      fetchMemoryGroups(),
    ])
    if (generation !== loadGeneration) return
    store.setState((s) => ({
      ...s,
      items,
      stats,
      groups: Object.values(groups),
      loadState: 'ready',
      error: '',
    }))
  } catch (err) {
    if (generation !== loadGeneration) return
    store.setState((s) => ({
      ...s,
      loadState: 'error',
      error: err instanceof Error ? err.message : String(err),
    }))
  } finally {
    if (generation === loadGeneration) pendingLoad = null
  }
}

/**
 * 审阅单条 pending memory。
 */
export async function resolvePendingMemoryAction(
  id: number,
  accepted: boolean,
): Promise<void> {
  if (store.getState().busyIds.has(id)) return
  store.setState((s) => ({
    ...s,
    busyIds: new Set([...s.busyIds, id]),
    error: '',
  }))
  try {
    const result = await resolvePendingMemory(id, accepted)
    if (!result.ok) throw new Error('无待处理记忆被更新')
    // 以服务端状态同步 items、stats、groups，保留确认后的长期记忆。
    await loadAllMemory({ force: true })
    emitStoreEvent({ type: 'memory:resolved', id, accepted })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  } finally {
    store.setState((s) => ({ ...s, busyIds: new Set([...s.busyIds].filter((busyId) => busyId !== id)) }))
  }
}

/**
 * 批量审阅 pending memory。
 */
export async function batchResolvePendingMemoryAction(
  accepted: boolean,
): Promise<void> {
  try {
    const result = await batchResolvePendingMemory(accepted)
    if (!result.ok) throw new Error('批量记忆更新失败')
    // 批量操作后全量 refresh
    await loadAllMemory({ force: true })
    // L3.7: 通知跨 store 联动
    emitStoreEvent({ type: 'memory:batch-resolved', accepted })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

/**
 * 更新单条 memory 内容。
 */
export async function updateMemoryAction(
  id: number,
  content: string,
): Promise<void> {
  if (store.getState().busyIds.has(id)) return
  store.setState((s) => ({ ...s, busyIds: new Set([...s.busyIds, id]), error: '' }))
  try {
    const result = await updateMemory(id, content)
    if (!result.ok) throw new Error('记忆更新失败')
    await loadAllMemory({ force: true })
    emitStoreEvent({ type: 'memory:updated', id })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  } finally {
    store.setState((s) => ({ ...s, busyIds: new Set([...s.busyIds].filter((busyId) => busyId !== id)) }))
  }
}

/**
 * 演化写入 memory。
 */
export async function evolveMemoryAction(
  id: number,
  content: string,
  type?: string,
  importance?: number,
  depth?: number,
): Promise<void> {
  try {
    const result = await evolveMemory(id, content, type, importance, depth)
    if (!result.ok) throw new Error('记忆演化失败')
    // 演化可能改变 type/depth，重新加载 memory 领域快照。
    await loadAllMemory({ force: true })
    // 通知跨领域订阅者，页面直接读取 store。
    emitStoreEvent({ type: 'memory:evolved', id })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

/**
 * 重置 store（用于测试或退出登录）。
 */
export function resetMemoryStore(): void {
  loadGeneration += 1
  pendingLoad = null
  store.setState(() => initialState)
}

// ───────────────────────── React hook ─────────────────────────

/**
 * 订阅 memoryStore 的切片。
 *
 * 注意：返回对象/数组时，selector 每次返回新引用会导致重渲染。
 * 建议页面侧用 useMemo 包裹派生数据，或选择基本类型字段。
 */
export function useMemoryStore<U>(selector: (state: MemoryStoreState) => U): U {
  return useExternalStore(store, selector)
}
