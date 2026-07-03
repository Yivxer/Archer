/**
 * Q1 量化指标采集 — 连接状态转换持久化。
 *
 * 镜像 eventLog.ts 的持久化模式：把 ConnectionStateEngine 的 transitions
 * 写入 localStorage，供 scripts/collect_metrics.py 导出后计算 dead→ready 耗时。
 *
 * 契约来源：Archer 稳定性框架 §13.5 Q1（dead→ready 耗时指标采集）。
 */

import type { ConnectionState, ConnectionSignal } from './connectionState'

export type TransitionRecord = {
  /** 发生时间戳（ms） */
  at: number
  /** 转换前状态 */
  from: ConnectionState
  /** 转换后状态 */
  to: ConnectionState
  /** 触发信号类型 */
  signal: ConnectionSignal['kind']
}

export type ConnectionLogStorage = {
  getItem: (key: string) => string | null
  setItem: (key: string, value: string) => void
  removeItem: (key: string) => void
}

const DEFAULT_LIMIT = 200

/**
 * 持久化转换记录到 storage。
 *
 * 设计：
 * - 全量覆盖写（transitions 已在 Engine 内截断到 50 条，这里再截到 limit）
 * - 调用方负责传入最新 transitions 数组
 * - 空数组时清除 storage（避免遗留空数据）
 */
export function persistTransitions(
  storage: ConnectionLogStorage,
  transitions: TransitionRecord[],
  key = 'archer-connection-transitions',
  limit = DEFAULT_LIMIT,
): void {
  const capped = transitions.slice(-limit)
  if (capped.length === 0) {
    storage.removeItem(key)
    return
  }
  try {
    storage.setItem(key, JSON.stringify(capped))
  } catch {
    // storage 满或不可用，静默降级（指标采集是 best-effort）
  }
}

/**
 * 读取持久化的转换记录（供 collect_metrics.py 导出用）。
 */
export function readTransitions(
  storage: ConnectionLogStorage,
  key = 'archer-connection-transitions',
): TransitionRecord[] {
  const raw = storage.getItem(key)
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(isValidTransition)
  } catch {
    return []
  }
}

function isValidTransition(value: unknown): value is TransitionRecord {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return (
    typeof v.at === 'number' &&
    typeof v.from === 'string' &&
    typeof v.to === 'string' &&
    typeof v.signal === 'string'
  )
}
