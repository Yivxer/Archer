import { describe, expect, it } from 'vitest'
import {
  badgeLabel,
  badgeVisual,
  brainReasonToState,
  canDeploy,
  canSend,
  CONNECTION_STATES,
  type ConnectionState,
  type ConnectionSignal,
  isInputDisabled,
  isSendDisabled,
  transition,
} from '../connectionState'

describe('connectionState — 6 状态枚举', () => {
  it('定义 6 个状态，顺序与稳定性框架 §四 一致', () => {
    expect(CONNECTION_STATES).toEqual([
      'disconnected',
      'connecting',
      'ready',
      'degraded',
      'recovering',
      'dead',
    ])
  })
})

// ───────────────────────── 17 条转移规则 ─────────────────────────

describe('transition — 17 条转移规则', () => {
  type Case = {
    name: string
    from: ConnectionState
    signal: ConnectionSignal
    expected: ConnectionState | null
  }

  const cases: Case[] = [
    // ── 1. disconnected → connecting (start) ──
    {
      name: 'T1: disconnected + start → connecting',
      from: 'disconnected',
      signal: { kind: 'start' },
      expected: 'connecting',
    },
    // ── 2. connecting → ready (health_ok + ready + token + doctor clear) ──
    {
      name: 'T2: connecting + health_ok(ready,token,clear) → ready',
      from: 'connecting',
      signal: { kind: 'connecting_health_ok', readyOk: true, tokenOk: true, doctorWarn: false },
      expected: 'ready',
    },
    // ── 3. connecting → degraded (health_ok but /ready 5xx) ──
    {
      name: 'T3: connecting + health_ok(!ready) → degraded',
      from: 'connecting',
      signal: { kind: 'connecting_health_ok', readyOk: false, tokenOk: true, doctorWarn: false },
      expected: 'degraded',
    },
    // ── 4. connecting → degraded (doctor warn) ──
    {
      name: 'T4: connecting + health_ok(doctorWarn) → degraded',
      from: 'connecting',
      signal: { kind: 'connecting_health_ok', readyOk: true, tokenOk: true, doctorWarn: true },
      expected: 'degraded',
    },
    // ── 5. connecting → dead (health 5xx) ──
    {
      name: 'T5: connecting + health_5xx → dead',
      from: 'connecting',
      signal: { kind: 'connecting_health_5xx' },
      expected: 'dead',
    },
    // ── 6. connecting → dead (launch_fail: missing_python) ──
    {
      name: 'T6: connecting + launch_fail(missing_python) → dead',
      from: 'connecting',
      signal: { kind: 'connecting_launch_fail', reason: 'missing_python' },
      expected: 'dead',
    },
    // ── 7. connecting → dead (timeout 15s) ──
    {
      name: 'T7: connecting + timeout_15s → dead',
      from: 'connecting',
      signal: { kind: 'connecting_timeout_15s' },
      expected: 'dead',
    },
    // ── 8. ready → recovering (3 次连续 /health 超时) ──
    {
      name: 'T8: ready + health_timeout_streak(3) → recovering',
      from: 'ready',
      signal: { kind: 'health_timeout_streak', count: 3 },
      expected: 'recovering',
    },
    // ── 9. ready → degraded (doctor warn) ──
    {
      name: 'T9: ready + doctor_warn → degraded',
      from: 'ready',
      signal: { kind: 'doctor_warn', reason: 'Obsidian vault 未配置' },
      expected: 'degraded',
    },
    // ── 10. ready → degraded (/ready 5xx) ──
    {
      name: 'T10: ready + ready_5xx → degraded',
      from: 'ready',
      signal: { kind: 'ready_5xx' },
      expected: 'degraded',
    },
    // ── 11. degraded → ready (doctor clear + /ready 200) ──
    {
      name: 'T11: degraded + doctor_clear(ready) → ready',
      from: 'degraded',
      signal: { kind: 'doctor_clear', readyOk: true },
      expected: 'ready',
    },
    // ── 12. degraded → recovering (3 次连续 /health 超时) ──
    {
      name: 'T12: degraded + health_timeout_streak(3) → recovering',
      from: 'degraded',
      signal: { kind: 'health_timeout_streak', count: 3 },
      expected: 'recovering',
    },
    // ── 13. recovering → ready (restart 后 /ready 200) ──
    {
      name: 'T13: recovering + restart_attempt(1, ok) → ready',
      from: 'recovering',
      signal: { kind: 'restart_attempt', attempt: 1, readyOk: true },
      expected: 'ready',
    },
    // ── 14. recovering → recovering (第 1 次失败) ──
    {
      name: 'T14: recovering + restart_attempt(1, !ok) → recovering',
      from: 'recovering',
      signal: { kind: 'restart_attempt', attempt: 1, readyOk: false },
      expected: 'recovering',
    },
    // ── 15. recovering → dead (第 2 次失败) ──
    {
      name: 'T15: recovering + restart_attempt(2, !ok) → dead',
      from: 'recovering',
      signal: { kind: 'restart_attempt', attempt: 2, readyOk: false },
      expected: 'dead',
    },
    // ── 16. recovering → dead (restart 超时 30s) ──
    {
      name: 'T16: recovering + restart_timeout_30s → dead',
      from: 'recovering',
      signal: { kind: 'restart_timeout_30s' },
      expected: 'dead',
    },
    // ── 17. dead → connecting (user_recover) ──
    {
      name: 'T17: dead + user_recover → connecting',
      from: 'dead',
      signal: { kind: 'user_recover' },
      expected: 'connecting',
    },
  ]

  for (const c of cases) {
    it(c.name, () => {
      expect(transition(c.from, c.signal)).toBe(c.expected)
    })
  }

  // ── 任意 → disconnected (user_quit) ──
  it('user_quit 从任意状态回到 disconnected', () => {
    for (const s of CONNECTION_STATES) {
      expect(transition(s, { kind: 'user_quit' })).toBe('disconnected')
    }
  })
})

