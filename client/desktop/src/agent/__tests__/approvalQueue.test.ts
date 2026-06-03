import { describe, expect, it } from 'vitest'
import { createApprovalQueue } from '../approvalQueue'
import type { ToolRequestEvent } from '../contracts'

function request(id = 'tool-1'): ToolRequestEvent {
  return {
    type: 'tool.request',
    id,
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
}

describe('approval queue', () => {
  it('adds waiting tool requests', () => {
    const queue = createApprovalQueue()
    queue.add(request())
    expect(queue.pending()).toHaveLength(1)
  })

  it('records approved decisions once', () => {
    const queue = createApprovalQueue()
    queue.add(request())
    expect(queue.decide('tool-1', 'approved')).toEqual({ ok: true })
    expect(queue.decide('tool-1', 'denied')).toEqual({ ok: false, reason: 'already_decided' })
  })

  it('removes completed approvals from pending list', () => {
    const queue = createApprovalQueue()
    queue.add(request())
    queue.decide('tool-1', 'approved')
    expect(queue.pending()).toHaveLength(0)
    expect(queue.decisionFor('tool-1')).toBe('approved')
  })
})
