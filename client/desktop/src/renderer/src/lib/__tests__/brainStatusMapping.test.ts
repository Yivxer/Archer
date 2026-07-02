/**
 * L1.2.3 — apiProcess brain status → 6 状态映射测试。
 *
 * 映射契约：
 *   - main 进程的 brainStatusReason() 输出 7 个 reason 字符串
 *   - renderer 的 brainReasonToState() 把这 7 个 reason 映射到 6 状态
 *   - useConnectionState 的 onBrainStatus() 用 BrainStatusSnapshot 字段
 *     做更智能的状态机推进（已在 T1-T10 覆盖）
 *
 * 本测试聚焦 reason 字符串契约，确保 main 进程输出的 reason 在 renderer
 * 能被正确解析。物理隔离下不能跨进程 import，所以这里测 renderer 侧的
 * brainReasonToState 对所有 7 个 reason 的行为。
 */

import { describe, expect, it } from 'vitest'

import {
  brainReasonToState,
  type BrainStatusReason,
} from '../connectionState'

// main 进程 brainStatusReason() 的 7 个输出值（字符串契约）
// 来源：client/desktop/src/main/apiProcess.ts BrainStatusReason 类型
const MAIN_PROCESS_REASONS: BrainStatusReason[] = [
  'missing_python',
  'missing_script',
  'port_down',
  'not_ready',
  'token_mismatch',
  'owned',
  'reused',
]

describe('L1.2.3 — brain status reason → 6 状态映射契约', () => {
  describe('main 进程 7 个 reason 全覆盖', () => {
    // 表格驱动：每个 reason 必须有明确的映射结果
    type Case = {
      reason: BrainStatusReason
      doctorClear: 'dead' | 'connecting' | 'ready'
      doctorWarn: 'dead' | 'connecting' | 'degraded' | 'ready'
    }

    const cases: Case[] = [
      // dead 类：4 个 reason，无论 doctor 状态都 → dead
      { reason: 'missing_python', doctorClear: 'dead', doctorWarn: 'dead' },
      { reason: 'missing_script', doctorClear: 'dead', doctorWarn: 'dead' },
      { reason: 'port_down', doctorClear: 'dead', doctorWarn: 'dead' },
      { reason: 'token_mismatch', doctorClear: 'dead', doctorWarn: 'dead' },
      // connecting 类：not_ready 不响应 doctorWarn
      { reason: 'not_ready', doctorClear: 'connecting', doctorWarn: 'connecting' },
      // ready/degraded 类：owned/reused 响应 doctorWarn
      { reason: 'owned', doctorClear: 'ready', doctorWarn: 'degraded' },
      { reason: 'reused', doctorClear: 'ready', doctorWarn: 'degraded' },
    ]

    for (const c of cases) {
      it(`${c.reason} + doctor clear → ${c.doctorClear}`, () => {
        expect(brainReasonToState(c.reason, { doctorWarn: false })).toBe(c.doctorClear)
      })
      it(`${c.reason} + doctor warn → ${c.doctorWarn}`, () => {
        expect(brainReasonToState(c.reason, { doctorWarn: true })).toBe(c.doctorWarn)
      })
    }

    // 验证 7 个 reason 全部覆盖
    it('main 进程 7 个 reason 全部测试覆盖', () => {
      const testedReasons = cases.map((c) => c.reason)
      expect(new Set(testedReasons)).toEqual(new Set(MAIN_PROCESS_REASONS))
    })
  })

  describe('dead 类 reason 的不变量', () => {
    it('dead 类 reason 在任何 doctor 状态下都 → dead', () => {
      const deadReasons: BrainStatusReason[] = [
        'missing_python',
        'missing_script',
        'port_down',
        'token_mismatch',
      ]
      for (const r of deadReasons) {
        expect(brainReasonToState(r, { doctorWarn: false })).toBe('dead')
        expect(brainReasonToState(r, { doctorWarn: true })).toBe('dead')
      }
    })
  })

  describe('not_ready 的不变量', () => {
    it('not_ready 不响应 doctorWarn（/ready 没通不算 degraded）', () => {
      expect(brainReasonToState('not_ready', { doctorWarn: false })).toBe('connecting')
      expect(brainReasonToState('not_ready', { doctorWarn: true })).toBe('connecting')
    })
  })

  describe('owned/reused 的 doctor 响应', () => {
    it('doctor clear → ready', () => {
      expect(brainReasonToState('owned', { doctorWarn: false })).toBe('ready')
      expect(brainReasonToState('reused', { doctorWarn: false })).toBe('ready')
    })
    it('doctor warn → degraded', () => {
      expect(brainReasonToState('owned', { doctorWarn: true })).toBe('degraded')
      expect(brainReasonToState('reused', { doctorWarn: true })).toBe('degraded')
    })
  })

  describe('readyOk 字段的辅助判定', () => {
    it('owned + readyOk=false 时仍为 ready（readyOk 由 onBrainStatus 处理）', () => {
      // brainReasonToState 只看 reason + doctorWarn
      // readyOk 字段在 useConnectionState.onBrainStatus 里单独处理
      // 这里验证 brainReasonToState 不依赖 readyOk
      expect(brainReasonToState('owned', { doctorWarn: false, readyOk: false })).toBe('ready')
      expect(brainReasonToState('owned', { doctorWarn: false, readyOk: true })).toBe('ready')
    })
  })
})