// ───────────────────────── 去抖/振荡保护 ─────────────────────────

describe('transition — 去抖/振荡保护', () => {
  it('单次 /health 抖动不切 recovering（count < 3）', () => {
    expect(transition('ready', { kind: 'health_timeout_streak', count: 1 })).toBeNull()
    expect(transition('ready', { kind: 'health_timeout_streak', count: 2 })).toBeNull()
  })

  it('3 次连续才算（count >= 3 切 recovering）', () => {
    expect(transition('ready', { kind: 'health_timeout_streak', count: 3 })).toBe('recovering')
    expect(transition('ready', { kind: 'health_timeout_streak', count: 5 })).toBe('recovering')
  })

  it('非法信号在当前状态返回 null（不抛异常）', () => {
    // ready 状态下收 start 信号
    expect(transition('ready', { kind: 'start' })).toBeNull()
    // disconnected 状态下收 health_ok
    expect(
      transition('disconnected', {
        kind: 'connecting_health_ok',
        readyOk: true,
        tokenOk: true,
        doctorWarn: false,
      }),
    ).toBeNull()
    // dead 状态下收 health_ok（dead 不再发请求）
    expect(
      transition('dead', {
        kind: 'connecting_health_ok',
        readyOk: true,
        tokenOk: true,
        doctorWarn: false,
      }),
    ).toBeNull()
  })

  it('不变量 1: recovering 状态下 start 信号不触发新 restart', () => {
    expect(transition('recovering', { kind: 'start' })).toBeNull()
  })

  it('不变量 5: connecting → ready 必须经过 doctor clear（doctorWarn 时切 degraded）', () => {
    expect(
      transition('connecting', {
        kind: 'connecting_health_ok',
        readyOk: true,
        tokenOk: true,
        doctorWarn: true,
      }),
    ).toBe('degraded')
  })

  it('connecting → dead when token 校验失败', () => {
    expect(
      transition('connecting', {
        kind: 'connecting_health_ok',
        readyOk: true,
        tokenOk: false,
        doctorWarn: false,
      }),
    ).toBe('dead')
  })
})

// ───────────────────────── 不变量辅助 ─────────────────────────

