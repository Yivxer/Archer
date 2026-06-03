import { describe, expect, it } from 'vitest'
import { pythonApprovalToAgentEvent, pythonToolEventToAgentEvent } from '../pythonBridge'

describe('python bridge', () => {
  it('converts Python toolEvent to a tool.request event', () => {
    const event = pythonToolEventToAgentEvent('session-1', {
      id: 'hugo-blog-1',
      name: 'hugo_blog',
      status: 'waiting',
      risk: 'low',
      summary: '确认部署枫弋札记',
      detail: 'action: deploy',
      requiresApproval: true,
      draft: {
        skillName: 'hugo_blog',
        displayName: 'hugo_blog',
        args: { action: 'deploy' },
        blocked: false,
      },
    })
    expect(event.type).toBe('tool.request')
    if (event.type === 'tool.request') {
      expect(event.status).toBe('waiting_approval')
      expect(event.args).toEqual({ action: 'deploy' })
    }
  })

  it('converts approval response to approval.result event', () => {
    const event = pythonApprovalToAgentEvent('session-1', {
      ok: true,
      eventId: 'hugo-blog-1',
      decision: 'approved',
      executed: true,
      output: '部署成功',
      message: 'hugo deploy 已自动执行',
    })
    expect(event.type).toBe('approval.result')
    if (event.type === 'approval.result') {
      expect(event.executed).toBe(true)
    }
  })
})
