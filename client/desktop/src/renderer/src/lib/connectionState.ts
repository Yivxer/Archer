/**
 * L1.2.1 — 第 1 层连接状态机：6 状态枚举 + 17 条转移规则 + 不变量。
 *
 * 契约来源：Archer 稳定性框架 §四（第 1 层：连接状态机）。
 *
 * 6 状态：
 *   disconnected → connecting → ready → degraded → recovering → dead
 *
 * 不变量（invariants）：
 *   1. `recovering` 状态下不再触发新的 restart（避免重启风暴）
 *   2. `dead` 状态下不再发任何 API 请求（避免给挂掉的 API 雪上加霜）
 *   3. `degraded` 状态下不阻塞聊天，但屏蔽 deploy-remote 和 write-vault
 *   4. 状态转换必须经过 transition()，所有转换写入 trace log
 *   5. 任意状态 → ready 必须经过 doctor clear 检查，避免"假就绪"
 */

// ───────────────────────── 状态枚举 ─────────────────────────

export type ConnectionState =
  | 'disconnected' // 未尝试连接或主动断开
  | 'connecting'   // 首次或重试中
  | 'ready'        // /health + /ready + token 全通 + doctor clear
  | 'degraded'     // API 活着但 doctor 有 warn / 模型 profile 错
  | 'recovering'   // 检测到 dead 后自动重启 API 中
  | 'dead'         // restart 多次失败

export const CONNECTION_STATES: readonly ConnectionState[] = [
  'disconnected',
  'connecting',
  'ready',
  'degraded',
  'recovering',
  'dead',
] as const

// ───────────────────────── 信号 ─────────────────────────

/**
 * 状态机输入信号。每条对应稳定性框架 §四 转移矩阵的一行。
 */
export type ConnectionSignal =
  // disconnected / dead → connecting
  | { kind: 'start' }
  // connecting → ready / degraded / dead
  | { kind: 'connecting_health_ok'; readyOk: boolean; tokenOk: boolean; doctorWarn: boolean }
  | { kind: 'connecting_health_5xx' }
  | { kind: 'connecting_launch_fail'; reason: LaunchFailReason }
  | { kind: 'connecting_timeout_15s' }
  // ready / degraded → degraded / recovering
  | { kind: 'health_timeout_streak'; count: number }
  | { kind: 'doctor_warn'; reason: string }
  | { kind: 'doctor_clear'; readyOk: boolean }
  | { kind: 'ready_5xx' }
  // recovering → ready / dead
  | { kind: 'restart_attempt'; attempt: number; readyOk: boolean }
  | { kind: 'restart_timeout_30s' }
  // dead → connecting
  | { kind: 'user_recover' }
  // 任意 → disconnected
  | { kind: 'user_quit' }

export type LaunchFailReason =
  | 'missing_python'
  | 'missing_script'
  | 'port_down'
  | 'token_mismatch'

// ───────────────────────── 转移规则 ─────────────────────────

/**
 * 17 条转移规则（对应稳定性框架 §四 转移矩阵表）。
 *
 * @returns 新状态；若信号在当前状态非法，返回 null（调用方决定丢弃或日志）
 */
export function transition(
  state: ConnectionState,
  signal: ConnectionSignal,
): ConnectionState | null {
  switch (signal.kind) {
    // ── disconnected / dead → connecting ──
    case 'start': {
      if (state === 'disconnected' || state === 'dead') return 'connecting'
      return null
    }
    case 'user_recover': {
      // 仅 dead → connecting（用户点击"手动恢复"）
      if (state === 'dead') return 'connecting'
      return null
    }

    // ── connecting → ready / degraded / dead ──
    case 'connecting_health_ok': {
      if (state !== 'connecting') return null
      // 不变量 5：任意 → ready 必须经过 doctor clear
      if (!signal.readyOk) return 'degraded'
      if (!signal.tokenOk) return 'dead' // token 校验失败视为 dead
      if (signal.doctorWarn) return 'degraded'
      return 'ready'
    }
    case 'connecting_health_5xx': {
      if (state !== 'connecting') return null
      // 单次即触发，无去抖
      return 'dead'
    }
    case 'connecting_launch_fail': {
      if (state !== 'connecting') return null
      // missing_python / missing_script / port_down / token_mismatch → dead
      return 'dead'
    }
    case 'connecting_timeout_15s': {
      if (state !== 'connecting') return null
      return 'dead'
    }

    // ── ready / degraded → degraded / recovering ──
    case 'health_timeout_streak': {
      if (state !== 'ready' && state !== 'degraded') return null
      // 3 次连续才算，单次抖动不切
      if (signal.count >= 3) return 'recovering'
      return null
    }
    case 'doctor_warn': {
      if (state === 'ready' || state === 'degraded') return 'degraded'
      return null
    }
    case 'doctor_clear': {
      if (state !== 'degraded') return null
      // doctor clear 且 /ready 200 → ready
      return signal.readyOk ? 'ready' : 'degraded'
    }
    case 'ready_5xx': {
      if (state === 'ready') return 'degraded'
      return null
    }

    // ── recovering → ready / dead ──
    case 'restart_attempt': {
      if (state !== 'recovering') return null
      if (signal.readyOk) return 'ready'
      // restart 第 2 次失败（attempt >= 2）→ dead
      if (signal.attempt >= 2) return 'dead'
      // 第 1 次失败仍 recovering，继续重试
      return 'recovering'
    }
    case 'restart_timeout_30s': {
      if (state !== 'recovering') return null
      return 'dead'
    }

    // ── 任意 → disconnected ──
    case 'user_quit': {
      // 任意状态 → disconnected，不触发 restart
      return 'disconnected'
    }

    default: {
      // 穷尽性检查（编译时保证）
      const _exhaustive: never = signal
      void _exhaustive
      return null
    }
  }
}

