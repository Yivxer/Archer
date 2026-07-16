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
      permissionLevel: 'deploy-remote',
      status: 'waiting_approval',
      args: { action: 'deploy' },
      summary: '确认部署枫弋札记',
      detail: 'action: deploy',
      requiresApproval: true,
      blocked: false,
    })
    expect(parsed.type).toBe('tool.request')
    if (parsed.type === 'tool.request') {
      expect(parsed.permissionLevel).toBe('deploy-remote')
    }
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

  it('accepts approval results with work receipt', () => {
    const parsed = parseAgentEvent({
      type: 'approval.result',
      id: 'approval-1',
      sessionId: 'session-1',
      createdAt: '2026-06-30T10:00:00.000Z',
      requestId: 'tool-1',
      decision: 'approved',
      permissionLevel: 'deploy-remote',
      executed: true,
      ok: true,
      output: '部署成功',
      message: '已发布',
      receipt: {
        done: '已发布《Test》到枫弋札记',
        source: '/tmp/source.md',
        target: 'https://iver.yivxer.com/posts/test/',
        verification: 'HTTP 200',
        rollback: 'content/posts/test.md',
        traceId: 'trace-1',
      },
    })

    expect(parsed.type).toBe('approval.result')
    if (parsed.type === 'approval.result') {
      expect(parsed.receipt?.verification).toBe('HTTP 200')
    }
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

  it('accepts a valid plan event', () => {
    const parsed = parseAgentEvent({
      type: 'plan.event',
      id: 'plan-1',
      sessionId: 'session-1',
      createdAt: '2026-06-11T10:00:00.000Z',
      title: '提炼内容并写入 Obsidian',
      status: 'proposed',
      detail: '先整理，再请求写入确认',
      steps: [
        { id: 1, action: 'read_source', tool: 'input_context', requiresApproval: false },
        { id: 2, action: 'write_obsidian', tool: 'obsidian_write', requiresApproval: true },
      ],
    })

    expect(parsed.type).toBe('plan.event')
  })

  it('accepts a valid orchestration event', () => {
    const parsed = parseAgentEvent({
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
        mode: 'foreground',
        reason: 'interactive turn stays in foreground',
        title: '项目规划',
        timeoutSeconds: 300,
      },
    })

    expect(parsed.type).toBe('orchestration.event')
    if (parsed.type === 'orchestration.event') {
      expect(parsed.taskRoute.mode).toBe('foreground')
    }
  })

  it('accepts status, runtime context, and failure hint events', () => {
    expect(parseAgentEvent({
      type: 'status.event',
      id: 'status-1',
      sessionId: 'session-1',
      createdAt: '2026-06-28T10:00:00.000Z',
      intentType: 'writing',
      intentLabel: '写作协助',
      matchedSkills: ['hugo_blog'],
      isBackground: false,
      memoryScope: ['project'],
    }).type).toBe('status.event')

    expect(parseAgentEvent({
      type: 'runtime.context',
      id: 'ctx-1',
      sessionId: 'session-1',
      createdAt: '2026-06-28T10:00:01.000Z',
      task: 'blog_publish',
      phase: 'route',
      userIntent: 'deploy_existing_post',
      lastResult: '',
      expectedNext: 'select_workflow_or_model',
      matchedSkills: ['hugo_blog'],
      provider: 'Kimi',
      model: 'kimi-k2-fast',
      baseUrlSummary: 'https://api.moonshot.cn',
      outcome: 'complete',
      ttftMs: 80,
      totalDurationMs: 200,
      contextBuildMs: 30,
      toolDurationMs: 40,
      cpuTimeMs: 10,
      peakRssBytes: 123456,
    }).type).toBe('runtime.context')

    expect(parseAgentEvent({
      type: 'failure.hint',
      id: 'failure-1',
      sessionId: 'session-1',
      createdAt: '2026-06-28T10:00:02.000Z',
      keyword: 'command_timeout',
      stage: 'model_stream',
      recoverable: true,
      detail: 'connect timeout',
    }).type).toBe('failure.hint')
  })
})
