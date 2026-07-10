import { describe, expect, it } from 'vitest'
import contractFixture from '../__fixtures__/desktopStreamV1.json'
import { UnsupportedContractVersionError, pythonApprovalToAgentEvent, pythonOrchestrationToAgentEvent, pythonPlanToAgentEvent, pythonStreamPayloadToAgentEvents, pythonToolEventToAgentEvent, type PythonApprovalResult, type PythonStreamPayload } from '../pythonBridge'

describe('python bridge', () => {
  it('normalizes the shared Python/Desktop contract fixture in stable order', () => {
    const streamEvents = pythonStreamPayloadToAgentEvents(
      contractFixture.sessionId,
      contractFixture.payload as PythonStreamPayload,
    )
    const approvalEvent = pythonApprovalToAgentEvent(
      contractFixture.sessionId,
      contractFixture.approvalResponse as PythonApprovalResult,
    )
    const events = [...streamEvents, approvalEvent]

    expect(events.map((event) => event.type)).toEqual(contractFixture.expectedAgentEventTypes)
    expect(approvalEvent).toMatchObject({
      type: 'approval.result',
      permissionLevel: 'deploy-remote',
      traceId: 'trace-contract-1',
      receipt: contractFixture.approvalResponse.receipt,
    })
    expect(contractFixture.donePayload).toEqual({ contractVersion: 1, type: 'done', done: true })
  })

  it('rejects missing or unknown stream contract versions', () => {
    expect(() => pythonStreamPayloadToAgentEvents('session-1', {} as PythonStreamPayload))
      .toThrow(UnsupportedContractVersionError)
    expect(() => pythonStreamPayloadToAgentEvents(
      'session-1',
      { contractVersion: 2 } as PythonStreamPayload,
    )).toThrow('请升级 Archer')
  })

  it('converts Python toolEvent to a tool.request event', () => {
    const event = pythonToolEventToAgentEvent('session-1', {
      id: 'hugo-blog-1',
      name: 'hugo_blog',
      status: 'waiting',
      risk: 'low',
      permissionLevel: 'deploy-remote',
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
      expect(event.permissionLevel).toBe('deploy-remote')
    }
  })

  it('converts approval response to approval.result event', () => {
    const event = pythonApprovalToAgentEvent('session-1', {
      ok: true,
      eventId: 'hugo-blog-1',
      traceId: 'trace-approval-1',
      decision: 'approved',
      executed: true,
      output: '部署成功',
      message: 'hugo deploy 已自动执行',
      permissionLevel: 'deploy-remote',
      workReceipt: {
        done: '已发布《Test》到枫弋札记',
        source: '/tmp/source.md',
        target: 'https://iver.yivxer.com/posts/test/',
        verification: 'HTTP 200',
        rollback: 'content/posts/test.md',
        traceId: 'trace-approval-1',
      },
    })
    expect(event.type).toBe('approval.result')
    if (event.type === 'approval.result') {
      expect(event.executed).toBe(true)
      expect(event.traceId).toBe('trace-approval-1')
      expect(event.permissionLevel).toBe('deploy-remote')
      expect(event.receipt?.target).toBe('https://iver.yivxer.com/posts/test/')
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

  it('converts a Python stream payload to ordered agent events', () => {
    const events = pythonStreamPayloadToAgentEvents('session-1', {
      contractVersion: 1,
      runtimeContextEvent: {
        id: 'ctx-1',
        traceId: 'trace-1',
        task: 'blog_publish',
        phase: 'execute',
        userIntent: 'deploy_existing_post',
        lastResult: 'hugo_file_created',
        expectedNext: 'build_and_deploy',
      },
      toolEvent: {
        id: 'tool-1',
        traceId: 'trace-1',
        name: 'obsidian_read',
        status: 'complete',
        risk: 'low',
        summary: '读取完成',
        detail: 'ok',
      },
      orchestrationEvent: {
        id: 'orch-1',
        traceId: 'trace-1',
        intent: 'project',
        subIntent: 'project_planning',
        mode: 'builder',
        depth: 'deep',
        labels: ['项目规划'],
        needsMemory: true,
        needsJob: false,
      },
      statusEvent: {
        traceId: 'trace-1',
        intentType: 'project',
        intentLabel: '项目规划',
        matchedSkills: ['obsidian_read'],
        isBackground: false,
        memoryScope: ['project'],
      },
      planEvent: {
        id: 'plan-1',
        traceId: 'trace-1',
        title: '继续执行',
        status: 'proposed',
        detail: 'next',
        steps: [],
      },
      initiativeEvent: {
        id: 'initiative-1',
        kind: 'thread_resume',
        title: '拾起未闭合话题',
        message: '上次还留着一个话题。',
        shadow: true,
        delivered: false,
        decisionTrace: { reason: 'stale_open_thread' },
      },
      failureHintEvent: {
        id: 'failure-1',
        traceId: 'trace-1',
        keyword: 'command_timeout',
        stage: 'deploy',
        recoverable: true,
        detail: 'deploy timed out',
      },
    })

    expect(events.map((event) => event.type)).toEqual([
      'runtime.context',
      'tool.request',
      'orchestration.event',
      'status.event',
      'plan.event',
      'initiative.event',
      'failure.hint',
    ])
    expect(events[0]).toMatchObject({
      type: 'runtime.context',
      traceId: 'trace-1',
      task: 'blog_publish',
      phase: 'execute',
      expectedNext: 'build_and_deploy',
    })
    expect(events[5]).toMatchObject({
      type: 'initiative.event',
      id: 'initiative-1',
      kind: 'thread_resume',
      shadow: true,
      delivered: false,
    })
    expect(events[6]).toMatchObject({
      type: 'failure.hint',
      keyword: 'command_timeout',
      stage: 'deploy',
      recoverable: true,
    })
  })
})
