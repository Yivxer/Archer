/**
 * L4.5 — <ErrorRecovery /> 组件测试。
 *
 * 测试策略：
 *   - 用 react-dom/server 静态渲染 + 字符串断言
 *   - 覆盖：色条色调分类、默认文案、detail 覆盖、recoverable 推导与覆盖、
 *     onRetry 按钮显隐、onViewTrace 按钮显隐、data-* 属性
 */

import { describe, expect, it } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { ErrorRecovery } from '../ErrorRecovery'
import type { FailureType } from '../../lib/chatEventDispatcher'

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
}

// ── 色条色调分类 ────────────────────────────────────────────

describe('ErrorRecovery — L4.5 色条色调分类', () => {
  const amberTypes: FailureType[] = [
    'provider_connection_failed',
    'command_timeout',
    'model_stream_timeout',
    'dependency_missing',
    'syntax_mismatch',
  ]
  const orangeTypes: FailureType[] = [
    'write_permission',
    'tool_failed',
    'approval_rejected',
    'job_stale_cancelled',
  ]
  const blueTypes: FailureType[] = [
    'model_empty_response',
    'tool_executed_no_summary',
    'chat_busy',
    'context_trimmed',
    'approval_duplicated',
  ]
  const redTypes: FailureType[] = ['runtime_failure', 'unknown_failure']

  for (const ft of amberTypes) {
    it(`${ft} → amber 色条`, () => {
      const html = render(<ErrorRecovery failureType={ft} />)
      expect(html).toContain('error-recovery-tone-amber')
    })
  }

  for (const ft of orangeTypes) {
    it(`${ft} → orange 色条`, () => {
      const html = render(<ErrorRecovery failureType={ft} />)
      expect(html).toContain('error-recovery-tone-orange')
    })
  }

  for (const ft of blueTypes) {
    it(`${ft} → blue 色条`, () => {
      const html = render(<ErrorRecovery failureType={ft} />)
      expect(html).toContain('error-recovery-tone-blue')
    })
  }

  for (const ft of redTypes) {
    it(`${ft} → red 色条`, () => {
      const html = render(<ErrorRecovery failureType={ft} />)
      expect(html).toContain('error-recovery-tone-red')
    })
  }
})

// ── 默认文案 ────────────────────────────────────────────────

describe('ErrorRecovery — 默认文案', () => {
  it('model_empty_response 默认文案', () => {
    const html = render(<ErrorRecovery failureType="model_empty_response" />)
    expect(html).toContain('模型没有回复，可以重试一次')
  })

  it('tool_executed_no_summary 默认文案', () => {
    const html = render(<ErrorRecovery failureType="tool_executed_no_summary" />)
    expect(html).toContain('已执行操作，详见上方卡片')
  })

  it('provider_connection_failed 默认文案', () => {
    const html = render(<ErrorRecovery failureType="provider_connection_failed" />)
    expect(html).toContain('模型服务连接失败')
  })

  it('runtime_failure 默认文案', () => {
    const html = render(<ErrorRecovery failureType="runtime_failure" />)
    expect(html).toContain('运行时异常，请查看诊断')
  })

  it('unknown_failure 默认文案', () => {
    const html = render(<ErrorRecovery failureType="unknown_failure" />)
    expect(html).toContain('发生未知错误，请查看诊断')
  })
})

// ── detail 覆盖 ────────────────────────────────────────────

describe('ErrorRecovery — detail 覆盖默认文案', () => {
  it('detail 提供时覆盖默认文案', () => {
    const html = render(
      <ErrorRecovery failureType="runtime_failure" detail="自定义错误说明" />,
    )
    expect(html).toContain('自定义错误说明')
    expect(html).not.toContain('运行时异常，请查看诊断')
  })

  it('detail 为空字符串时回退到默认文案', () => {
    const html = render(
      <ErrorRecovery failureType="runtime_failure" detail="" />,
    )
    expect(html).toContain('运行时异常，请查看诊断')
  })
})

// ── recoverable 推导 ───────────────────────────────────────

