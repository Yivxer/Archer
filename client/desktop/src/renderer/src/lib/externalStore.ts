/**
 * L3.2-L3.6 共享：外部 store 基础工具
 *
 * 模式：单例外部 store + useSyncExternalStore（与 runtimeStore 一致）
 * 不引入新依赖，纯 React 18 API。
 */

import { useSyncExternalStore } from 'react'

/**
 * 外部 store 接口。每个领域 store 实现此接口。
 *
 * - getState：返回当前快照（不可变）
 * - subscribe：注册监听器，返回 unsubscribe
 * - setState：不可变更新，自动通知所有监听器
 */
export type ExternalStore<T> = {
  getState(): T
  subscribe(listener: () => void): () => void
  setState(producer: (draft: T) => T): void
}

/**
 * 创建一个外部 store 单例。
 *
 * @param initialState 初始状态
 * @returns ExternalStore 实例
 */
export function createExternalStore<T>(initialState: T): ExternalStore<T> {
  let state = initialState
  const listeners = new Set<() => void>()

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    setState(producer) {
      const next = producer(state)
      if (next !== state) {
        state = next
        for (const listener of listeners) listener()
      }
    },
  }
}

/**
 * React hook：订阅外部 store，返回 selector 选中的切片。
 *
 * useSyncExternalStore 要求 getSnapshot 返回稳定引用：
 * 如果 selector 返回新对象/数组，需要配合 useMemo 或 shallow equal。
 * 这里用 Object.is 做默认比较，简单值类型（string/number/boolean/null）直接安全。
 *
 * @param store ExternalStore 实例
 * @param selector 从 state 中选取切片
 * @returns 选中切片
 */
export function useExternalStore<T, U>(
  store: ExternalStore<T>,
  selector: (state: T) => U,
): U {
  return useSyncExternalStore(
    store.subscribe,
    () => selector(store.getState()),
    () => selector(store.getState()),
  )
}

/**
 * 加载状态枚举（5 个 store 共用）。
 */
export type LoadState = 'idle' | 'loading' | 'ready' | 'error'