describe('不变量辅助函数', () => {
  describe('canSend', () => {
    it('ready / degraded 允许发送', () => {
      expect(canSend('ready')).toBe(true)
      expect(canSend('degraded')).toBe(true)
    })
    it('其他状态禁止发送', () => {
      expect(canSend('disconnected')).toBe(false)
      expect(canSend('connecting')).toBe(false)
      expect(canSend('recovering')).toBe(false)
      expect(canSend('dead')).toBe(false)
    })
  })

  describe('canDeploy', () => {
    it('仅 ready 允许 deploy', () => {
      expect(canDeploy('ready')).toBe(true)
      expect(canDeploy('degraded')).toBe(false) // degraded 屏蔽 deploy
      expect(canDeploy('dead')).toBe(false)
    })
  })

  describe('isInputDisabled', () => {
    it('仅 dead 禁用输入框', () => {
      expect(isInputDisabled('dead')).toBe(true)
      expect(isInputDisabled('disconnected')).toBe(false)
      expect(isInputDisabled('connecting')).toBe(false)
      expect(isInputDisabled('ready')).toBe(false)
      expect(isInputDisabled('degraded')).toBe(false)
      expect(isInputDisabled('recovering')).toBe(false)
    })
  })

  describe('isSendDisabled', () => {
    it('与 canSend 互补', () => {
      for (const s of CONNECTION_STATES) {
        expect(isSendDisabled(s)).toBe(!canSend(s))
      }
    })
  })
})

// ───────────────────────── 视觉规范 ─────────────────────────

describe('badgeVisual — 6 状态视觉规范', () => {
  it('每个状态都有视觉定义', () => {
    for (const s of CONNECTION_STATES) {
      const v = badgeVisual(s)
      expect(v.state).toBe(s)
      expect(v.color).toMatch(/^#[0-9a-f]{6}$/i)
      expect(v.label.length).toBeGreaterThan(0)
      expect(v.labelEn.length).toBeGreaterThan(0)
    }
  })

  it('颜色匹配稳定性框架 §四 徽章视觉规范表', () => {
    expect(badgeVisual('disconnected').color).toBe('#9ca3af') // 灰
    expect(badgeVisual('connecting').color).toBe('#f59e0b')   // 琥珀
    expect(badgeVisual('ready').color).toBe('#10b981')         // 翠绿
    expect(badgeVisual('degraded').color).toBe('#f59e0b')      // 琥珀
    expect(badgeVisual('recovering').color).toBe('#3b82f6')    // 蓝
    expect(badgeVisual('dead').color).toBe('#ef4444')          // 红
  })

  it('dot 样式各不相同（视觉区分度）', () => {
    const dots = CONNECTION_STATES.map((s) => badgeVisual(s).dot)
    expect(new Set(dots).size).toBe(6)
  })
})

describe('badgeLabel — 带原因的文案', () => {
  it('degraded 状态拼装原因', () => {
    expect(badgeLabel('degraded', 'Obsidian vault 未配置')).toBe(
      '降级中：Obsidian vault 未配置',
    )
  })

  it('其他状态忽略 reason', () => {
    expect(badgeLabel('ready', 'whatever')).toBe('已就绪')
    expect(badgeLabel('dead', 'whatever')).toBe('本地 API 不可用')
  })

  it('degraded 无 reason 时只显示"降级中"', () => {
    expect(badgeLabel('degraded')).toBe('降级中')
  })
})

// ───────────────────────── Brain status 映射 ─────────────────────────

describe('brainReasonToState — L1.2.3 预留映射', () => {
  it('missing_python / missing_script / port_down / token_mismatch → dead', () => {
    expect(brainReasonToState('missing_python')).toBe('dead')
    expect(brainReasonToState('missing_script')).toBe('dead')
    expect(brainReasonToState('port_down')).toBe('dead')
    expect(brainReasonToState('token_mismatch')).toBe('dead')
  })

  it('not_ready → connecting', () => {
    expect(brainReasonToState('not_ready')).toBe('connecting')
  })

  it('owned / reused / started → ready（doctor clear）', () => {
    expect(brainReasonToState('owned', { doctorWarn: false })).toBe('ready')
    expect(brainReasonToState('reused', { doctorWarn: false })).toBe('ready')
    expect(brainReasonToState('started', { doctorWarn: false })).toBe('ready')
  })

  it('owned / reused / started → degraded（doctor warn）', () => {
    expect(brainReasonToState('owned', { doctorWarn: true })).toBe('degraded')
    expect(brainReasonToState('reused', { doctorWarn: true })).toBe('degraded')
    expect(brainReasonToState('started', { doctorWarn: true })).toBe('degraded')
  })
})
