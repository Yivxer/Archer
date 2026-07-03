/**
 * L4.4 — <TracePanel /> 组件测试。
 *
 * 测试策略：
 *   - 用 react-dom/server 静态渲染 + 字符串断言
 *   - 覆盖：traceId、empty、runtime context、failure hint（展开/折叠）、
 *     keyword badge 着色、onRetry 按钮、recent events、defaultExpandFailure 开关
 */

import { describe, expect, it } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { TracePanel } from '../TracePanel'
import type { TraceDiagnostics } from '../../../../agent'
import type { AgentEvent, FailureHintEvent, RuntimeContextEvent } from '../../../../agent/contracts'

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
}

// ── fixtures ────────────────────────────────────────────────

const runtimeContext: RuntimeContextEvent = {
  id: 'evt-rt-1',
  sessionId: 'sess-1',
  createdAt: '2026-07-03T10:00:00Z',
  traceId: 'trace-abc',
  type: 'runtime.context',
  task: '写入 Obsidian 笔记',
  phase: 'awaiting_approval',
  userIntent: '记录今日学习',
  lastResult: '已读取原文件',
  expectedNext: '用户审批',
  matchedSkills: ['obsidian_write'],
}

const failureHint: FailureHintEvent = {
  id: 'evt-fh-1',
  sessionId: 'sess-1',
  createdAt: '2026-07-03T10:00:01Z',
  traceId: 'trace-abc',
  type: 'failure.hint',
  keyword: 'command_timeout',
  stage: 'shell_exec',
  recoverable: true,
  detail: '命令在 30s 内无响应',
}

const failureHintUnrecoverable: FailureHintEvent = {
  ...failureHint,
  id: 'evt-fh-2',
  keyword: 'write_permission',
  stage: 'vault_write',
  recoverable: false,
  detail: 'Obsidian vault 路径无写权限',
}

const toolResultEvent: AgentEvent = {
  id: 'evt-tr-1',
  sessionId: 'sess-1',
  createdAt: '2026-07-03T10:00:02Z',
  traceId: 'trace-abc',
  type: 'tool.result',
  requestId: 'req-1',
  toolName: 'obsidian_write',
  status: 'complete',
  ok: true,
  output: '已写入',
  message: 'success',
} as AgentEvent

function buildDiagnostics(overrides: Partial<TraceDiagnostics> = {}): TraceDiagnostics {
  return {
    traceId: 'trace-abc',
    empty: false,
    runtimeContext,
    failureHint,
    recentEvents: [toolResultEvent],
    ...overrides,
  }
}

// ────────────────────────────────────────────────────────────

describe('TracePanel — L4.4 基础渲染', () => {
  it('渲染 trace-panel 容器 + aria-label', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('class="trace-panel"')
    expect(html).toContain('aria-label="诊断面板"')
  })

  it('traceId 渲染在 header', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('trace-abc')
    expect(html).toContain('trace-panel-trace-id')
  })

  it('traceId 缺失时显示「暂无 traceId」', () => {
    const html = render(
      <TracePanel diagnostics={buildDiagnostics({ traceId: '' })} onClose={() => {}} />,
    )
    expect(html).toContain('暂无 traceId')
  })

  it('data-trace-id 注入到根元素', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('data-trace-id="trace-abc"')
  })

  it('渲染关闭按钮 + aria-label="关闭"', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('trace-panel-close')
    expect(html).toContain('aria-label="关闭"')
  })
})

describe('TracePanel — empty 状态', () => {
  it('empty=true 时显示「暂无诊断事件」', () => {
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ empty: true, recentEvents: [], runtimeContext: undefined, failureHint: undefined })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('trace-empty')
    expect(html).toContain('暂无诊断事件')
  })

  it('empty=true 时不渲染 trace-kv / failure / events', () => {
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ empty: true, recentEvents: [], runtimeContext: undefined, failureHint: undefined })}
        onClose={() => {}}
      />,
    )
    expect(html).not.toContain('trace-kv')
    expect(html).not.toContain('trace-failure-section')
    expect(html).not.toContain('trace-events')
  })
})

describe('TracePanel — runtime context 字段', () => {
  it('渲染任务/阶段/下一步/故障 4 字段', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('任务')
    expect(html).toContain('写入 Obsidian 笔记')
    expect(html).toContain('阶段')
    expect(html).toContain('awaiting_approval')
    expect(html).toContain('下一步')
    expect(html).toContain('用户审批')
    expect(html).toContain('故障')
  })

  it('runtimeContext 缺失时显示「未知」/「未记录」', () => {
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ runtimeContext: undefined })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('未知')
    expect(html).toContain('未记录')
  })

  it('failure 缺失时故障字段显示「无」', () => {
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ failureHint: undefined })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('无')
  })

  it('failure recoverable=true 时显示「可恢复」', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('command_timeout')
    expect(html).toContain('可恢复')
  })

  it('failure recoverable=false 时显示「不可恢复」', () => {
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ failureHint: failureHintUnrecoverable })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('write_permission')
    expect(html).toContain('不可恢复')
  })
})

