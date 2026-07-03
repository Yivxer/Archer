/**
 * L4.3 — <WorkReceipt /> 组件测试。
 *
 * 测试策略（与 ConfirmationCard.test.tsx 一致）：
 *   - 用 react-dom/server 静态渲染 + 字符串断言
 *   - 覆盖：左边色条、4 字段渲染、trace 按钮显隐、showTraceAction 开关、空字段处理
 */

import { describe, expect, it } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { WorkReceipt } from '../WorkReceipt'
import type { WorkReceipt as WorkReceiptType } from '../../types'

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
}

const fullReceipt: WorkReceiptType = {
  done: '已写入 Archer客户端.md',
  source: '/vault/Archer客户端.md',
  target: '/vault/Archer客户端.md（追加）',
  verification: 'grep 确认关键词存在',
  rollback: '恢复 .bak.md',
  traceId: 'trace-abc123',
}

describe('WorkReceipt — L4.3 基础渲染', () => {
  it('渲染 work-receipt 容器 + 左边色条', () => {
    const html = render(<WorkReceipt receipt={fullReceipt} />)
    expect(html).toContain('class="work-receipt"')
    expect(html).toContain('work-receipt-stripe')
  })

  it('done 字段渲染为标题', () => {
    const html = render(<WorkReceipt receipt={fullReceipt} />)
    expect(html).toContain('已写入 Archer客户端.md')
    expect(html).toContain('work-receipt-done')
  })

  it('aria-label 为「工作回执」', () => {
    const html = render(<WorkReceipt receipt={fullReceipt} />)
    expect(html).toContain('aria-label="工作回执"')
  })
})

describe('WorkReceipt — 4 字段渲染', () => {
  it('source/target/verification/rollback 全部渲染', () => {
    const html = render(<WorkReceipt receipt={fullReceipt} />)
    expect(html).toContain('来源')
    expect(html).toContain('/vault/Archer客户端.md')
    expect(html).toContain('目标')
    expect(html).toContain('/vault/Archer客户端.md（追加）')
    expect(html).toContain('验证')
    expect(html).toContain('grep 确认关键词存在')
    expect(html).toContain('回滚')
    expect(html).toContain('恢复 .bak.md')
  })

  it('source 缺失时不渲染 source 字段', () => {
    const html = render(<WorkReceipt receipt={{ ...fullReceipt, source: '' }} />)
    expect(html).not.toContain('>来源<')
  })

  it('target 缺失时不渲染 target 字段', () => {
    const html = render(<WorkReceipt receipt={{ ...fullReceipt, target: '' }} />)
    expect(html).not.toContain('>目标<')
  })

  it('verification 缺失时不渲染 verification 字段', () => {
    const html = render(<WorkReceipt receipt={{ ...fullReceipt, verification: '' }} />)
    expect(html).not.toContain('>验证<')
  })

  it('rollback 缺失时不渲染 rollback 字段', () => {
    const html = render(<WorkReceipt receipt={{ ...fullReceipt, rollback: '' }} />)
    expect(html).not.toContain('>回滚<')
  })

  it('只有 done 时不渲染任何字段（grid 为空）', () => {
    const html = render(
      <WorkReceipt
        receipt={{
          done: '操作完成',
          source: '',
          target: '',
          verification: '',
          rollback: '',
        }}
      />,
    )
    expect(html).toContain('操作完成')
    // grid 容器存在但为空（无 work-receipt-field）
    expect(html).not.toContain('work-receipt-field')
  })
})

describe('WorkReceipt — trace 按钮', () => {
  it('traceId + onViewTrace 提供时渲染 trace 按钮', () => {
    const html = render(
      <WorkReceipt
        receipt={fullReceipt}
        traceId="trace-abc123"
        onViewTrace={() => {}}
      />,
    )
    expect(html).toContain('work-receipt-trace-button')
    expect(html).toContain('aria-label="查看 trace"')
  })

  it('traceId 缺失时不渲染 trace 按钮', () => {
    const html = render(
      <WorkReceipt
        receipt={fullReceipt}
        onViewTrace={() => {}}
      />,
    )
    expect(html).not.toContain('work-receipt-trace-button')
  })

  it('onViewTrace 缺失时不渲染 trace 按钮', () => {
    const html = render(
      <WorkReceipt
        receipt={fullReceipt}
        traceId="trace-abc123"
      />,
    )
    expect(html).not.toContain('work-receipt-trace-button')
  })

  it('showTraceAction=false 时不渲染 trace 按钮', () => {
    const html = render(
      <WorkReceipt
        receipt={fullReceipt}
        traceId="trace-abc123"
        showTraceAction={false}
        onViewTrace={() => {}}
      />,
    )
    expect(html).not.toContain('work-receipt-trace-button')
  })

  it('showTraceAction 默认为 true', () => {
    const htmlWithDefault = render(
      <WorkReceipt receipt={fullReceipt} traceId="trace-abc123" onViewTrace={() => {}} />,
    )
    const htmlWithExplicit = render(
      <WorkReceipt receipt={fullReceipt} traceId="trace-abc123" showTraceAction={true} onViewTrace={() => {}} />,
    )
    expect(htmlWithDefault).toContain('work-receipt-trace-button')
    expect(htmlWithExplicit).toContain('work-receipt-trace-button')
  })
})

describe('WorkReceipt — data-trace-id', () => {
  it('traceId 提供时渲染 data-trace-id', () => {
    const html = render(
      <WorkReceipt receipt={fullReceipt} traceId="trace-xyz" onViewTrace={() => {}} />,
    )
    expect(html).toContain('data-trace-id="trace-xyz"')
  })

  it('traceId 缺失时不渲染 data-trace-id', () => {
    const html = render(<WorkReceipt receipt={fullReceipt} />)
    expect(html).not.toContain('data-trace-id')
  })
})