// ───────────────────────── 不变量辅助 ─────────────────────────

/**
 * 是否允许发送聊天消息。
 * - ready / degraded 允许（degraded 下 deploy/write 受限，但聊天不阻塞）
 * - disconnected / connecting / recovering / dead 禁止
 */
export function canSend(state: ConnectionState): boolean {
  return state === 'ready' || state === 'degraded'
}

/**
 * 是否允许 deploy-remote / write-vault 等高危操作。
 * - 仅 ready 允许；degraded 屏蔽
 */
export function canDeploy(state: ConnectionState): boolean {
  return state === 'ready'
}

/**
 * 输入框是否 disabled。
 * - 仅 dead 禁用输入；其余状态允许输入但发送按钮可能禁用
 */
export function isInputDisabled(state: ConnectionState): boolean {
  return state === 'dead'
}

/**
 * 发送按钮是否 disabled。
 */
export function isSendDisabled(state: ConnectionState): boolean {
  return !canSend(state)
}

// ───────────────────────── 视觉规范 ─────────────────────────

export type ConnectionBadgeVisual = {
  state: ConnectionState
  /** 圆点颜色 hex */
  color: string
  /** 圆点样式 */
  dot: 'hollow' | 'spin' | 'solid-glow' | 'triangle' | 'arc' | 'cross'
  /** 中文文案（degraded 含原因占位符） */
  label: string
  /** 英文 fallback */
  labelEn: string
}

const BADGE_VISUALS: Record<ConnectionState, ConnectionBadgeVisual> = {
  disconnected: {
    state: 'disconnected',
    color: '#9ca3af',
    dot: 'hollow',
    label: '未连接',
    labelEn: 'Not connected',
  },
  connecting: {
    state: 'connecting',
    color: '#f59e0b',
    dot: 'spin',
    label: '正在连接…',
    labelEn: 'Connecting…',
  },
  ready: {
    state: 'ready',
    color: '#10b981',
    dot: 'solid-glow',
    label: '已就绪',
    labelEn: 'Ready',
  },
  degraded: {
    state: 'degraded',
    color: '#f59e0b',
    dot: 'triangle',
    label: '降级中',
    labelEn: 'Degraded',
  },
  recovering: {
    state: 'recovering',
    color: '#3b82f6',
    dot: 'arc',
    label: '正在恢复本地 API…',
    labelEn: 'Recovering local API…',
  },
  dead: {
    state: 'dead',
    color: '#ef4444',
    dot: 'cross',
    label: '本地 API 不可用',
    labelEn: 'Local API unavailable',
  },
}

export function badgeVisual(state: ConnectionState): ConnectionBadgeVisual {
  return BADGE_VISUALS[state]
}

/**
 * 拼装带原因的徽章文案（degraded 状态）。
 */
export function badgeLabel(state: ConnectionState, reason = ''): string {
  const visual = BADGE_VISUALS[state]
  if (state === 'degraded' && reason) {
    return `降级中：${reason}`
  }
  return visual.label
}

// ───────────────────────── Brain status 映射 ─────────────────────────

/**
 * L1.2.3 预留：将 apiProcess.ts 的 BrainStatusReason 映射到 6 状态。
 *
 * 映射规则（稳定性框架 §四 与现有代码的关系）：
 *   missing_python / missing_script / port_down / token_mismatch → dead
 *   not_ready → connecting 或 degraded（看上下文）
 *   owned / reused → ready 或 degraded（看 doctor warn）
 *
 * 注意：这只是"快速映射"，不替代 transition() 的完整状态机。
 * 调用方应优先用 transition() 推进状态；只在初始化或外部信号缺失时用此映射。
 */
export type BrainStatusReason =
  | 'missing_python'
  | 'missing_script'
  | 'port_down'
  | 'not_ready'
  | 'token_mismatch'
  | 'owned'
  | 'reused'
  | 'started'

export function brainReasonToState(
  reason: BrainStatusReason,
  ctx: { doctorWarn?: boolean; readyOk?: boolean } = {},
): ConnectionState {
  switch (reason) {
    case 'missing_python':
    case 'missing_script':
    case 'port_down':
    case 'token_mismatch':
      return 'dead'
    case 'not_ready':
      // 启动后 /ready 还没通 → 仍在 connecting
      return 'connecting'
    case 'owned':
    case 'reused':
    case 'started':
      // API 在跑，但 doctor warn 决定 degraded vs ready
      return ctx.doctorWarn ? 'degraded' : 'ready'
    default: {
      const _exhaustive: never = reason
      void _exhaustive
      return 'disconnected'
    }
  }
}