describe('ErrorRecovery — recoverable 推导', () => {
  it('model_empty_response 默认 recoverable=true（提供 onRetry 时显示按钮）', () => {
    const html = render(
      <ErrorRecovery failureType="model_empty_response" onRetry={() => {}} />,
    )
    expect(html).toContain('error-recovery-retry')
  })

  it('tool_executed_no_summary 默认 recoverable=false（不显示重试按钮）', () => {
    const html = render(
      <ErrorRecovery failureType="tool_executed_no_summary" onRetry={() => {}} />,
    )
    expect(html).not.toContain('error-recovery-retry')
  })

  it('approval_rejected 默认 recoverable=false', () => {
    const html = render(
      <ErrorRecovery failureType="approval_rejected" onRetry={() => {}} />,
    )
    expect(html).not.toContain('error-recovery-retry')
  })

  it('显式 recoverable=true 覆盖默认 false', () => {
    const html = render(
      <ErrorRecovery
        failureType="approval_rejected"
        recoverable={true}
        onRetry={() => {}}
      />,
    )
    expect(html).toContain('error-recovery-retry')
  })

  it('显式 recoverable=false 覆盖默认 true', () => {
    const html = render(
      <ErrorRecovery
        failureType="model_empty_response"
        recoverable={false}
        onRetry={() => {}}
      />,
    )
    expect(html).not.toContain('error-recovery-retry')
  })
})

// ── onRetry 按钮显隐 ───────────────────────────────────────

describe('ErrorRecovery — onRetry 按钮', () => {
  it('recoverable=true + onRetry 提供 → 渲染重试按钮 + aria-label', () => {
    const html = render(
      <ErrorRecovery failureType="model_empty_response" onRetry={() => {}} />,
    )
    expect(html).toContain('error-recovery-retry')
    expect(html).toContain('aria-label="重试"')
    expect(html).toContain('>重试<')
  })

  it('recoverable=true 但 onRetry 缺失 → 不渲染重试按钮', () => {
    const html = render(
      <ErrorRecovery failureType="model_empty_response" />,
    )
    expect(html).not.toContain('error-recovery-retry')
  })
})

// ── onViewTrace 按钮显隐 ───────────────────────────────────

describe('ErrorRecovery — onViewTrace 按钮', () => {
  it('traceId + onViewTrace 提供 → 渲染诊断按钮', () => {
    const html = render(
      <ErrorRecovery
        failureType="runtime_failure"
        traceId="trace-xyz"
        onViewTrace={() => {}}
      />,
    )
    expect(html).toContain('error-recovery-trace')
    expect(html).toContain('aria-label="查看诊断"')
  })

  it('traceId 缺失 → 不渲染诊断按钮', () => {
    const html = render(
      <ErrorRecovery
        failureType="runtime_failure"
        onViewTrace={() => {}}
      />,
    )
    expect(html).not.toContain('error-recovery-trace')
  })

  it('onViewTrace 缺失 → 不渲染诊断按钮', () => {
    const html = render(
      <ErrorRecovery failureType="runtime_failure" traceId="trace-xyz" />,
    )
    expect(html).not.toContain('error-recovery-trace')
  })
})

// ── data-* 属性 ────────────────────────────────────────────

describe('ErrorRecovery — data-* 属性', () => {
  it('data-failure-type 注入', () => {
    const html = render(<ErrorRecovery failureType="command_timeout" />)
    expect(html).toContain('data-failure-type="command_timeout"')
  })

  it('data-trace-id 在 traceId 提供时注入', () => {
    const html = render(
      <ErrorRecovery failureType="runtime_failure" traceId="trace-abc" />,
    )
    expect(html).toContain('data-trace-id="trace-abc"')
  })

  it('data-trace-id 在 traceId 缺失时不注入', () => {
    const html = render(<ErrorRecovery failureType="runtime_failure" />)
    expect(html).not.toContain('data-trace-id')
  })
})

// ── 容器基础 ────────────────────────────────────────────────

describe('ErrorRecovery — 基础渲染', () => {
  it('渲染 error-recovery 容器 + aria-label', () => {
    const html = render(<ErrorRecovery failureType="unknown_failure" />)
    expect(html).toContain('class="error-recovery')
    expect(html).toContain('aria-label="错误恢复"')
  })

  it('渲染左边色条', () => {
    const html = render(<ErrorRecovery failureType="unknown_failure" />)
    expect(html).toContain('error-recovery-stripe')
  })

  it('无 onRetry 且无 onViewTrace 时不渲染 actions 区', () => {
    const html = render(<ErrorRecovery failureType="unknown_failure" />)
    expect(html).not.toContain('error-recovery-actions')
  })
})
