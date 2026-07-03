/**
 * L4.9 — <LoadingState /> 组件测试。
 *
 * 测试策略：
 *   - 用 react-dom/server 静态渲染 + 字符串断言
 *   - 覆盖：4 个 stage 默认文案、hint 覆盖、showDots 开关、
 *     标准/紧凑两种模式、data-stage、data-compact、role="status"、aria-label
 */

import { describe, expect, it } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { LoadingState } from '../LoadingState'

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
}

describe('LoadingState — L4.9 基础渲染', () => {
  it('渲染 loading-state 容器 + role="status"', () => {
    const html = render(<LoadingState />)
    expect(html).toContain('class="loading-state')
    expect(html).toContain('role="status"')
  })

  it('默认 stage=fetching → aria-label="正在读取..."', () => {
    const html = render(<LoadingState />)
    expect(html).toContain('aria-label="正在读取..."')
    expect(html).toContain('正在读取...')
  })

  it('data-stage 注入', () => {
    const html = render(<LoadingState stage="thinking" />)
    expect(html).toContain('data-stage="thinking"')
  })

  it('data-compact 注入', () => {
    const html = render(<LoadingState compact />)
    expect(html).toContain('data-compact="true"')
  })
})

describe('LoadingState — 4 个 stage 默认文案', () => {
  const stages: Array<{ stage: 'connecting' | 'fetching' | 'thinking' | 'applying'; text: string }> = [
    { stage: 'connecting', text: '正在连接 Archer...' },
    { stage: 'fetching', text: '正在读取...' },
    { stage: 'thinking', text: 'Archer 正在想...' },
    { stage: 'applying', text: '正在应用...' },
  ]

  for (const { stage, text } of stages) {
    it(`stage=${stage} → "${text}"`, () => {
      const html = render(<LoadingState stage={stage} />)
      expect(html).toContain(text)
    })
  }
})

describe('LoadingState — hint 覆盖', () => {
  it('hint 提供时覆盖 stage 默认文案', () => {
    const html = render(
      <LoadingState stage="fetching" hint="正在读取会话" />,
    )
    expect(html).toContain('正在读取会话')
    expect(html).not.toContain('正在读取...')
  })

  it('hint 为空字符串时回退到 stage 默认文案', () => {
    const html = render(<LoadingState stage="fetching" hint="" />)
    expect(html).toContain('正在读取...')
  })

  it('hint 缺失时使用 stage 默认文案', () => {
    const html = render(<LoadingState stage="thinking" />)
    expect(html).toContain('Archer 正在想...')
  })

  it('aria-label 等于 hint（覆盖后）', () => {
    const html = render(<LoadingState hint="自定义加载中文案" />)
    expect(html).toContain('aria-label="自定义加载中文案"')
  })
})

describe('LoadingState — showDots 开关', () => {
  it('showDots 默认 true → 渲染 3 个 dot', () => {
    const html = render(<LoadingState />)
    expect(html).toContain('loading-state-dots')
    // 3 个 dot（用 class="loading-state-dot" 精确匹配，避免匹配到容器 loading-state-dots）
    const dotCount = (html.match(/class="loading-state-dot"/g) || []).length
    expect(dotCount).toBe(3)
  })

  it('showDots=false → 不渲染 dots', () => {
    const html = render(<LoadingState showDots={false} />)
    expect(html).not.toContain('loading-state-dots')
    expect(html).not.toContain('loading-state-dot')
  })

  it('showDots=false 时仍渲染文案', () => {
    const html = render(<LoadingState showDots={false} stage="connecting" />)
    expect(html).toContain('正在连接 Archer...')
    expect(html).toContain('loading-state-text')
  })
})

describe('LoadingState — 标准模式（默认）', () => {
  it('默认 compact=false → loading-state-standard class', () => {
    const html = render(<LoadingState />)
    expect(html).toContain('loading-state-standard')
    expect(html).not.toContain('loading-state-compact')
  })

  it('标准模式 dot size=6', () => {
    const html = render(<LoadingState />)
    // 3 个 dot，每个 width:6px;height:6px
    const matches = html.match(/width:6px/g) || []
    expect(matches.length).toBe(3)
  })
})

describe('LoadingState — 紧凑模式', () => {
  it('compact=true → loading-state-compact class', () => {
    const html = render(<LoadingState compact />)
    expect(html).toContain('loading-state-compact')
    expect(html).not.toContain('loading-state-standard')
  })

  it('紧凑模式 dot size=4', () => {
    const html = render(<LoadingState compact />)
    const matches = html.match(/width:4px/g) || []
    expect(matches.length).toBe(3)
  })

  it('紧凑模式 + hint', () => {
    const html = render(<LoadingState compact hint="加载中" />)
    expect(html).toContain('loading-state-compact')
    expect(html).toContain('加载中')
  })

  it('紧凑模式 + showDots=false', () => {
    const html = render(<LoadingState compact showDots={false} />)
    expect(html).toContain('loading-state-compact')
    expect(html).not.toContain('loading-state-dots')
  })
})

describe('LoadingState — dot 动画 delay', () => {
  it('3 个 dot 有递增的 animation-delay', () => {
    const html = render(<LoadingState />)
    expect(html).toContain('animation-delay:0s')
    expect(html).toContain('animation-delay:0.18s')
    expect(html).toContain('animation-delay:0.36s')
  })
})

describe('LoadingState — 组合场景', () => {
  it('stage=thinking + hint 覆盖 + compact + showDots=false', () => {
    const html = render(
      <LoadingState
        stage="thinking"
        hint="Archer 正在思考你的问题"
        compact
        showDots={false}
      />,
    )
    expect(html).toContain('loading-state-compact')
    expect(html).toContain('data-stage="thinking"')
    expect(html).toContain('Archer 正在思考你的问题')
    expect(html).not.toContain('loading-state-dots')
  })

  it('stage=connecting + 标准模式 + showDots=true', () => {
    const html = render(<LoadingState stage="connecting" />)
    expect(html).toContain('loading-state-standard')
    expect(html).toContain('data-stage="connecting"')
    expect(html).toContain('正在连接 Archer...')
    expect(html).toContain('loading-state-dots')
  })
})
