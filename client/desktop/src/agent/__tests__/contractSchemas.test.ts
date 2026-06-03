import { describe, expect, it } from 'vitest'
import { agentEventSchema, parseAgentEvent } from '../contractSchemas'

describe('contract schemas', () => {
  it('accepts a valid tool request event', () => {
    const parsed = parseAgentEvent({
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
    })
    expect(parsed.type).toBe('tool.request')
  })

  it('rejects unknown event types', () => {
    const result = agentEventSchema.safeParse({
      type: 'tool_event',
      id: 'bad',
    })
    expect(result.success).toBe(false)
  })

  it('rejects malformed approval results', () => {
    const result = agentEventSchema.safeParse({
      type: 'approval.result',
      id: 'approval-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      requestId: 'tool-1',
      decision: 'maybe',
      executed: true,
      ok: true,
      output: '',
      message: '',
    })
    expect(result.success).toBe(false)
  })

  it('accepts a valid job event', () => {
    const parsed = parseAgentEvent({
      type: 'job.event',
      id: 'job-1-running',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      jobId: 'job-1',
      title: '后台分析',
      status: 'running',
      detail: '后台执行中',
    })

    expect(parsed.type).toBe('job.event')
  })
})
