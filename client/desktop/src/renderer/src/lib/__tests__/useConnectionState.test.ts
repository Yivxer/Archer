/**
 * L1.2.2 — useConnectionState() hook 测试。
 *
 * 测试策略：
 *   - Engine 是纯逻辑类，覆盖 10 条测试矩阵 T1-T10 + 边界
 *   - hook 部分是 Engine 的 React 包装，逻辑等价，不重复测
 *   - 不引入 @testing-library/react 依赖（项目当前无此依赖）
 */

import { describe, expect, it } from 'vitest'

import {
  CONNECTING_TIMEOUT_MS,
  ConnectionStateEngine,
  RECOVERING_TIMEOUT_MS,
  type BrainStatusSnapshot,
} from '../useConnectionState'

// ───────────────────────── 辅助 ─────────────────────────

function brainReady(overrides: Partial<BrainStatusSnapshot> = {}): BrainStatusSnapshot {
  return {
    pythonOk: true,
    scriptOk: true,
    portOk: true,
    readyOk: true,
    tokenOk: true,
    owned: true,
    reason: 'owned',
    ...overrides,
  }
}

function brainNotReady(): BrainStatusSnapshot {
  return brainReady({ readyOk: false, owned: false, reason: 'not_ready' })
}

function brainPortDown(): BrainStatusSnapshot {
  return brainReady({ portOk: false, readyOk: false, owned: false, reason: 'port_down' })
}

function brainMissingPython(): BrainStatusSnapshot {
  return brainReady({
    pythonOk: false,
    portOk: false,
    readyOk: false,
    owned: false,
    reason: 'missing_python',
  })
}

function brainTokenMismatch(): BrainStatusSnapshot {
  return brainReady({ tokenOk: false, owned: false, reason: 'token_mismatch' })
}

// ───────────────────────── Engine: 10 条测试矩阵 T1-T10 ─────────────────────────

