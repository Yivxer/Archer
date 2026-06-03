import { describe, expect, it } from 'vitest'
import type { AgentEvent, ApprovalResultEvent, ToolRequestEvent } from '../contracts'

describe('agent contracts', () => {
  it('represents a tool request event with stable approval fields', () => {
    const event: ToolRequestEvent = {
      type: 'tool.request',
      id: 'tool-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      toolName: 'hugo_blog',
      displayName: 'hugo_blog',
      risk: 'low',
      status: 'waiting_approval',
      args: { action: 'deploy' },
      summary: '确认部署枫弋札记',
      detail: 'action: deploy',
      requiresApproval: true,
      blocked: false,
    }
    expect(event.type).toBe('tool.request')
    expect(event.requiresApproval).toBe(true)
  })

  it('represents approval results as events, not UI-only mutations', () => {
    const event: ApprovalResultEvent = {
      type: 'approval.result',
      id: 'approval-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:01:00.000Z',
      requestId: 'tool-1',
      decision: 'approved',
      executed: true,
      ok: true,
      output: '部署成功',
      message: 'hugo deploy 已自动执行',
    }
    expect(event.executed).toBe(true)
  })

  it('keeps every event discriminated by type', () => {
    const event: AgentEvent = {
      type: 'text.delta',
      id: 'text-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:02:00.000Z',
      text: '完成。',
    }
    expect(event.type).toBe('text.delta')
  })
})
