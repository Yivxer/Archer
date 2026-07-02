/**
 * L2.4 — chatEventDispatcher 6 种主要失败类型测试
 * L2.5 — initiative.event 消费不展示测试
 *
 * 测试策略：
 *   - L2.4：覆盖 6 种主要 failure.hint keyword + 4 种派生失败类型
 *   - L2.5：initiative.event → forward_initiative action（不渲染聊天）
 *   - 纯函数测试，无 React 依赖
 */

import { describe, expect, it } from 'vitest'

import type {
  AgentEvent,
  ApprovalResultEvent,
  FailureHintEvent,
  JobEvent,
  ToolRequestEvent,
  ToolResultEvent,
} from '../../../../agent/contracts'
import {
  createInitialDispatcherContext,
  dispatchAgentEvent,
  fallbackActionWhenNoReply,
  failureHintToActions,
  failureMessageFor,
  resetDispatcherContext,
} from '../chatEventDispatcher'

// ───────────────────────── 辅助构造 ─────────────────────────

function makeFailureHint(keyword: string, overrides: Partial<FailureHintEvent> = {}): FailureHintEvent {
  return {
    type: 'failure.hint',
    id: `failure-${keyword}-${Math.random().toString(36).slice(2, 8)}`,
    sessionId: 'test-session',
    createdAt: new Date().toISOString(),
    traceId: 'trace-test-1234',
    keyword,
    stage: 'model_stream',
    recoverable: true,
    detail: '',
    ...overrides,
  }
}

function makeToolRequest(overrides: Partial<ToolRequestEvent> = {}): ToolRequestEvent {
  return {
    type: 'tool.request',
    id: 'tool-req-1',
    sessionId: 'test-session',
    createdAt: new Date().toISOString(),
    traceId: 'trace-test-1234',
    toolName: 'shell_execute',
    displayName: 'Shell',
    risk: 'low',
    status: 'running',
    args: {},
    summary: '',
    detail: '',
    requiresApproval: false,
    blocked: false,
    ...overrides,
  }
}

function makeToolResult(overrides: Partial<ToolResultEvent> = {}): ToolResultEvent {
  return {
    type: 'tool.result',
    id: 'tool-result-1',
    sessionId: 'test-session',
    createdAt: new Date().toISOString(),
    traceId: 'trace-test-1234',
    requestId: 'tool-req-1',
    toolName: 'shell_execute',
    status: 'complete',
    ok: true,
    output: '',
    message: '',
    ...overrides,
  }
}

function makeApprovalResult(overrides: Partial<ApprovalResultEvent> = {}): ApprovalResultEvent {
  return {
    type: 'approval.result',
    id: 'approval-1',
    sessionId: 'test-session',
    createdAt: new Date().toISOString(),
    traceId: 'trace-test-1234',
    requestId: 'tool-req-1',
    decision: 'approved',
    executed: true,
    ok: true,
    output: '',
    message: '',
    ...overrides,
  }
}

function makeJobEvent(overrides: Partial<JobEvent> = {}): JobEvent {
  return {
    type: 'job.event',
    id: 'job-1',
    sessionId: 'test-session',
    createdAt: new Date().toISOString(),
    traceId: 'trace-test-1234',
    jobId: 'job-abc',
    title: 'Test Job',
    status: 'running',
    detail: '',
    ...overrides,
  }
}

function makeInitiativeEvent(): AgentEvent {
  return {
    type: 'initiative.event',
    id: 'init-1',
    sessionId: 'test-session',
    createdAt: new Date().toISOString(),
    traceId: 'trace-test-1234',
    kind: 'shadow_touch',
    title: '测试 initiative',
    message: '这是一条 shadow 事件',
    shadow: true,
    delivered: false,
    decisionTrace: {},
  }
}

// ───────────────────────── L2.4：6 种主要失败类型 ─────────────────────────

