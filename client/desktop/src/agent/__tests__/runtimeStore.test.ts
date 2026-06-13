import { describe, expect, it } from 'vitest'
import type { AgentEvent } from '../contracts'
import { createInitialRuntimeState, reduceRuntimeEvent } from '../runtimeStore'

describe('runtime store reducer', () => {
  it('appends assistant text deltas', () => {
    const state = createInitialRuntimeState('session-1')
    const event: AgentEvent = {
      type: 'text.delta',
      id: 'text-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      text: '你好',
    }
    const next = reduceRuntimeEvent(state, event)
    expect(next.streamingText).toBe('你好')
  })

  it('marks session as waiting when approval is required', () => {
    const state = createInitialRuntimeState('session-1')
    const next = reduceRuntimeEvent(state, {
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
      detail: '',
      requiresApproval: true,
      blocked: false,
    })
    expect(next.status).toBe('waiting_approval')
    expect(next.pendingApprovals).toHaveLength(1)
  })

  it('removes pending approval after approval result', () => {
    const state = reduceRuntimeEvent(createInitialRuntimeState('session-1'), {
      type: 'tool.request',
      id: 'tool-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      toolName: 'hugo_blog',
      displayName: 'hugo_blog',
      risk: 'low',
      status: 'waiting_approval',
      args: {},
      summary: '',
      detail: '',
      requiresApproval: true,
      blocked: false,
    })
    const next = reduceRuntimeEvent(state, {
      type: 'approval.result',
      id: 'approval-tool-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:01:00.000Z',
      requestId: 'tool-1',
      decision: 'approved',
      executed: true,
      ok: true,
      output: 'ok',
      message: 'done',
    })
    expect(next.pendingApprovals).toHaveLength(0)
    expect(next.toolResults['tool-1']?.message).toBe('done')
  })

  it('tracks job events and returns to idle after completion', () => {
    const running = reduceRuntimeEvent(createInitialRuntimeState('session-1'), {
      type: 'job.event',
      id: 'job-1-running',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      jobId: 'job-1',
      title: '后台分析',
      status: 'running',
      detail: '后台执行中',
    })
    const complete = reduceRuntimeEvent(running, {
      type: 'job.event',
      id: 'job-1-complete',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:01:00.000Z',
      jobId: 'job-1',
      title: '后台分析',
      status: 'complete',
      detail: '完成',
    })

    expect(running.status).toBe('running_job')
    expect(complete.status).toBe('idle')
    expect(complete.jobs['job-1']?.status).toBe('complete')
  })

  it('tracks proposed plan events without changing active status', () => {
    const state = createInitialRuntimeState('session-1')
    const next = reduceRuntimeEvent(state, {
      type: 'plan.event',
      id: 'plan-1',
      sessionId: 'session-1',
      createdAt: '2026-06-11T10:00:00.000Z',
      title: '提炼内容并写入 Obsidian',
      status: 'proposed',
      detail: '先整理，再请求写入确认',
      prompt: '帮我把这篇文章提炼成方法论，并写入 Obsidian',
      steps: [
        { id: 1, action: 'read_source', tool: 'input_context', requiresApproval: false },
        { id: 2, action: 'write_obsidian', tool: 'obsidian_write', requiresApproval: true },
      ],
    })

    expect(next.status).toBe('idle')
    expect(next.plans['plan-1']?.steps).toHaveLength(2)

    const accepted = reduceRuntimeEvent(next, {
      ...next.plans['plan-1'],
      status: 'accepted',
      createdAt: '2026-06-11T10:01:00.000Z',
    })
    expect(accepted.plans['plan-1']?.status).toBe('accepted')
  })

  it('tracks orchestration events for status chips', () => {
    const state = createInitialRuntimeState('session-1')
    const next = reduceRuntimeEvent(state, {
      type: 'orchestration.event',
      id: 'orch-1',
      sessionId: 'session-1',
      createdAt: '2026-06-11T10:00:00.000Z',
      intent: 'project',
      subIntent: 'project_planning',
      mode: 'builder',
      depth: 'deep',
      labels: ['项目规划', '构建'],
      needsMemory: true,
      needsJob: false,
    })

    expect(next.status).toBe('idle')
    expect(next.orchestrations['orch-1']?.labels).toContain('项目规划')
  })
})
