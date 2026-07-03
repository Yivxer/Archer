/**
 * L4.8 — <EmptyState /> 组件测试。
 *
 * 测试策略：
 *   - 用 react-dom/server 静态渲染 + 字符串断言
 *   - 覆盖：标准/紧凑两种模式、title/hint/action/icon、默认 Inbox 图标、
 *     data-compact、role="status"、aria-label
 */

import { describe, expect, it } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Inbox, FileText } from 'lucide-react'

import { EmptyState } from '../EmptyState'

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
}

describe('EmptyState — L4.8 基础渲染', () => {
  it('渲染 empty-state 容器 + role="status"', () => {
    const html = render(<EmptyState title="暂无记忆" />)
    expect(html).toContain('class="empty-state')
    expect(html).toContain('role="status"')
  })

  it('aria-label 等于 title', () => {
    const html = render(<EmptyState title="暂无后台任务" />)
    expect(html).toContain('aria-label="暂无后台任务"')
  })

  it('渲染 title', () => {
    const html = render(<EmptyState title="暂无记忆" />)
    expect(html).toContain('暂无记忆')
    expect(html).toContain('empty-state-title')
  })
})

describe('EmptyState — 标准模式（默认）', () => {
  it('默认 compact=false → empty-state-standard class', () => {
    const html = render(<EmptyState title="x" />)
    expect(html).toContain('empty-state-standard')
    expect(html).not.toContain('empty-state-compact')
  })

  it('data-compact="false"', () => {
    const html = render(<EmptyState title="x" />)
    expect(html).toContain('data-compact="false"')
  })

  it('hint 提供时渲染', () => {
    const html = render(
      <EmptyState title="暂无记忆" hint="连接本地 API 后会读取" />,
    )
    expect(html).toContain('empty-state-hint')
    expect(html).toContain('连接本地 API 后会读取')
  })

  it('hint 缺失时不渲染 hint', () => {
    const html = render(<EmptyState title="x" />)
    expect(html).not.toContain('empty-state-hint')
  })

  it('action 提供时渲染', () => {
    const html = render(
      <EmptyState
        title="x"
        action={<button type="button">重试</button>}
      />,
    )
    expect(html).toContain('empty-state-action')
    expect(html).toContain('重试')
  })

  it('action 缺失时不渲染 action 区', () => {
    const html = render(<EmptyState title="x" />)
    expect(html).not.toContain('empty-state-action')
  })
})

describe('EmptyState — 紧凑模式', () => {
  it('compact=true → empty-state-compact class', () => {
    const html = render(<EmptyState title="x" compact />)
    expect(html).toContain('empty-state-compact')
    expect(html).not.toContain('empty-state-standard')
  })

  it('data-compact="true"', () => {
    const html = render(<EmptyState title="x" compact />)
    expect(html).toContain('data-compact="true"')
  })

  it('紧凑模式 + hint 同行渲染', () => {
    const html = render(
      <EmptyState title="暂无诊断事件" hint="稍后再试" compact />,
    )
    expect(html).toContain('empty-state-compact')
    expect(html).toContain('暂无诊断事件')
    expect(html).toContain('稍后再试')
  })
})

describe('EmptyState — 图标', () => {
  it('默认 Inbox 图标', () => {
    const html = render(<EmptyState title="x" />)
    expect(html).toContain('empty-state-icon')
    // lucide-react Inbox 渲染为 svg
    expect(html).toContain('<svg')
  })

  it('自定义图标 FileText', () => {
    const html = render(<EmptyState title="x" icon={FileText} />)
    expect(html).toContain('empty-state-icon')
    expect(html).toContain('<svg')
  })

  it('标准模式图标 size=32', () => {
    const html = render(<EmptyState title="x" />)
    // lucide-react 把 size 注入到 svg width/height 属性
    expect(html).toMatch(/width="32"/)
    expect(html).toMatch(/height="32"/)
  })

  it('紧凑模式图标 size=13', () => {
    const html = render(<EmptyState title="x" compact />)
    expect(html).toMatch(/width="13"/)
    expect(html).toMatch(/height="13"/)
  })
})

describe('EmptyState — 组合场景', () => {
  it('全部 props 提供：标准模式完整结构', () => {
    const html = render(
      <EmptyState
        title="暂无记忆"
        hint="连接本地 API 后会读取"
        action={<button type="button">连接</button>}
      />,
    )
    expect(html).toContain('empty-state-standard')
    expect(html).toContain('暂无记忆')
    expect(html).toContain('连接本地 API 后会读取')
    expect(html).toContain('连接')
  })

  it('紧凑模式 + action', () => {
    const html = render(
      <EmptyState
        title="暂无任务"
        compact
        action={<button type="button">刷新</button>}
      />,
    )
    expect(html).toContain('empty-state-compact')
    expect(html).toContain('暂无任务')
    expect(html).toContain('刷新')
  })
})