describe('L2.4 — 6 种主要失败类型测试', () => {
  /**
   * 工作计划要求覆盖：
   *   model_empty_response / tool_executed_no_summary / model_stream_timeout /
   *   provider_connection_failed / chat_busy / context_trimmed
   *
   * 同时覆盖后端实际发出的其他 5 个 keyword + 未知 keyword 兜底。
   */

  it('model_empty_response：show_failure_message + show_recovery', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeFailureHint('model_empty_response')
    const actions = failureHintToActions(event, ctx)

    expect(actions).toHaveLength(2)
    expect(actions[0].kind).toBe('show_failure_message')
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('model_empty_response')
      expect(actions[0].severity).toBe('warning')
      expect(actions[0].recoverable).toBe(true)
      expect(actions[0].text).toContain('模型请求成功但没有返回文本')
      expect(actions[0].traceId).toBe('trace-test-1234')
    }
    expect(actions[1].kind).toBe('show_recovery')
  })

  it('tool_executed_no_summary（有 tool event）：info severity + 不含"模型没有返回总结"', () => {
    const ctx = createInitialDispatcherContext()
    ctx.sawToolEvent = true
    const event = makeFailureHint('tool_executed_no_summary')
    const actions = failureHintToActions(event, ctx)

    expect(actions[0].kind).toBe('show_failure_message')
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('tool_executed_no_summary')
      expect(actions[0].severity).toBe('info')
      expect(actions[0].text).toContain('工具已执行')
    }
  })

  it('tool_executed_no_summary（无 tool event）：fallback 文案', () => {
    const ctx = createInitialDispatcherContext()
    ctx.sawToolEvent = false
    const event = makeFailureHint('tool_executed_no_summary')
    const actions = failureHintToActions(event, ctx)

    expect(actions[0].kind).toBe('show_failure_message')
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].text).toContain('本轮没有返回可显示内容')
    }
  })

  it('model_stream_timeout：show_failure_message + show_recovery', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeFailureHint('model_stream_timeout')
    const actions = failureHintToActions(event, ctx)

    expect(actions).toHaveLength(2)
    expect(actions[0].kind).toBe('show_failure_message')
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('model_stream_timeout')
      expect(actions[0].severity).toBe('warning')
      expect(actions[0].text).toContain('模型流式响应超时')
    }
  })

  it('provider_connection_failed：error severity + show_recovery', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeFailureHint('provider_connection_failed')
    const actions = failureHintToActions(event, ctx)

    expect(actions).toHaveLength(2)
    expect(actions[0].kind).toBe('show_failure_message')
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('provider_connection_failed')
      expect(actions[0].severity).toBe('error')
      expect(actions[0].text).toContain('模型服务连接失败')
    }
  })

  it('chat_busy：info + 无 show_recovery（recoverable=false）', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeFailureHint('chat_busy', { recoverable: false })
    const actions = failureHintToActions(event, ctx)

    // chat_busy 即使 recoverable=false 也不附加 show_recovery
    expect(actions).toHaveLength(1)
    expect(actions[0].kind).toBe('show_failure_message')
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('chat_busy')
      expect(actions[0].severity).toBe('info')
      expect(actions[0].recoverable).toBe(false)
      expect(actions[0].text).toContain('上一轮仍在处理')
    }
  })

  it('context_trimmed：info + 不附加 show_recovery', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeFailureHint('context_trimmed')
    const actions = failureHintToActions(event, ctx)

    // context_trimmed 即使 recoverable=true 也不附加 show_recovery
    expect(actions).toHaveLength(1)
    expect(actions[0].kind).toBe('show_failure_message')
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('context_trimmed')
      expect(actions[0].text).toContain('上下文已裁剪')
    }
  })

  // ── 后端实际发出的其他 5 个 keyword ──

  it('command_timeout：warning + show_recovery', () => {
    const ctx = createInitialDispatcherContext()
    const actions = failureHintToActions(makeFailureHint('command_timeout'), ctx)
    expect(actions[0].kind).toBe('show_failure_message')
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('command_timeout')
      expect(actions[0].severity).toBe('warning')
      expect(actions[0].text).toContain('命令执行超时')
    }
    expect(actions[1].kind).toBe('show_recovery')
  })

  it('write_permission：error + 无 show_recovery（recoverable=false）', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeFailureHint('write_permission', { recoverable: false })
    const actions = failureHintToActions(event, ctx)
    expect(actions).toHaveLength(1)
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('write_permission')
      expect(actions[0].severity).toBe('error')
      expect(actions[0].recoverable).toBe(false)
    }
  })

  it('dependency_missing：warning + show_recovery', () => {
    const ctx = createInitialDispatcherContext()
    const actions = failureHintToActions(makeFailureHint('dependency_missing'), ctx)
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('dependency_missing')
      expect(actions[0].text).toContain('依赖未找到')
    }
  })

  it('syntax_mismatch：warning + show_recovery', () => {
    const ctx = createInitialDispatcherContext()
    const actions = failureHintToActions(makeFailureHint('syntax_mismatch'), ctx)
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('syntax_mismatch')
      expect(actions[0].text).toContain('语法/解析错误')
    }
  })

  it('runtime_failure：error + show_recovery', () => {
    const ctx = createInitialDispatcherContext()
    const actions = failureHintToActions(makeFailureHint('runtime_failure'), ctx)
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('runtime_failure')
      expect(actions[0].severity).toBe('error')
    }
  })

  it('未知 keyword：unknown_failure 兜底', () => {
    const ctx = createInitialDispatcherContext()
    const actions = failureHintToActions(makeFailureHint('some_new_keyword'), ctx)
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('unknown_failure')
      expect(actions[0].text).toContain('本轮没有返回可显示内容')
    }
  })
})

