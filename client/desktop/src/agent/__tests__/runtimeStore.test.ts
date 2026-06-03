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
})
