import { describe, expect, it } from 'vitest'
import { pythonApprovalToAgentEvent, pythonOrchestrationToAgentEvent, pythonPlanToAgentEvent, pythonToolEventToAgentEvent } from '../pythonBridge'

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

  it('converts Python plan events to plan.event', () => {
    const event = pythonPlanToAgentEvent('session-1', {
      id: 'plan-1',
      title: '提炼内容并写入 Obsidian',
      status: 'proposed',
      detail: '先整理，再请求写入确认',
      steps: [
        { id: 1, action: 'read_source', tool: 'input_context', requiresApproval: false },
        { id: 2, action: 'write_obsidian', tool: 'obsidian_write', requiresApproval: true },
      ],
    })

    expect(event.type).toBe('plan.event')
    if (event.type === 'plan.event') {
      expect(event.steps[1].requiresApproval).toBe(true)
    }
  })

  it('converts Python orchestration snapshots to orchestration.event', () => {
    const event = pythonOrchestrationToAgentEvent('session-1', {
      id: 'orch-1',
      intent: 'project',
      subIntent: 'project_planning',
      mode: 'builder',
      depth: 'deep',
      labels: ['项目规划', '构建', '检索记忆'],
      needsMemory: true,
      needsJob: false,
    })

    expect(event.type).toBe('orchestration.event')
    if (event.type === 'orchestration.event') {
      expect(event.labels).toContain('项目规划')
    }
  })
})