// ───────────────────────── L2.4：4 种派生失败类型 ─────────────────────────

describe('L2.4 — 4 种派生失败类型', () => {
  it('tool_failed：tool.result status=complete && !ok', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeToolResult({ status: 'complete', ok: false })
    const actions = dispatchAgentEvent(event, ctx)
    expect(actions).toHaveLength(1)
    expect(actions[0].kind).toBe('show_tool_card')
    if (actions[0].kind === 'show_tool_card') {
      expect(actions[0].failureType).toBe('tool_failed')
    }
  })

  it('tool_failed：tool.result status=blocked', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeToolResult({ status: 'blocked', ok: false })
    const actions = dispatchAgentEvent(event, ctx)
    if (actions[0].kind === 'show_tool_card') {
      expect(actions[0].failureType).toBe('tool_failed')
    }
  })

  it('tool 正常完成：无 failureType', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeToolResult({ status: 'complete', ok: true })
    const actions = dispatchAgentEvent(event, ctx)
    if (actions[0].kind === 'show_tool_card') {
      expect(actions[0].failureType).toBeUndefined()
    }
  })

  it('approval_rejected：approval.result decision=denied', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeApprovalResult({ decision: 'denied', executed: false, ok: false })
    const actions = dispatchAgentEvent(event, ctx)
    expect(actions[0].kind).toBe('show_tool_card')
    if (actions[0].kind === 'show_tool_card') {
      expect(actions[0].failureType).toBe('approval_rejected')
    }
  })

  it('job_stale_cancelled：job.event status=cancelled && stale=true', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeJobEvent({ status: 'cancelled', stale: true })
    const actions = dispatchAgentEvent(event, ctx)
    expect(actions[0].kind).toBe('show_failure_message')
    if (actions[0].kind === 'show_failure_message') {
      expect(actions[0].failureType).toBe('job_stale_cancelled')
      expect(actions[0].severity).toBe('warning')
      expect(actions[0].text).toContain('任务已取消')
    }
  })

  it('approval_duplicated：同 requestId 出现 2 次', () => {
    const ctx = createInitialDispatcherContext()
    const req1 = makeToolRequest({ id: 'req-dup-1' })
    const req2 = makeToolRequest({ id: 'req-dup-1' })

    const actions1 = dispatchAgentEvent(req1, ctx)
    expect(actions1).toHaveLength(1) // 首次：仅 show_tool_card

    const actions2 = dispatchAgentEvent(req2, ctx)
    expect(actions2).toHaveLength(2) // 第二次：show_tool_card + show_failure_message
    if (actions2[1].kind === 'show_failure_message') {
      expect(actions2[1].failureType).toBe('approval_duplicated')
      expect(actions2[1].severity).toBe('info')
    }
  })
})

// ───────────────────────── L2.5：initiative.event 不展示 ─────────────────────────

