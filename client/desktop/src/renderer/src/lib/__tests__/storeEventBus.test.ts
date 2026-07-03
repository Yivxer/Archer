/**
 * L3.7 — storeEventBus 单元测试
 *
 * 覆盖：
 * - emit/on 基本订阅
 * - 取消订阅
 * - 多监听者独立通知
 * - 异常隔离（单个监听者抛错不影响其他）
 * - 无监听者时 emit 静默
 * - clearStoreEventBus 清空
 *
 * 集成测试（store action 成功后 emit 事件）留 L3.9 接入 main.tsx 时验证。
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import {
  clearStoreEventBus,
  emitStoreEvent,
  onStoreEvent,
  type StoreEvent,
} from '../storeEventBus'

describe('storeEventBus — L3.7 事件总线', () => {
  beforeEach(() => {
    clearStoreEventBus()
  })

  it('emit/on 基本订阅', () => {
    const received: StoreEvent[] = []
    onStoreEvent('memory:resolved', (event) => received.push(event))

    emitStoreEvent({ type: 'memory:resolved', id: 1, accepted: true })
    expect(received).toHaveLength(1)
    expect(received[0]).toEqual({ type: 'memory:resolved', id: 1, accepted: true })
  })

  it('取消订阅后不再收到事件', () => {
    const received: StoreEvent[] = []
    const unsub = onStoreEvent('memory:resolved', (event) => received.push(event))
    unsub()
    emitStoreEvent({ type: 'memory:resolved', id: 1, accepted: true })
    expect(received).toHaveLength(0)
  })

  it('多监听者独立通知', () => {
    const a: StoreEvent[] = []
    const b: StoreEvent[] = []
    onStoreEvent('job:created', (event) => a.push(event))
    onStoreEvent('job:created', (event) => b.push(event))

    emitStoreEvent({ type: 'job:created', jobId: 'job-1' })
    expect(a).toHaveLength(1)
    expect(b).toHaveLength(1)
  })

  it('一个监听者取消不影响其他', () => {
    const a: StoreEvent[] = []
    const b: StoreEvent[] = []
    const unsubA = onStoreEvent('job:created', (event) => a.push(event))
    onStoreEvent('job:created', (event) => b.push(event))

    unsubA()
    emitStoreEvent({ type: 'job:created', jobId: 'job-1' })
    expect(a).toHaveLength(0)
    expect(b).toHaveLength(1)
  })

  it('异常隔离：单个监听者抛错不影响其他监听者', () => {
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const received: StoreEvent[] = []
    onStoreEvent('memory:resolved', () => {
      throw new Error('监听者异常')
    })
    onStoreEvent('memory:resolved', (event) => received.push(event))

    emitStoreEvent({ type: 'memory:resolved', id: 1, accepted: false })
    expect(received).toHaveLength(1)
    expect(consoleWarn).toHaveBeenCalled()
    consoleWarn.mockRestore()
  })

  it('无监听者时 emit 静默（不抛错）', () => {
    expect(() => {
      emitStoreEvent({ type: 'soul:imported', imported: 5 })
    }).not.toThrow()
  })

  it('不同事件类型互不干扰', () => {
    const memoryEvents: StoreEvent[] = []
    const jobEvents: StoreEvent[] = []
    onStoreEvent('memory:resolved', (e) => memoryEvents.push(e))
    onStoreEvent('job:created', (e) => jobEvents.push(e))

    emitStoreEvent({ type: 'memory:resolved', id: 1, accepted: true })
    emitStoreEvent({ type: 'job:created', jobId: 'job-1' })

    expect(memoryEvents).toHaveLength(1)
    expect(jobEvents).toHaveLength(1)
  })

  it('clearStoreEventBus 清空所有监听者', () => {
    const received: StoreEvent[] = []
    onStoreEvent('memory:resolved', (e) => received.push(e))
    clearStoreEventBus()
    emitStoreEvent({ type: 'memory:resolved', id: 1, accepted: true })
    expect(received).toHaveLength(0)
  })
})