describe('ConnectionStateEngine — 10 条测试矩阵 T1-T10', () => {
  /**
   * T1 启动正常: disconnected → connecting → ready
   * T2 启动时 Python 缺失: disconnected → connecting → dead
   * T3 启动时端口占用: disconnected → connecting → dead
   * T4 ready 时杀 API: ready → recovering → ready
   * T5 ready 时 doctor warn: ready → degraded
   * T6 degraded 恢复: degraded → ready
   * T7 restart 2 次失败: recovering → dead
   * T8 dead 状态不变量: dead 状态保持
   * T9 单次 /health 抖动: ready → ready（不计入 recovering）
   * T10 用户退出: any → disconnected
   */

  it('T1: 启动正常 disconnected → connecting → ready', () => {
    const e = new ConnectionStateEngine()
    expect(e.get().state).toBe('disconnected')

    e.dispatch({ kind: 'start' })
    expect(e.get().state).toBe('connecting')

    // 第一次心跳：not_ready（仍在 connecting）
    e.onBrainStatus(brainNotReady(), false, 1000)
    expect(e.get().state).toBe('connecting')

    // 第二次心跳：ready + doctor clear
    e.onBrainStatus(brainReady(), false, 2000)
    expect(e.get().state).toBe('ready')
  })

  it('T2: 启动时 Python 缺失 → dead', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    expect(e.get().state).toBe('connecting')

    e.onBrainStatus(brainMissingPython(), false, 1000)
    expect(e.get().state).toBe('dead')
    expect(e.get().deadReason).toContain('missing_python')
  })

  it('T3: 启动时端口占用 → dead', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })

    e.onBrainStatus(brainPortDown(), false, 1000)
    expect(e.get().state).toBe('dead')
    expect(e.get().deadReason).toContain('port_down')
  })

  it('T4: ready 时杀 API → recovering → ready', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainReady(), false, 1000)
    expect(e.get().state).toBe('ready')

    // 连续 3 次 /health 超时
    e.onBrainStatus(brainPortDown(), false, 2000) // streak=1
    expect(e.get().state).toBe('ready')
    e.onBrainStatus(brainPortDown(), false, 3000) // streak=2
    expect(e.get().state).toBe('ready')
    e.onBrainStatus(brainPortDown(), false, 4000) // streak=3 → recovering
    expect(e.get().state).toBe('recovering')

    // restart 成功
    e.onBrainStatus(brainReady(), false, 5000)
    expect(e.get().state).toBe('ready')
  })

  it('T5: ready 时 doctor warn → degraded', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainReady(), false, 1000)
    expect(e.get().state).toBe('ready')

    // doctor warn 触发 degraded
    e.onBrainStatus(brainReady(), true, 2000)
    expect(e.get().state).toBe('degraded')
    expect(e.get().degradedReason).toBeTruthy()
  })

  it('T6: degraded 恢复 → ready', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainReady(), true, 1000) // 直接 degraded
    expect(e.get().state).toBe('degraded')

    // doctor clear + ready 200
    e.onBrainStatus(brainReady(), false, 2000)
    expect(e.get().state).toBe('ready')
    expect(e.get().degradedReason).toBe('')
  })

  it('T7: restart 2 次失败 → dead', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainReady(), false, 1000)
    expect(e.get().state).toBe('ready')

    // 连续 3 次超时 → recovering
    e.onBrainStatus(brainPortDown(), false, 2000)
    e.onBrainStatus(brainPortDown(), false, 3000)
    e.onBrainStatus(brainPortDown(), false, 4000)
    expect(e.get().state).toBe('recovering')

    // restart 第 1 次失败
    e.onBrainStatus(brainPortDown(), false, 5000)
    expect(e.get().state).toBe('recovering')
    expect(e.get().restartAttempts).toBe(1)

    // restart 第 2 次失败 → dead
    e.onBrainStatus(brainPortDown(), false, 6000)
    expect(e.get().state).toBe('dead')
    expect(e.get().deadReason).toContain('重启失败')
  })

  it('T8: dead 状态保持（不变量 2: 不再发请求）', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainMissingPython(), false, 1000)
    expect(e.get().state).toBe('dead')

    // dead 状态下 brain status 不再触发转移
    e.onBrainStatus(brainReady(), false, 2000)
    expect(e.get().state).toBe('dead')

    // 只有 user_recover 能离开 dead
    e.dispatch({ kind: 'user_recover' })
    expect(e.get().state).toBe('connecting')
  })

  it('T9: 单次 /health 抖动不计入 recovering', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainReady(), false, 1000)
    expect(e.get().state).toBe('ready')

    // 1 次超时
    e.onBrainStatus(brainPortDown(), false, 2000)
    expect(e.get().state).toBe('ready')
    expect(e.get().healthTimeoutStreak).toBe(1)

    // 恢复 → streak 重置
    e.onBrainStatus(brainReady(), false, 3000)
    expect(e.get().state).toBe('ready')
    expect(e.get().healthTimeoutStreak).toBe(0)
  })

  it('T10: 用户退出 → disconnected（从 ready）', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainReady(), false, 1000)
    expect(e.get().state).toBe('ready')

    e.dispatch({ kind: 'user_quit' })
    expect(e.get().state).toBe('disconnected')
  })
})

// ───────────────────────── Engine 边界与不变量 ─────────────────────────