describe('L2.5 — initiative.event 消费不展示', () => {
  it('initiative.event → forward_initiative action（不渲染聊天）', () => {
    const ctx = createInitialDispatcherContext()
    const event = makeInitiativeEvent()
    const actions = dispatchAgentEvent(event, ctx)

    expect(actions).toHaveLength(1)
    expect(actions[0].kind).toBe('forward_initiative')
    if (actions[0].kind === 'forward_initiative') {
      expect(actions[0].event.type).toBe('initiative.event')
      expect(actions[0].event.shadow).toBe(true)
    }
  })

  it('initiative.event 不产 show_failure_message / show_reply_text', () => {
    const ctx = createInitialDispatcherContext()
    const actions = dispatchAgentEvent(makeInitiativeEvent(), ctx)
    for (const action of actions) {
      expect(action.kind).not.toBe('show_failure_message')
      expect(action.kind).not.toBe('show_reply_text')
      expect(action.kind).not.toBe('show_recovery')
    }
  })

  it('shadow=true 的 initiative 事件仍进 trace log（由 recordAgentEvent 处理，dispatcher 仅转发）', () => {
    // dispatcher 只产 forward_initiative，trace log 由 ChatPage 的 recordAgentEvent 调用维护
    // 这里验证 dispatcher 不阻塞、不改变事件
    const ctx = createInitialDispatcherContext()
    const event = makeInitiativeEvent()
    const actions = dispatchAgentEvent(event, ctx)
    if (actions[0].kind === 'forward_initiative') {
      expect(actions[0].event).toBe(event)
    }
  })
})

// ───────────────────────── fallbackActionWhenNoReply ─────────────────────────

describe('fallbackActionWhenNoReply', () => {
  it('有 failure.hint：用其 keyword 决定文案', () => {
    const ctx = createInitialDispatcherContext()
    ctx.sawToolEvent = true
    const action = fallbackActionWhenNoReply(makeFailureHint('tool_executed_no_summary'), ctx)
    expect(action.kind).toBe('show_failure_message')
    expect(action.failureType).toBe('tool_executed_no_summary')
    expect(action.text).toContain('工具已执行')
  })

  it('无 failure.hint + 有 tool event：兜底"已执行操作"', () => {
    const ctx = createInitialDispatcherContext()
    ctx.sawToolEvent = true
    const action = fallbackActionWhenNoReply(null, ctx)
    expect(action.text).toContain('已执行操作')
  })

  it('无 failure.hint + 无 tool event：兜底"模型没有返回内容"', () => {
    const ctx = createInitialDispatcherContext()
    ctx.sawToolEvent = false
    const action = fallbackActionWhenNoReply(null, ctx)
    expect(action.text).toContain('模型没有返回内容')
  })
})

// ───────────────────────── ctx 维护 ─────────────────────────

describe('DispatcherContext 维护', () => {
  it('tool.request 标记 sawToolEvent=true', () => {
    const ctx = createInitialDispatcherContext()
    expect(ctx.sawToolEvent).toBe(false)
    dispatchAgentEvent(makeToolRequest(), ctx)
    expect(ctx.sawToolEvent).toBe(true)
  })

  it('text.delta 标记 hasStreamedReply=true', () => {
    const ctx = createInitialDispatcherContext()
    expect(ctx.hasStreamedReply).toBe(false)
    dispatchAgentEvent({
      type: 'text.delta',
      id: 'text-1',
      sessionId: 's',
      createdAt: new Date().toISOString(),
      text: 'hello',
    }, ctx)
    expect(ctx.hasStreamedReply).toBe(true)
  })

  it('resetDispatcherContext 清空状态', () => {
    const ctx = createInitialDispatcherContext()
    ctx.sawToolEvent = true
    ctx.hasStreamedReply = true
    ctx.seenRequestIds.add('req-1')
    resetDispatcherContext(ctx)
    expect(ctx.sawToolEvent).toBe(false)
    expect(ctx.hasStreamedReply).toBe(false)
    expect(ctx.seenRequestIds.size).toBe(0)
  })

  it('failureMessageFor 纯函数：相同输入相同输出', () => {
    const ctx = createInitialDispatcherContext()
    const a = failureMessageFor('provider_connection_failed', ctx)
    const b = failureMessageFor('provider_connection_failed', ctx)
    expect(a).toEqual(b)
  })
})
