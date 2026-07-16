/**
 * L3.7 — storeEventBus（跨 store 联动事件总线）
 *
 * 解耦 store 间联动：store action 成功后 emit 事件，
 * 订阅方（main.tsx 或其他 store）决定是否 refresh。
 *
 * 设计：
 * - store 间不直接调用（低耦合）
 * - main.tsx 作为协调者，优先做领域投影；未迁移事件保留兼容 refresh
 * - store 的 action 不需要知道谁在监听
 *
 * 契约：docs/api-contract.md §「跨 store 联动（L3.7）」
 */

// ───────────────────────── 事件类型 ─────────────────────────

export type StoreEvent =
  | { type: 'memory:resolved'; id: number; accepted: boolean }
  | { type: 'memory:batch-resolved'; accepted: boolean; count?: number }
  | { type: 'memory:evolved'; id: number }
  | { type: 'memory:updated'; id: number }
  | { type: 'soul:imported'; imported: number }
  | { type: 'soul:reflection-triggered' }
  | { type: 'job:created'; jobId: string }
  | { type: 'job:cancelled'; jobId: string }
  | { type: 'job:retried'; jobId: string }
  | { type: 'job:approved'; jobId: string; decision: 'approved' | 'denied' }
  | { type: 'job:spawned'; parentJobId: string; childCount: number }

export type StoreEventType = StoreEvent['type']

// ───────────────────────── 总线实现 ─────────────────────────

const listeners = new Map<StoreEventType, Set<(event: StoreEvent) => void>>()

/**
 * 发出 store 事件。同步通知所有监听者。
 * 异常隔离：单个监听者抛错不影响其他监听者。
 */
export function emitStoreEvent(event: StoreEvent): void {
  const set = listeners.get(event.type)
  if (!set) return
  for (const handler of set) {
    try {
      handler(event)
    } catch (err) {
      // 监听者异常不影响其他监听者，也不阻塞 emit 方
      console.warn(`[storeEventBus] listener for "${event.type}" threw:`, err)
    }
  }
}

/**
 * 订阅 store 事件。返回取消订阅函数。
 */
export function onStoreEvent(
  type: StoreEventType,
  handler: (event: StoreEvent) => void,
): () => void {
  let set = listeners.get(type)
  if (!set) {
    set = new Set()
    listeners.set(type, set)
  }
  set.add(handler)
  return () => {
    set?.delete(handler)
  }
}

/**
 * 清空所有监听者（仅用于测试）。
 */
export function clearStoreEventBus(): void {
  listeners.clear()
}