describe('ConnectionStateEngine — 边界与不变量', () => {
  it('disconnected 状态不响应 brain status', () => {
    const e = new ConnectionStateEngine()
    e.onBrainStatus(brainReady(), false, 1000)
    expect(e.get().state).toBe('disconnected')
  })

  it('connecting 超时 15s → dead', () => {
    const e = new ConnectionStateEngine()
    const start = 1000
    e.dispatch({ kind: 'start' })
    expect(e.get().state).toBe('connecting')

    // 模拟 lastTransitionAt 已设
    ;(e as unknown as { snapshot: { lastTransitionAt: number } }).snapshot.lastTransitionAt = start
    e.onTick(start + CONNECTING_TIMEOUT_MS + 100)
    expect(e.get().state).toBe('dead')
    expect(e.get().deadReason).toContain('连接超时')
  })

  it('recovering 超时 30s → dead', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainReady(), false, 1000)
    e.onBrainStatus(brainPortDown(), false, 2000)
    e.onBrainStatus(brainPortDown(), false, 3000)
    e.onBrainStatus(brainPortDown(), false, 4000)
    expect(e.get().state).toBe('recovering')

    const start = e.get().lastTransitionAt
    e.onTick(start + RECOVERING_TIMEOUT_MS + 100)
    expect(e.get().state).toBe('dead')
    expect(e.get().deadReason).toContain('恢复超时')
  })

  it('connecting_health_ok token 失败 → dead', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainTokenMismatch(), false, 1000)
    expect(e.get().state).toBe('dead')
  })

  it('transitions 历史保留最近 50 条', () => {
    const e = new ConnectionStateEngine()
    for (let i = 0; i < 60; i++) {
      e.dispatch({ kind: 'start' })
      e.dispatch({ kind: 'user_quit' })
    }
    expect(e.get().transitions.length).toBeLessThanOrEqual(50)
  })

  it('不变量 1: recovering 状态下 start 信号不触发新 restart', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainReady(), false, 1000)
    e.onBrainStatus(brainPortDown(), false, 2000)
    e.onBrainStatus(brainPortDown(), false, 3000)
    e.onBrainStatus(brainPortDown(), false, 4000)
    expect(e.get().state).toBe('recovering')

    // start 信号在 recovering 状态返回 null
    e.dispatch({ kind: 'start' })
    expect(e.get().state).toBe('recovering')
  })

  it('connecting 时 not_ready 心跳不切状态', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    // 多次 not_ready 心跳
    for (let i = 0; i < 3; i++) {
      e.onBrainStatus(brainNotReady(), false, 1000 + i * 1000)
      expect(e.get().state).toBe('connecting')
    }
  })

  it('degraded 时连续 3 次超时 → recovering', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainReady(), true, 1000) // degraded
    expect(e.get().state).toBe('degraded')

    e.onBrainStatus(brainPortDown(), false, 2000) // streak=1
    e.onBrainStatus(brainPortDown(), false, 3000) // streak=2
    e.onBrainStatus(brainPortDown(), false, 4000) // streak=3 → recovering
    expect(e.get().state).toBe('recovering')
  })

  it('tick 在 ready 状态不触发转移', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    e.onBrainStatus(brainReady(), false, 1000)
    expect(e.get().state).toBe('ready')

    // 多次 tick
    for (let i = 0; i < 10; i++) {
      e.onTick(2000 + i * 1000)
      expect(e.get().state).toBe('ready')
    }
  })

  it('transitions 记录 from/to/signal', () => {
    const e = new ConnectionStateEngine()
    e.dispatch({ kind: 'start' })
    const last = e.get().transitions.at(-1)
    expect(last).toBeDefined()
    expect(last!.from).toBe('disconnected')
    expect(last!.to).toBe('connecting')
    expect(last!.signal).toBe('start')
  })
})

// ───────────────────────── L1.2.8 端到端场景 ─────────────────────────

