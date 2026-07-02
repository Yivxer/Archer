import { describe, expect, it } from 'vitest'
import type { AgentEvent } from '../contracts'
import { buildTraceDiagnostics } from '../traceDiagnostics'

const base = {
  sessionId: 's1',
  createdAt: '2026-06-30T10:00:00.000Z',
  traceId: 'trace-1',
}

describe('trace diagnostics', () => {
  it('groups runtime, tool, failure, and job events by trace id', () => {
    const events: AgentEvent[] = [
      {
        ...base,
        type: 'runtime.context',
        id: 'ctx-1',
        task: 'blog_publish',
        phase: 'deploy',
        userIntent: 'publish',
        lastResult: 'created',
        expectedNext: 'verify_url',
        matchedSkills: ['hugo_blog'],
      },
      {
        ...base,
        type: 'tool.request',
        id: 'tool-1',
        toolName: 'hugo_blog',
        displayName: 'hugo_blog',
        risk: 'medium',
        permissionLevel: 'deploy-remote',
        status: 'blocked',
        args: { action: 'deploy' },
        summary: '部署枫弋札记失败',
        detail: 'timeout',
        requiresApproval: false,
        blocked: true,
      },
      {
        ...base,
        type: 'failure.hint',
        id: 'failure-1',
        keyword: 'command_timeout',
        stage: 'hugo_workflow',
        recoverable: true,
        detail: 'deploy timed out',
      },
      {
        ...base,
        type: 'job.event',
        id: 'job-1',
        jobId: 'job-1',
        title: '后台部署',
        status: 'cancelled',
        detail: 'job stale',
        stale: true,
      },
    ]

    const diagnostics = buildTraceDiagnostics(events, 'trace-1')

    expect(diagnostics.empty).toBe(false)
    expect(diagnostics.traceId).toBe('trace-1')
    expect(diagnostics.runtimeContext?.task).toBe('blog_publish')
    expect(diagnostics.failureHint?.keyword).toBe('command_timeout')
    expect(diagnostics.recentEvents).toHaveLength(4)
    expect(diagnostics.recentEvents.map((event) => event.type)).toEqual([
      'runtime.context',
      'tool.request',
      'failure.hint',
      'job.event',
    ])
  })

  it('returns an empty diagnostic state when trace id has no events', () => {
    const diagnostics = buildTraceDiagnostics([], 'trace-missing')

    expect(diagnostics.empty).toBe(true)
    expect(diagnostics.traceId).toBe('trace-missing')
    expect(diagnostics.recentEvents).toEqual([])
  })
})
