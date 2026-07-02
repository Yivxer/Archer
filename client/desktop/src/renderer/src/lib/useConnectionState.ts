/**
 * L1.2.2 — useConnectionState() hook + 状态机引擎。
 *
 * 设计：
 *   - `ConnectionStateEngine`：纯逻辑类，无 React 依赖，可独立测试
 *     - 接收 brain status / doctor warn / tick 信号
 *     - 维护 /health 超时计数、connecting/recovering 超时
 *     - 内部调 transition() 推进状态
 *   - `useConnectionState()`：React hook，包装 Engine + 副作用
 *     - 5s 心跳：调 window.archerDesktop.getBrainStatus()
 *     - 30s doctor：调 /config/doctor（fetch），可选注入
 *     - 1s tick：触发 connecting/recovering 超时检查
 *
 * 契约来源：Archer 稳定性框架 §四 L1.2.2。
 */

import React from 'react'

import {
  badgeLabel,
  type BrainStatusReason,
  type ConnectionBadgeVisual,
  type ConnectionState,
  type ConnectionSignal,
  transition,
} from './connectionState'

// ───────────────────────── 类型 ─────────────────────────

export type BrainStatusSnapshot = {
  pythonOk: boolean
  scriptOk: boolean
  portOk: boolean
  readyOk: boolean
  tokenOk: boolean
  owned: boolean
  reason: string
}

export type ConnectionStateSnapshot = {
  state: ConnectionState
  /** degraded 状态下的原因（来自 doctor warn） */
  degradedReason: string
  /** dead 状态下的原因（来自 launch_fail / restart 失败） */
  deadReason: string
  /** 最近一次 brain status reason（trace 用） */
  lastBrainReason: string | null
  /** /health 超时连续计数（≥3 触发 recovering） */
  healthTimeoutStreak: number
  /** restart 尝试次数 */
  restartAttempts: number
  /** 最近一次状态转移时间戳（ms） */
  lastTransitionAt: number
  /** 最近一次 brain status 时间戳（ms） */
  lastBrainAt: number
  /** 历史转移记录（trace log） */
  transitions: Array<{ at: number; from: ConnectionState; to: ConnectionState; signal: ConnectionSignal['kind'] }>
}

export const INITIAL_SNAPSHOT: ConnectionStateSnapshot = {
  state: 'disconnected',
  degradedReason: '',
  deadReason: '',
  lastBrainReason: null,
  healthTimeoutStreak: 0,
  restartAttempts: 0,
  lastTransitionAt: 0,
  lastBrainAt: 0,
  transitions: [],
}

// ───────────────────────── 常量 ─────────────────────────

/** 5s 心跳（与主进程 API_WATCHDOG_INTERVAL_MS 对齐） */
export const HEARTBEAT_INTERVAL_MS = 5_000
/** 30s doctor 轮询 */
export const DOCTOR_POLL_INTERVAL_MS = 30_000
/** 1s tick（驱动超时检查） */
export const TICK_INTERVAL_MS = 1_000
/** connecting 超时 15s → dead */
export const CONNECTING_TIMEOUT_MS = 15_000
/** recovering 超时 30s → dead */
export const RECOVERING_TIMEOUT_MS = 30_000
/** /health 连续超时阈值 */
export const HEALTH_TIMEOUT_STREAK_THRESHOLD = 3
/** restart 最大尝试次数（超过即 dead） */
export const RESTART_MAX_ATTEMPTS = 2

// ───────────────────────── Engine ─────────────────────────

/**
 * 纯逻辑状态机引擎。无副作用，所有方法返回新 snapshot。
 *
 * 调用方负责：
 *   - 5s 调 onBrainStatus(snapshot, doctorWarn)
 *   - 1s 调 onTick(now)
 *   - 用户操作调 dispatch(signal)
 */
export class ConnectionStateEngine {
  private snapshot: ConnectionStateSnapshot

  constructor(initial: ConnectionStateSnapshot = INITIAL_SNAPSHOT) {
    this.snapshot = { ...initial, transitions: [...initial.transitions] }
  }

  get(): ConnectionStateSnapshot {
    return this.snapshot
  }

  /** 手动 dispatch 信号（用户点击重连/手动恢复/退出等） */
  dispatch(signal: ConnectionSignal): ConnectionStateSnapshot {
    const next = transition(this.snapshot.state, signal)
    if (next === null) return this.snapshot
    this.snapshot = applyTransition(this.snapshot, next, signal)
    return this.snapshot
  }