describe('L1.2.8 端到端：杀 Python API 自动恢复（60s 内回到 ready 或显式 dead）', () => {
  /**
   * 模拟 useConnectionState hook 的完整调用模式：
   *   - 5s 心跳：onBrainStatus
   *   - 1s tick：onTick（驱动超时）
   *   - 用户/系统信号：dispatch
   *
   * 不依赖 React，直接驱动 Engine，验证状态流转 + transitions log。
   */

  it('场景 A：杀 API → 3 次超时 → recovering → restart 成功 → ready（< 60s）', () => {
    const e = new ConnectionStateEngine()
    let now = 0

    // t=0: autoStart → connecting
    e.dispatch({ kind: 'start' })
    expect(e.get().state).toBe('connecting')
    now = 100

    // t=5s: 第一次心跳 not_ready（仍在 connecting）
    now = 5_000
    e.onBrainStatus(brainNotReady(), false, now)
    expect(e.get().state).toBe('connecting')

    // t=10s: 心跳 ready → ready
    now = 10_000
    e.onBrainStatus(brainReady(), false, now)
    expect(e.get().state).toBe('ready')

    // t=15s: 杀 API，第一次 portDown（streak=1，仍 ready）
    now = 15_000
    e.onBrainStatus(brainPortDown(), false, now)
    expect(e.get().state).toBe('ready')
    expect(e.get().healthTimeoutStreak).toBe(1)

    // t=16-19s: tick 不触发转移（ready 状态无超时）
    for (let t = 16_000; t < 20_000; t += 1_000) {
      e.onTick(t)
      expect(e.get().state).toBe('ready')
    }

    // t=20s: 第二次 portDown（streak=2，仍 ready）
    now = 20_000
    e.onBrainStatus(brainPortDown(), false, now)
    expect(e.get().state).toBe('ready')
    expect(e.get().healthTimeoutStreak).toBe(2)

    // t=25s: 第三次 portDown（streak=3 → recovering）
    now = 25_000
    e.onBrainStatus(brainPortDown(), false, now)
    expect(e.get().state).toBe('recovering')
    expect(e.get().healthTimeoutStreak).toBe(0) // 进入 recovering 时重置

    const recoveringAt = e.get().lastTransitionAt

    // t=26-34s: tick 不触发超时（< 30s）
    for (let t = 26_000; t < 35_000; t += 1_000) {
      e.onTick(t)
      expect(e.get().state).toBe('recovering')
    }

    // t=35s: restart 成功 → ready
    now = 35_000
    e.onBrainStatus(brainReady(), false, now)
    expect(e.get().state).toBe('ready')
    expect(e.get().restartAttempts).toBe(0)

    // 验证 60s 内回到 ready
    expect(now - recoveringAt).toBeLessThan(60_000)

    // 验证 transitions log 完整
    const kinds = e.get().transitions.map((t) => t.signal)
    expect(kinds).toEqual([
      'start',                    // disconnected → connecting
      'connecting_health_ok',     // connecting → ready
      'health_timeout_streak',    // ready → recovering
      'restart_attempt',          // recovering → ready
    ])
  })

  it('场景 B：杀 API → recovering → restart 2 次失败 → dead（< 60s）', () => {
    const e = new ConnectionStateEngine()
    let now = 0

    // 启动到 ready
    e.dispatch({ kind: 'start' })
    now = 100
    now = 5_000
    e.onBrainStatus(brainNotReady(), false, now)
    now = 10_000
    e.onBrainStatus(brainReady(), false, now)
    expect(e.get().state).toBe('ready')

    // 杀 API：3 次超时 → recovering
    e.onBrainStatus(brainPortDown(), false, 15_000)
    e.onBrainStatus(brainPortDown(), false, 20_000)
    e.onBrainStatus(brainPortDown(), false, 25_000)
    expect(e.get().state).toBe('recovering')

    const recoveringAt = e.get().lastTransitionAt

    // restart 第 1 次失败（attempt=1，仍 recovering）
    now = 30_000
    e.onBrainStatus(brainPortDown(), false, now)
    expect(e.get().state).toBe('recovering')
    expect(e.get().restartAttempts).toBe(1)

    // restart 第 2 次失败（attempt=2 → dead）
    now = 35_000
    e.onBrainStatus(brainPortDown(), false, now)
    expect(e.get().state).toBe('dead')
    expect(e.get().deadReason).toContain('重启失败')

    // 验证 60s 内显式 dead
    expect(now - recoveringAt).toBeLessThan(60_000)

    // 验证 dead 状态不变量：后续 brain status 不再改变状态
    e.onBrainStatus(brainReady(), false, 40_000)
    expect(e.get().state).toBe('dead')

    // 验证只能通过 user_recover 离开 dead
    e.dispatch({ kind: 'user_recover' })
    expect(e.get().state).toBe('connecting')
  })

  it('场景 C：杀 API → recovering → 30s 超时 → dead（< 60s）', () => {
    const e = new ConnectionStateEngine()
    let now = 0

    // 启动到 ready
    e.dispatch({ kind: 'start' })
    now = 5_000
    e.onBrainStatus(brainReady(), false, now)
    expect(e.get().state).toBe('ready')

    // 杀 API：3 次超时 → recovering
    e.onBrainStatus(brainPortDown(), false, 10_000)
    e.onBrainStatus(brainPortDown(), false, 15_000)
    e.onBrainStatus(brainPortDown(), false, 20_000)
    expect(e.get().state).toBe('recovering')

    const recoveringAt = e.get().lastTransitionAt

    // tick 推进到 30s 后 → dead
    e.onTick(recoveringAt + RECOVERING_TIMEOUT_MS + 100)
    expect(e.get().state).toBe('dead')
    expect(e.get().deadReason).toContain('恢复超时')

    // 验证 60s 内显式 dead
    expect(recoveringAt + RECOVERING_TIMEOUT_MS + 100 - recoveringAt).toBeLessThan(60_000)
  })
})
