/**
 * L3.2 — memoryStore
 *
 * 真值来源：/memory + /memory/stats + /memory/groups + 审阅动作
 * 订阅者：MemoryPage、ReviewPage、ChatPage Workspace
 *
 * 契约：docs/api-contract.md §「memoryStore（L3.2）」
 */

import {
  batchResolvePendingMemory,
  evolveMemory,
  fetchMemoryGroups,
  fetchMemoryStats,
  resolvePendingMemory,
  updateMemory,
} from '../adapters/localArcher'
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
export async function loadAllMemory(): Promise<void> {
  store.setState((s) => ({ ...s, loadState: 'loading', error: '' }))
  try {
    const [items, stats, groups] = await Promise.all([
      // items 复用 loadLocalArcher 的 fetch（这里直接调 stats/groups + 假设 items 由 mergeItems 注入）
      // 实际实现：items 通过 mergeItems 由 main.tsx 注入，loadAll 只补 stats + groups
      Promise.resolve<MemoryItem[]>(store.getState().items),
      fetchMemoryStats(),
      fetchMemoryGroups(),
    ])
    store.setState((s) => ({
      ...s,
      items,
      stats,
      groups: Object.values(groups),
      loadState: 'ready',
      error: '',
    }))
  } catch (err) {
    store.setState((s) => ({
      ...s,
      loadState: 'error',
      error: err instanceof Error ? err.message : String(err),
    }))
  }
}

/**
 * 审阅单条 pending memory。
 */
export async function resolvePendingMemoryAction(
  id: number,
  accepted: boolean,
): Promise<void> {
  store.setState((s) => ({
    ...s,
    busyIds: new Set([...s.busyIds, id]),
  }))
  try {
    await resolvePendingMemory(id, accepted)
    // 成功后从 items 移除（rejected 也移除，避免重复显示）
    store.setState((s) => ({
      ...s,
      items: s.items.filter((item) => item.id !== id),
      busyIds: new Set([...s.busyIds].filter((busyId) => busyId !== id)),
    }))
    // refresh stats（不阻塞，失败静默）
    fetchMemoryStats()
      .then((stats) => store.setState((s) => ({ ...s, stats })))
      .catch(() => {})
    // L3.7: 通知跨 store 联动（main.tsx 监听后触发 loadLocalArcher refresh）
    emitStoreEvent({ type: 'memory:resolved', id, accepted })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      busyIds: new Set([...s.busyIds].filter((busyId) => busyId !== id)),
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

/**
 * 批量审阅 pending memory。
 */
export async function batchResolvePendingMemoryAction(
  accepted: boolean,
): Promise<void> {
  try {
    await batchResolvePendingMemory(accepted)
    // 批量操作后全量 refresh
    await loadAllMemory()
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
  try {
    await updateMemory(id, content)
    store.setState((s) => ({
      ...s,
      items: s.items.map((item) => (item.id === id ? { ...item, content } : item)),
    }))
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
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
    await evolveMemory(id, content, type, importance, depth)
    // 演化可能改变 type/depth，全量 refresh items 更稳妥
    await loadAllMemory()
    // L3.7: 通知跨 store 联动（soul 演化可能影响 session 摘要）
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
 * 由 loadLocalArcher 注入 items（不触发 API）。
 * 注入后即视为 ready，避免 storeSync 后 loadState 仍为 idle。
 */
export function mergeMemoryItems(items: MemoryItem[]): void {
  store.setState((s) => ({ ...s, items, loadState: 'ready' }))
}

/**
 * 重置 store（用于测试或退出登录）。
 */
export function resetMemoryStore(): void {
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