  /**
   * 接收 brain status 信号（5s 心跳）。
   *
   * @param brain 主进程返回的 BrainStatusSnapshot
   * @param doctorWarn /config/doctor 是否有 warn（可选，由 30s 轮询提供）
   * @param now 当前时间戳
   */
  onBrainStatus(
    brain: BrainStatusSnapshot,
    doctorWarn: boolean,
    now: number,
  ): ConnectionStateSnapshot {
    this.snapshot = { ...this.snapshot, lastBrainAt: now, lastBrainReason: brain.reason }

    const state = this.snapshot.state

    // dead 状态下不再发任何 API 请求（不变量 2）—— 但 brain status 仍可能被调用
    // 只在 dead 状态收到 reused/owned 信号时，允许通过 user_recover 间接恢复
    if (state === 'dead') {
      // 死了就不动，等用户点击手动恢复
      return this.snapshot
    }

    // disconnected 状态不响应 brain status（需先 start）
    if (state === 'disconnected') {
      return this.snapshot
    }

    // ── connecting：brain status 决定转移到 ready/degraded/dead ──
    if (state === 'connecting') {
      const launchFailReasons = ['missing_python', 'missing_script', 'port_down', 'token_mismatch']
      if (launchFailReasons.includes(brain.reason)) {
        return this.dispatch({ kind: 'connecting_launch_fail', reason: brain.reason as never })
      }
      if (brain.pythonOk && brain.scriptOk && brain.portOk && brain.readyOk && brain.tokenOk) {
        return this.dispatch({
          kind: 'connecting_health_ok',
          readyOk: brain.readyOk,
          tokenOk: brain.tokenOk,
          doctorWarn,
        })
      }
      // not_ready：仍在 connecting，等下一次心跳
      return this.snapshot
    }

    // ── ready / degraded：brain status 决定是否切 recovering 或维持 ──
    if (state === 'ready' || state === 'degraded') {
      // /health + /ready + token 都通
      if (brain.pythonOk && brain.scriptOk && brain.portOk && brain.readyOk && brain.tokenOk) {
        // 重置超时计数
        if (this.snapshot.healthTimeoutStreak > 0) {
          this.snapshot = { ...this.snapshot, healthTimeoutStreak: 0 }
        }
        // degraded → ready（doctor clear + ready 200）
        if (state === 'degraded' && !doctorWarn) {
          return this.dispatch({ kind: 'doctor_clear', readyOk: true })
        }
        // ready → degraded（doctor warn）
        if (state === 'ready' && doctorWarn) {
          return this.dispatch({ kind: 'doctor_warn', reason: '配置诊断有警告' })
        }
        return this.snapshot
      }

      // /health 超时（readyOk=false 或 portOk=false）
      if (!brain.portOk || !brain.readyOk) {
        const newStreak = this.snapshot.healthTimeoutStreak + 1
        this.snapshot = { ...this.snapshot, healthTimeoutStreak: newStreak }
        if (newStreak >= HEALTH_TIMEOUT_STREAK_THRESHOLD) {
          // 进入 recovering，重置计数
          this.snapshot = { ...this.snapshot, healthTimeoutStreak: 0 }
          return this.dispatch({ kind: 'health_timeout_streak', count: newStreak })
        }
        return this.snapshot
      }

      // portOk + readyOk 但 token 不通 → dead
      if (!brain.tokenOk) {
        return this.dispatch({ kind: 'connecting_launch_fail', reason: 'token_mismatch' })
      }

      return this.snapshot
    }

    // ── recovering：brain status 决定 restart 成功/失败 ──
    if (state === 'recovering') {
      const attempt = this.snapshot.restartAttempts
      if (brain.pythonOk && brain.scriptOk && brain.portOk && brain.readyOk && brain.tokenOk) {
        // restart 成功，重置计数
        this.snapshot = { ...this.snapshot, restartAttempts: 0, healthTimeoutStreak: 0 }
        return this.dispatch({ kind: 'restart_attempt', attempt, readyOk: true })
      }
      // restart 失败
      const newAttempts = attempt + 1
      this.snapshot = { ...this.snapshot, restartAttempts: newAttempts }
      return this.dispatch({ kind: 'restart_attempt', attempt: newAttempts, readyOk: false })
    }

    return this.snapshot
  }

  /**
   * 接收 1s tick 信号，驱动超时检查。
   */
  onTick(now: number): ConnectionStateSnapshot {
    const state = this.snapshot.state
    const lastTransitionAt = this.snapshot.lastTransitionAt

    // connecting 超时 15s
    if (state === 'connecting' && lastTransitionAt > 0) {
      if (now - lastTransitionAt >= CONNECTING_TIMEOUT_MS) {
        return this.dispatch({ kind: 'connecting_timeout_15s' })
      }
    }

    // recovering 超时 30s
    if (state === 'recovering' && lastTransitionAt > 0) {
      if (now - lastTransitionAt >= RECOVERING_TIMEOUT_MS) {
        return this.dispatch({ kind: 'restart_timeout_30s' })
      }
    }

    return this.snapshot
  }

