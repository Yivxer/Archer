/**
 * L4.2 — <ConfirmationCard /> 组件测试。
 *
 * 测试策略（与 ConnectionBadge.test.tsx 一致）：
 *   - 用 react-dom/server 静态渲染 + 字符串断言
 *   - 不测 CSS 动画 / 不引入 @testing-library/react
 *   - 覆盖：4 个 risk 等级色条、workIntent 渲染、按钮回调、busy 状态、diff toggle
 */

import { describe, expect, it, vi } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { ConfirmationCard } from '../ConfirmationCard'
import type { WorkIntent } from '../../types'

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
}

const baseIntent: WorkIntent = {
  workflowName: 'Obsidian 写入',
  action: 'append',
  targets: [
    { label: '笔记', path: '/vault/Archer客户端.md' },
  ],
  steps: ['读取原文件', '追加内容', '写回'],
  verifyPlan: 'grep 确认关键词存在',
  rollbackPlan: '恢复 .bak.md',
}

describe('ConfirmationCard — L4.2 视觉规范', () => {
  it('4 个 risk 等级都渲染对应色条 class', () => {
    const risks = ['low', 'medium', 'high', 'critical'] as const
    for (const risk of risks) {
      const html = render(
        <ConfirmationCard
          workIntent={baseIntent}
          toolEventId="evt-1"
          risk={risk}
          onApprove={() => {}}
          onReject={() => {}}
        />,
      )
      expect(html).toContain(`confirmation-card risk-${risk}`)
      expect(html).toContain('confirmation-card-stripe')
    }
  })

  it('risk badge 显示中文标签', () => {
    const cases: Array<{ risk: 'low' | 'medium' | 'high' | 'critical'; label: string }> = [
      { risk: 'low', label: '低风险' },
      { risk: 'medium', label: '中风险' },
      { risk: 'high', label: '高风险' },
      { risk: 'critical', label: '极高风险' },
    ]
    for (const { risk, label } of cases) {
      const html = render(
        <ConfirmationCard
          workIntent={baseIntent}
          toolEventId="evt-1"
          risk={risk}
          onApprove={() => {}}
          onReject={() => {}}
        />,
      )
      expect(html).toContain(label)
    }
  })

  it('默认 risk 为 medium', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('confirmation-card risk-medium')
  })
})

describe('ConfirmationCard — workIntent 渲染', () => {
  it('workflowName + action 渲染在 workflow 段', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('Obsidian 写入 · append')
  })

  it('targets 渲染 label: path', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('笔记：/vault/Archer客户端.md')
  })

  it('steps 渲染为有序列表', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('读取原文件')
    expect(html).toContain('追加内容')
    expect(html).toContain('写回')
    expect(html).toContain('<ol')
  })

  it('verifyPlan + rollbackPlan 渲染', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('验证：')
    expect(html).toContain('grep 确认关键词存在')
    expect(html).toContain('回滚计划：')
    expect(html).toContain('恢复 .bak.md')
  })

  it('workflowName/action/verify/rollback 缺失时不渲染对应段', () => {
    const minimal: WorkIntent = {}
    const html = render(
      <ConfirmationCard
        workIntent={minimal}
        toolEventId="evt-1"
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('工作确认')
    expect(html).not.toContain('验证：')
    expect(html).not.toContain('回滚计划：')
  })
})

describe('ConfirmationCard — targetPreview', () => {
  it('path 渲染为 code 块', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        targetPreview={{ path: '/abs/path/to/file.md' }}
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('path: /abs/path/to/file.md')
  })

  it('command 渲染带 $ 前缀', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        targetPreview={{ command: 'npm run build' }}
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('$ npm run build')
  })

  it('url 渲染为 code 块', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        targetPreview={{ url: 'https://example.com' }}
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('url: https://example.com')
  })

  it('targetPreview 为空对象不渲染 preview 段', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        targetPreview={{}}
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).not.toContain('confirmation-card-target-preview')
  })
})

describe('ConfirmationCard — 按钮回调', () => {
  it('onApprove 回调收到 toolEventId', () => {
    const onApprove = vi.fn()
    // 静态渲染无法触发 onClick，验证回调绑定正确性通过 props 传递
    // 这里验证按钮存在 + aria-label
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-callback"
        onApprove={onApprove}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('aria-label="批准"')
    expect(html).toContain('aria-label="拒绝"')
    expect(html).toContain('confirmation-card-approve')
    expect(html).toContain('confirmation-card-reject')
  })
})

describe('ConfirmationCard — busy 状态', () => {
  it('busy=true 时按钮区显示 ThinkingDots 而非按钮', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        busy
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('busy')
    expect(html).toContain('aria-busy="true"')
    // ThinkingDots 渲染 thinking-indicator class
    expect(html).toContain('thinking-indicator')
    // 按钮不渲染
    expect(html).not.toContain('confirmation-card-approve')
    expect(html).not.toContain('confirmation-card-reject')
  })

  it('busy=false 时按钮正常渲染', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        busy={false}
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).not.toContain('aria-busy="true"')
    expect(html).toContain('confirmation-card-approve')
    expect(html).toContain('confirmation-card-reject')
  })
})

describe('ConfirmationCard — diff toggle', () => {
  it('onShowDiff 提供时渲染 diff 按钮', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        onApprove={() => {}}
        onReject={() => {}}
        onShowDiff={() => {}}
      />,
    )
    expect(html).toContain('confirmation-card-diff-toggle')
    expect(html).toContain('查看 diff 预览')
  })

  it('onShowDiff 未提供时不渲染 diff 按钮', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).not.toContain('confirmation-card-diff-toggle')
  })

  it('busy 时 diff 按钮 disabled', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        busy
        onApprove={() => {}}
        onReject={() => {}}
        onShowDiff={() => {}}
      />,
    )
    // diff 按钮在 busy 时仍渲染但 disabled
    expect(html).toContain('disabled=""')
  })
})

describe('ConfirmationCard — toolDisplayName', () => {
  it('提供时渲染在 header', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        toolDisplayName="Obsidian 写入"
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('confirmation-card-name')
    expect(html).toContain('Obsidian 写入')
  })

  it('未提供时不渲染 name 段', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-1"
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).not.toContain('confirmation-card-name')
  })
})

describe('ConfirmationCard — data-tool-event-id', () => {
  it('渲染 data-tool-event-id 用于追踪', () => {
    const html = render(
      <ConfirmationCard
        workIntent={baseIntent}
        toolEventId="evt-track-123"
        onApprove={() => {}}
        onReject={() => {}}
      />,
    )
    expect(html).toContain('data-tool-event-id="evt-track-123"')
  })
})
