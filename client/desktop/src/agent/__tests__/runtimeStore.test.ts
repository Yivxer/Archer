import { describe, expect, it } from 'vitest'
import type { AgentEvent } from '../contracts'
import { createInitialRuntimeState, reduceRuntimeEvent, restoreRuntimeStateFromEvents } from '../runtimeStore'

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
      taskRoute: {
        mode: 'background',
        reason: 'python orchestrator requires background job',
        title: '项目规划',
        timeoutSeconds: 300,
      },
    })

    expect(next.status).toBe('idle')
    expect(next.orchestrations['orch-1']?.labels).toContain('项目规划')
    expect(next.orchestrations['orch-1']?.taskRoute.mode).toBe('background')
  })

  it('tracks runtime context and failure hints without changing active status', () => {
    const withContext = reduceRuntimeEvent(createInitialRuntimeState('session-1'), {
      type: 'runtime.context',
      id: 'ctx-1',
      sessionId: 'session-1',
      createdAt: '2026-06-28T10:00:00.000Z',
      task: 'blog_publish',
      phase: 'execute',
      userIntent: 'deploy_existing_post',
      lastResult: 'hugo_file_created',
      expectedNext: 'build_and_deploy',
    })

    const withFailure = reduceRuntimeEvent(withContext, {
      type: 'failure.hint',
      id: 'failure-1',
      sessionId: 'session-1',
      createdAt: '2026-06-28T10:00:01.000Z',
      keyword: 'command_timeout',
      stage: 'deploy',
      recoverable: true,
      detail: 'deploy timed out',
    })

    expect(withContext.status).toBe('idle')
    expect(withContext.runtimeContext?.task).toBe('blog_publish')
    expect(withFailure.status).toBe('idle')
    expect(withFailure.failureHints['failure-1']?.keyword).toBe('command_timeout')
  })

  it('restores state from event replay for one session only', () => {
    const events: AgentEvent[] = [
      {
        type: 'job.event',
        id: 'job-other',
        sessionId: 'other-session',
        createdAt: '2026-06-02T10:00:00.000Z',
        jobId: 'job-other',
        title: '其他任务',
        status: 'running',
        detail: 'ignore',
      },
      {
        type: 'job.event',
        id: 'job-1-running',
        sessionId: 'session-1',
        createdAt: '2026-06-02T10:01:00.000Z',
        jobId: 'job-1',
        title: '后台分析',
        status: 'running',
        detail: '后台执行中',
      },
      {
        type: 'plan.event',
        id: 'plan-1',
        sessionId: 'session-1',
        createdAt: '2026-06-02T10:02:00.000Z',
        title: '执行计划',
        status: 'proposed',
        detail: '由事件恢复',
        steps: [],
      },
    ]

    const restored = restoreRuntimeStateFromEvents('session-1', events, {
      now: Date.parse('2026-06-02T10:05:00.000Z'),
    })

    expect(restored.status).toBe('running_job')
    expect(Object.keys(restored.jobs)).toEqual(['job-1'])
    expect(restored.plans['plan-1']?.detail).toBe('由事件恢复')
    expect(restored.events.map((event) => event.id)).toEqual(['job-1-running', 'plan-1'])
  })

  it('marks old active jobs stale during crash recovery restore', () => {
    const restored = restoreRuntimeStateFromEvents('session-1', [
      {
        type: 'job.event',
        id: 'job-old-running',
        sessionId: 'session-1',
        createdAt: '2026-06-02T10:00:00.000Z',
        jobId: 'job-old',
        title: '重启前任务',
        status: 'running',
        detail: '模型流处理中',
      },
    ], {
      now: Date.parse('2026-06-02T10:20:00.000Z'),
      activeJobStaleMs: 15 * 60 * 1000,
    })

    expect(restored.status).toBe('idle')
    expect(restored.jobs['job-old']?.status).toBe('cancelled')
    expect(restored.jobs['job-old']?.stale).toBe(true)
    expect(restored.jobs['job-old']?.detail).toContain('重启后检测到任务长时间无进展')
  })

  it('keeps recent active jobs running during restore', () => {
    const restored = restoreRuntimeStateFromEvents('session-1', [
      {
        type: 'job.event',
        id: 'job-recent-running',
        sessionId: 'session-1',
        createdAt: '2026-06-02T10:10:00.000Z',
        jobId: 'job-recent',
        title: '刚开始的任务',
        status: 'running',
        detail: '执行中',
      },
    ], {
      now: Date.parse('2026-06-02T10:20:00.000Z'),
      activeJobStaleMs: 15 * 60 * 1000,
    })

    expect(restored.status).toBe('running_job')
    expect(restored.jobs['job-recent']?.status).toBe('running')
    expect(restored.jobs['job-recent']?.stale).toBeUndefined()
  })
})