  /** 手动重置（仅用于测试或 doctor clear） */
  reset(): ConnectionStateSnapshot {
    this.snapshot = { ...INITIAL_SNAPSHOT, transitions: [...INITIAL_SNAPSHOT.transitions] }
    return this.snapshot
  }
}

function applyTransition(
  snap: ConnectionStateSnapshot,
  next: ConnectionState,
  signal: ConnectionSignal,
): ConnectionStateSnapshot {
  const now = Date.now()
  const transitions = [...snap.transitions, { at: now, from: snap.state, to: next, signal: signal.kind }]
  // 保留最近 50 条
  if (transitions.length > 50) transitions.splice(0, transitions.length - 50)

  let degradedReason = snap.degradedReason
  let deadReason = snap.deadReason

  if (next === 'degraded' && signal.kind === 'doctor_warn') {
    degradedReason = signal.reason
  } else if (next === 'degraded' && signal.kind === 'connecting_health_ok') {
    degradedReason = signal.doctorWarn ? '配置诊断有警告' : '/ready 异常'
  } else if (next === 'ready') {
    degradedReason = ''
  } else if (next === 'dead') {
    if (signal.kind === 'connecting_launch_fail') deadReason = `启动失败：${signal.reason}`
    else if (signal.kind === 'connecting_timeout_15s') deadReason = '连接超时 15s'
    else if (signal.kind === 'connecting_health_5xx') deadReason = '/health 5xx'
    else if (signal.kind === 'restart_timeout_30s') deadReason = '恢复超时 30s'
    else if (signal.kind === 'restart_attempt') deadReason = `重启失败 ${signal.attempt} 次`
    else if (signal.kind === 'connecting_health_ok' && !signal.tokenOk) deadReason = 'token 校验失败'
  } else if (next === 'connecting') {
    deadReason = ''
  }

  return {
    ...snap,
    state: next,
    degradedReason,
    deadReason,
    lastTransitionAt: now,
    transitions,
  }
}

// ───────────────────────── 视觉辅助 ─────────────────────────

export function snapshotBadgeVisual(snap: ConnectionStateSnapshot): ConnectionBadgeVisual {
  // 复用 connectionState.badgeVisual 的视觉定义，但 label 用动态原因
  // 这里直接 import badgeVisual 并扩展
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { badgeVisual } = require('./connectionState') as typeof import('./connectionState')
  const v = badgeVisual(snap.state)
  return {
    ...v,
    label: snapshotBadgeLabel(snap),
  }
}

export function snapshotBadgeLabel(snap: ConnectionStateSnapshot): string {
  if (snap.state === 'degraded' && snap.degradedReason) {
    return `降级中：${snap.degradedReason}`
  }
  if (snap.state === 'dead' && snap.deadReason) {
    return '本地 API 不可用'
  }
  return badgeLabel(snap.state)
}

// ───────────────────────── React Hook ─────────────────────────

export type UseConnectionStateOptions = {
  /** 注入 brain status fetcher（测试用） */
  fetchBrainStatus?: () => Promise<BrainStatusSnapshot | null>
  /** 注入 doctor warn fetcher（测试用）；返回 warn 列表第一条 reason 或 null */
  fetchDoctorWarn?: () => Promise<{ warn: boolean; reason: string }>
  /** 注入当前时间（测试用） */
  now?: () => number
  /** 是否自动启动（默认 true） */
  autoStart?: boolean
  /** 心跳间隔（测试用，默认 5s） */
  heartbeatMs?: number
  /** doctor 轮询间隔（测试用，默认 30s） */
  doctorPollMs?: number
  /** tick 间隔（测试用，默认 1s） */
  tickMs?: number
}

export type UseConnectionStateResult = {
  state: ConnectionState
  snapshot: ConnectionStateSnapshot
  badge: ConnectionBadgeVisual & { label: string }
  canSend: boolean
  canDeploy: boolean
  isInputDisabled: boolean
  isSendDisabled: boolean
  /** 手动 dispatch 信号 */
  dispatch: (signal: ConnectionSignal) => void
  /** 用户点击重连 */
  start: () => void
  /** 用户点击手动恢复（dead → connecting） */
  recover: () => void
  /** 用户退出 */
  quit: () => void
  /** 强制刷新 brain status，返回最新 snapshot（L1.2.7：调用方需要同步判断状态） */
  refresh: () => Promise<ConnectionStateSnapshot>
}

/**
 * 默认 brain status fetcher：调主进程 IPC。
 */