describe('TracePanel — failure hint 折叠区', () => {
  it('failure 存在时渲染 trace-failure-section', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('trace-failure-section')
  })

  it('failure 缺失时不渲染 trace-failure-section', () => {
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ failureHint: undefined })}
        onClose={() => {}}
      />,
    )
    expect(html).not.toContain('trace-failure-section')
  })

  it('defaultExpandFailure 默认 true → failure 展开（detail 可见）', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain('命令在 30s 内无响应')
  })

  it('defaultExpandFailure=false → failure 折叠（detail 不可见）', () => {
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics()}
        defaultExpandFailure={false}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('aria-expanded="false"')
    expect(html).not.toContain('命令在 30s 内无响应')
  })

  it('渲染 keyword badge + stage', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('trace-keyword-badge')
    expect(html).toContain('command_timeout')
    expect(html).toContain('trace-failure-stage')
    expect(html).toContain('shell_exec')
  })
})

describe('TracePanel — keyword badge 着色', () => {
  it('command_timeout → warning 色', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('trace-keyword-warning')
  })

  it('write_permission → warning 色', () => {
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ failureHint: failureHintUnrecoverable })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('trace-keyword-warning')
  })

  it('provider_connection_failed → danger 色', () => {
    const danger: FailureHintEvent = {
      ...failureHint,
      keyword: 'provider_connection_failed',
    }
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ failureHint: danger })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('trace-keyword-danger')
  })

  it('runtime_failure → danger 色', () => {
    const danger: FailureHintEvent = {
      ...failureHint,
      keyword: 'runtime_failure',
    }
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ failureHint: danger })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('trace-keyword-danger')
  })

  it('model_empty_response → info 色', () => {
    const info: FailureHintEvent = {
      ...failureHint,
      keyword: 'model_empty_response',
    }
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ failureHint: info })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('trace-keyword-info')
  })

  it('未知 keyword 兜底 → danger 色', () => {
    const unknown: FailureHintEvent = {
      ...failureHint,
      keyword: 'some_unknown_keyword',
    }
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ failureHint: unknown })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('trace-keyword-danger')
  })
})

describe('TracePanel — onRetry 按钮', () => {
  it('recoverable=true + onRetry 提供 → 渲染重试按钮', () => {
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ failureHint })}
        onRetry={() => {}}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('trace-retry-button')
    expect(html).toContain('aria-label="重试"')
  })

  it('recoverable=false → 不渲染重试按钮', () => {
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ failureHint: failureHintUnrecoverable })}
        onRetry={() => {}}
        onClose={() => {}}
      />,
    )
    expect(html).not.toContain('trace-retry-button')
  })

  it('onRetry 缺失 → 不渲染重试按钮', () => {
    const html = render(
      <TracePanel diagnostics={buildDiagnostics({ failureHint })} onClose={() => {}} />,
    )
    expect(html).not.toContain('trace-retry-button')
  })

  it('failure 缺失 → 不渲染重试按钮', () => {
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ failureHint: undefined })}
        onRetry={() => {}}
        onClose={() => {}}
      />,
    )
    expect(html).not.toContain('trace-retry-button')
  })
})

describe('TracePanel — recent events 时间线', () => {
  it('渲染 trace-events 容器 + 事件行', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('trace-events')
    expect(html).toContain('trace-event-row')
  })

  it('渲染事件类型 + summary', () => {
    const html = render(<TracePanel diagnostics={buildDiagnostics()} onClose={() => {}} />)
    expect(html).toContain('tool.result')
    expect(html).toContain('obsidian_write / complete')
  })

  it('多事件按顺序渲染', () => {
    const events: AgentEvent[] = [
      runtimeContext,
      {
        id: 'evt-tr-2',
        sessionId: 'sess-1',
        createdAt: '2026-07-03T10:00:03Z',
        traceId: 'trace-abc',
        type: 'tool.request',
        toolName: 'obsidian_write',
        displayName: 'Obsidian 写入',
        risk: 'medium',
        permissionLevel: 'write-vault',
        status: 'waiting_approval',
        args: {},
        summary: '写入笔记',
        detail: '',
        requiresApproval: true,
        blocked: false,
      },
      toolResultEvent,
    ]
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ recentEvents: events })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('runtime.context')
    expect(html).toContain('写入 Obsidian 笔记 / awaiting_approval')
    expect(html).toContain('tool.request')
    expect(html).toContain('obsidian_write / waiting_approval / write-vault')
  })

  it('status.event 用 intentType/intentLabel 描述', () => {
    const statusEvent: AgentEvent = {
      id: 'evt-se-1',
      sessionId: 'sess-1',
      createdAt: '2026-07-03T10:00:04Z',
      traceId: 'trace-abc',
      type: 'status.event',
      intentType: 'learn',
      intentLabel: '学习',
      matchedSkills: [],
      isBackground: false,
      memoryScope: [],
    } as AgentEvent
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ recentEvents: [statusEvent] })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('status.event')
    expect(html).toContain('learn / 学习')
  })

  it('未知事件类型 fallback 到 type 本身', () => {
    const unknownEvent = {
      id: 'evt-unk-1',
      sessionId: 'sess-1',
      createdAt: '2026-07-03T10:00:05Z',
      traceId: 'trace-abc',
      type: 'text.delta',
      text: 'hello',
    } as unknown as AgentEvent
    const html = render(
      <TracePanel
        diagnostics={buildDiagnostics({ recentEvents: [unknownEvent] })}
        onClose={() => {}}
      />,
    )
    expect(html).toContain('text.delta')
  })
})
