/**
 * L1.2.4 — <ConnectionBadge /> 组件测试。
 *
 * 测试策略：
 *   - 不引入 @testing-library/react，用 React 19 + react-dom/server 静态渲染
 *   - 验证 6 状态的 className / label / aria-label / title
 *   - 不测 CSS 动画（CSS 层面）
 */

import { describe, expect, it } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { ConnectionBadge } from '../ConnectionBadge'
import { CONNECTION_STATES, type ConnectionState } from '../../lib/connectionState'

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
}

describe('ConnectionBadge — 6 状态视觉规范', () => {
  describe('基础渲染', () => {
    it('6 状态都能渲染', () => {
      for (const state of CONNECTION_STATES) {
        const html = render(<ConnectionBadge state={state} />)
        expect(html).toContain('connection-badge')
        expect(html.length).toBeGreaterThan(0)
      }
    })

    it('className 包含状态名', () => {
      for (const state of CONNECTION_STATES) {
        const html = render(<ConnectionBadge state={state} />)
        expect(html).toContain(`connection-badge-${state}`)
      }
    })

    it('className 包含尺寸', () => {
      const sizes = ['footer', 'banner', 'inline'] as const
      for (const size of sizes) {
        const html = render(<ConnectionBadge state="ready" size={size} />)
        expect(html).toContain(`connection-badge-${size}`)
      }
    })
  })

  describe('文案', () => {
    type Case = { state: ConnectionState; expected: string }
    const cases: Case[] = [
      { state: 'disconnected', expected: '未连接' },
      { state: 'connecting', expected: '正在连接…' },
      { state: 'ready', expected: '已就绪' },
      { state: 'degraded', expected: '降级中' },
      { state: 'recovering', expected: '正在恢复本地 API…' },
      { state: 'dead', expected: '本地 API 不可用' },
    ]

    for (const c of cases) {
      it(`${c.state} 显示"${c.expected}"`, () => {
        const html = render(<ConnectionBadge state={c.state} />)
        expect(html).toContain(c.expected)
      })
    }

    it('degraded 拼装原因', () => {
      const html = render(
        <ConnectionBadge state="degraded" reason="Obsidian vault 未配置" />,
      )
      expect(html).toContain('降级中：Obsidian vault 未配置')
    })

    it('dead 显示固定文案（deadReason 不影响 label）', () => {
      const html = render(
        <ConnectionBadge state="dead" deadReason="启动失败：missing_python" />,
      )
      expect(html).toContain('本地 API 不可用')
      // 但 title 包含详情
      expect(html).toContain('missing_python')
    })
  })

  describe('aria 与 title', () => {
    it('aria-label 等于 label', () => {
      const html = render(<ConnectionBadge state="ready" />)
      expect(html).toContain('aria-label="已就绪"')
    })

    it('title 含英文 fallback', () => {
      const html = render(<ConnectionBadge state="ready" />)
      expect(html).toContain('title="Ready"')
    })

    it('degraded title 含原因', () => {
      const html = render(
        <ConnectionBadge state="degraded" reason="Obsidian vault 未配置" />,
      )
      expect(html).toContain('Degraded: Obsidian vault 未配置')
    })

    it('dead title 含 deadReason', () => {
      const html = render(
        <ConnectionBadge state="dead" deadReason="启动失败：missing_python" />,
      )
      expect(html).toContain('Local API unavailable: 启动失败：missing_python')
    })
  })

  describe('圆点样式', () => {
    it('disconnected 渲染空心圆', () => {
      const html = render(<ConnectionBadge state="disconnected" />)
      expect(html).toContain('cb-dot-hollow')
    })

    it('connecting 渲染旋转环', () => {
      const html = render(<ConnectionBadge state="connecting" />)
      expect(html).toContain('cb-dot-spin')
    })

    it('ready 渲染实心圆+柔光', () => {
      const html = render(<ConnectionBadge state="ready" />)
      expect(html).toContain('cb-dot-solid-glow')
    })

    it('degraded 渲染三角', () => {
      const html = render(<ConnectionBadge state="degraded" />)
      expect(html).toContain('cb-dot-triangle')
    })

    it('recovering 渲染旋转弧', () => {
      const html = render(<ConnectionBadge state="recovering" />)
      expect(html).toContain('cb-dot-arc')
    })

    it('dead 渲染实心叉', () => {
      const html = render(<ConnectionBadge state="dead" />)
      expect(html).toContain('cb-dot-cross')
      expect(html).toContain('cb-cross-line')
    })
  })

  describe('颜色（inline style）', () => {
    it('disconnected 用 #9ca3af', () => {
      const html = render(<ConnectionBadge state="disconnected" />)
      expect(html).toContain('#9ca3af')
    })

    it('ready 用 #10b981', () => {
      const html = render(<ConnectionBadge state="ready" />)
      expect(html).toContain('#10b981')
    })

    it('dead 用 #ef4444', () => {
      const html = render(<ConnectionBadge state="dead" />)
      expect(html).toContain('#ef4444')
    })

    it('recovering 用 #3b82f6', () => {
      const html = render(<ConnectionBadge state="recovering" />)
      expect(html).toContain('#3b82f6')
    })
  })

  describe('交互', () => {
    it('无 onClick 时按钮 disabled', () => {
      const html = render(<ConnectionBadge state="ready" />)
      expect(html).toContain('disabled')
    })

    it('有 onClick 时按钮 enabled + clickable class', () => {
      const html = render(<ConnectionBadge state="ready" onClick={() => {}} />)
      expect(html).toContain('clickable')
      expect(html).not.toContain('disabled')
    })

    it('showLabel=false 不显示文案', () => {
      const html = render(<ConnectionBadge state="ready" showLabel={false} />)
      expect(html).not.toContain('connection-badge-label')
    })
  })
})