async function defaultFetchBrainStatus(): Promise<BrainStatusSnapshot | null> {
  try {
    return (await window.archerDesktop?.getBrainStatus?.()) ?? null
  } catch {
    return null
  }
}

/**
 * 默认 doctor warn fetcher：调本地 API /config/doctor。
 */
async function defaultFetchDoctorWarn(): Promise<{ warn: boolean; reason: string }> {
  try {
    const token = await window.archerDesktop?.getApiToken?.()
    if (!token) return { warn: false, reason: '' }
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 2000)
    try {
      const response = await fetch('http://127.0.0.1:8765/config/doctor', {
        signal: controller.signal,
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!response.ok) return { warn: false, reason: '' }
      const data = await response.json() as {
        ok?: boolean
        warnings?: Array<{ key: string; message: string }>
        warns?: Array<{ key: string; message: string }>
      }
      const warns = data.warnings || data.warns || []
      if (!Array.isArray(warns) || warns.length === 0) return { warn: false, reason: '' }
      return { warn: true, reason: warns[0]?.message || '配置诊断有警告' }
    } finally {
      clearTimeout(timeout)
    }
  } catch {
    return { warn: false, reason: '' }
  }
}

export function useConnectionState(options: UseConnectionStateOptions = {}): UseConnectionStateResult {
  const {
    fetchBrainStatus = defaultFetchBrainStatus,
    fetchDoctorWarn = defaultFetchDoctorWarn,
    now = Date.now,
    autoStart = true,
    heartbeatMs = HEARTBEAT_INTERVAL_MS,
    doctorPollMs = DOCTOR_POLL_INTERVAL_MS,
    tickMs = TICK_INTERVAL_MS,
  } = options

  const engineRef = React.useRef<ConnectionStateEngine>(new ConnectionStateEngine())
  const [snapshot, setSnapshot] = React.useState<ConnectionStateSnapshot>(() => engineRef.current.get())
  const doctorWarnRef = React.useRef<{ warn: boolean; reason: string }>({ warn: false, reason: '' })

  const dispatch = React.useCallback((signal: ConnectionSignal) => {
    const next = engineRef.current.dispatch(signal)
    setSnapshot(next)
  }, [])

  const start = React.useCallback(() => {
    dispatch({ kind: 'start' })
  }, [dispatch])

  const recover = React.useCallback(() => {
    dispatch({ kind: 'user_recover' })
  }, [dispatch])

  const quit = React.useCallback(() => {
    dispatch({ kind: 'user_quit' })
  }, [dispatch])

  const refresh = React.useCallback(async (): Promise<ConnectionStateSnapshot> => {
    const brain = await fetchBrainStatus()
    if (!brain) return engineRef.current.get()
    const next = engineRef.current.onBrainStatus(brain, doctorWarnRef.current.warn, now())
    setSnapshot(next)
    return next
  }, [fetchBrainStatus, now])

  // autoStart
  React.useEffect(() => {
    if (!autoStart) return
    dispatch({ kind: 'start' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 5s 心跳
  React.useEffect(() => {
    let cancelled = false
    const timer = setInterval(async () => {
      const brain = await fetchBrainStatus()
      if (cancelled || !brain) return
      const next = engineRef.current.onBrainStatus(brain, doctorWarnRef.current.warn, now())
      setSnapshot(next)
    }, heartbeatMs)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [fetchBrainStatus, heartbeatMs, now])

  // 30s doctor
  React.useEffect(() => {
    let cancelled = false
    const timer = setInterval(async () => {
      const result = await fetchDoctorWarn()
      if (cancelled) return
      doctorWarnRef.current = result
      // doctor warn 变化时，触发一次 brain status 刷新（让 engine 重新决策）
      const brain = await fetchBrainStatus()
      if (cancelled || !brain) return
      const next = engineRef.current.onBrainStatus(brain, result.warn, now())
      setSnapshot(next)
    }, doctorPollMs)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [fetchDoctorWarn, doctorPollMs, fetchBrainStatus, now])

  // 1s tick（超时检查）
  React.useEffect(() => {
    const timer = setInterval(() => {
      const next = engineRef.current.onTick(now())
      if (next !== engineRef.current.get()) {
        setSnapshot(next)
      }
    }, tickMs)
    return () => clearInterval(timer)
  }, [tickMs, now])

  const state = snapshot.state
  const badge = { ...snapshotBadgeVisual(snapshot), label: snapshotBadgeLabel(snapshot) }

  return {
    state,
    snapshot,
    badge,
    canSend: state === 'ready' || state === 'degraded',
    canDeploy: state === 'ready',
    isInputDisabled: state === 'dead',
    isSendDisabled: state !== 'ready' && state !== 'degraded',
    dispatch,
    start,
    recover,
    quit,
    refresh,
  }
}
