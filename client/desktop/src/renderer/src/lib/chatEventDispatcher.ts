/**
 * L2.2 — chatEventDispatcher.ts
 *
 * 把 AgentEvent 映射到 UI action，统一处理 failure.hint + 派生失败类型。
 * ChatPage 不再自己判断"应该显示什么文案"，全部走 dispatcher。
 *
 * 契约来源：
 *   - docs/api-contract.md §「SSE 事件契约（L2.1）」
 *   - Archer 稳定性框架 §五「事件矩阵」
 *
 * 纯函数模块，无 React 依赖，方便 SSR 测试。
 */

import type {
  AgentEvent,
  ApprovalResultEvent,
  FailureHintEvent,
  InitiativeEvent,
  JobEvent,
  ToolRequestEvent,
  ToolResultEvent,
} from '../../../agent/contracts'

// ───────────────────────── 类型 ─────────────────────────

/**
 * failure.hint keyword + 派生失败类型的并集。
 *
 * 后端实际发出（_failure_hint_event + 内联）的 8 个 keyword：
 *   provider_connection_failed / command_timeout / write_permission /
 *   dependency_missing / syntax_mismatch / runtime_failure /
 *   model_empty_response / tool_executed_no_summary
 *
 * 前端历史已有但后端当前不发（保留兼容）的 3 个：
 *   model_stream_timeout / chat_busy / context_trimmed
 *
 * 派生失败（dispatcher 从其他 AgentEvent 推导）的 4 个：
 *   tool_failed / approval_rejected / job_stale_cancelled / approval_duplicated
 */
export type FailureType =
  // 后端 _failure_hint_event keyword
  | 'provider_connection_failed'
  | 'command_timeout'
  | 'write_permission'
  | 'dependency_missing'
  | 'syntax_mismatch'
  | 'runtime_failure'
  // 后端内联 keyword
  | 'model_empty_response'
  | 'tool_executed_no_summary'
  // 前端 legacy（保留兼容）
  | 'model_stream_timeout'
  | 'chat_busy'
  | 'context_trimmed'
  // 派生失败
  | 'tool_failed'
  | 'approval_rejected'
  | 'job_stale_cancelled'
  | 'approval_duplicated'
  // 未知兜底
  | 'unknown_failure'

export type FailureSeverity = 'info' | 'warning' | 'error'

/**
 * dispatcher 在消费事件流时维护的可变上下文。
 *
 * - sawToolEvent：本轮是否已见 tool.request / tool.result（用于 failure.hint 兜底文案）
 * - hasStreamedReply：本轮是否已收到 text.delta / text.final（决定是否需要兜底文案）
 * - seenRequestIds：已见 tool.request.id 集合（推导 approval_duplicated）
 */
export type DispatcherContext = {
  sawToolEvent: boolean
  hasStreamedReply: boolean
  seenRequestIds: Set<string>
}

export type DispatcherAction =
  | { kind: 'show_reply_text'; text: string; traceId?: string }
  | {
      kind: 'show_failure_message'
      text: string
      failureType: FailureType
      severity: FailureSeverity
      traceId?: string
      recoverable: boolean
    }
  | {
      kind: 'show_tool_card'
      event: ToolRequestEvent | ToolResultEvent | ApprovalResultEvent
      failureType?: FailureType
    }
  | {
      kind: 'show_recovery'
      failureType: FailureType
      traceId?: string
      detail?: string
    }
  | { kind: 'forward_initiative'; event: InitiativeEvent }
  | { kind: 'silent_log' }

/** show_failure_message action 的具体类型，用于 fallbackActionWhenNoReply 返回值 */
export type ShowFailureMessageAction = Extract<DispatcherAction, { kind: 'show_failure_message' }>

// ───────────────────────── 上下文 ─────────────────────────

export function createInitialDispatcherContext(): DispatcherContext {
  return {
    sawToolEvent: false,
    hasStreamedReply: false,
    seenRequestIds: new Set<string>(),
  }
}

/**
 * 重置上下文（用于新一轮对话开始）。
 * 复用现有 Set 减少分配。
 */
export function resetDispatcherContext(ctx: DispatcherContext): void {
  ctx.sawToolEvent = false
  ctx.hasStreamedReply = false
  ctx.seenRequestIds.clear()
}

// ───────────────────────── 主入口 ─────────────────────────

/**
 * 消费一个 AgentEvent，返回需要执行的 UI action 列表（可能为空）。
 *
 * 副作用：会修改 ctx（更新 sawToolEvent / hasStreamedReply / seenRequestIds）。
 *
 * @param event AgentEvent
 * @param ctx 可变上下文（跨事件保持状态）
 * @returns UI action 列表
 */
export function dispatchAgentEvent(event: AgentEvent, ctx: DispatcherContext): DispatcherAction[] {
  switch (event.type) {
    case 'text.delta':
    case 'text.final':
      ctx.hasStreamedReply = true
      return [event.type === 'text.final'
        ? { kind: 'show_reply_text', text: event.text, traceId: event.traceId }
        : { kind: 'silent_log' }]

    case 'tool.request':
      return dispatchToolRequest(event, ctx)

    case 'tool.result':
      return dispatchToolResult(event, ctx)

    case 'approval.result':
      return dispatchApprovalResult(event, ctx)

    case 'job.event':
      return dispatchJobEvent(event)

    case 'initiative.event':
      // L2.5：shadow 事件进 trace log + 转发父组件，不渲染到聊天
      return [{ kind: 'forward_initiative', event }]

    case 'failure.hint':
      return failureHintToActions(event, ctx)

    case 'runtime.error':
      return [{
        kind: 'show_failure_message',
        text: event.message || '运行时错误，请打开诊断查看详情。',
        failureType: 'unknown_failure',
        severity: 'error',
        traceId: event.traceId,
        recoverable: event.recoverable,
      }]

    case 'plan.event':
    case 'orchestration.event':
    case 'status.event':
    case 'runtime.context':
      // 这些事件由 ChatPage 现有逻辑（trace 面板 / runtimeStore）处理，
      // dispatcher 只标记 silent_log（无额外 UI action）
      return [{ kind: 'silent_log' }]

    default:
      // 兜底：未知事件类型，静默
      return [{ kind: 'silent_log' }]
  }
}

// ───────────────────────── tool 分支 ─────────────────────────

function dispatchToolRequest(event: ToolRequestEvent, ctx: DispatcherContext): DispatcherAction[] {
  ctx.sawToolEvent = true
  const actions: DispatcherAction[] = [{ kind: 'show_tool_card', event }]

  // 派生 approval_duplicated：同 requestId 重复出现
  if (ctx.seenRequestIds.has(event.id)) {
    actions.push({
      kind: 'show_failure_message',
      text: '已复用上次审批结果，未重复执行工具。',
      failureType: 'approval_duplicated',
      severity: 'info',
      traceId: event.traceId,
      recoverable: false,
    })
  } else {
    ctx.seenRequestIds.add(event.id)
  }

  return actions
}

function dispatchToolResult(event: ToolResultEvent, ctx: DispatcherContext): DispatcherAction[] {
  ctx.sawToolEvent = true

  // 派生 tool_failed：status=complete && !ok，或 status=blocked
  if ((event.status === 'complete' && !event.ok) || event.status === 'blocked') {
    return [{
      kind: 'show_tool_card',
      event,
      failureType: 'tool_failed',
    }]
  }

  return [{ kind: 'show_tool_card', event }]
}

function dispatchApprovalResult(event: ApprovalResultEvent, _ctx: DispatcherContext): DispatcherAction[] {
  // 派生 approval_rejected：decision=denied
  if (event.decision === 'denied') {
    return [{
      kind: 'show_tool_card',
      event,
      failureType: 'approval_rejected',
    }]
  }
  return [{ kind: 'show_tool_card', event }]
}

function dispatchJobEvent(event: JobEvent): DispatcherAction[] {
  // 派生 job_stale_cancelled：status=cancelled && stale=true
  if (event.status === 'cancelled' && event.stale === true) {
    return [{
      kind: 'show_failure_message',
      text: '任务已取消（无进展超时），可重新发起。',
      failureType: 'job_stale_cancelled',
      severity: 'warning',
      traceId: event.traceId,
      recoverable: true,
    }]
  }
  return [{ kind: 'silent_log' }]
}

// ───────────────────────── failure.hint 分支 ─────────────────────────

/**
 * 把 FailureHintEvent 转成 UI action。
 *
 * - recoverable=true：show_failure_message + show_recovery（用户可重试）
 * - recoverable=false：show_failure_message（仅提示，需检查配置/权限）
 * - chat_busy：只 info 提示，无 recovery
 */
export function failureHintToActions(event: FailureHintEvent, ctx: DispatcherContext): DispatcherAction[] {
  const message = failureMessageFor(event.keyword, ctx)
  const actions: DispatcherAction[] = [{
    kind: 'show_failure_message',
    text: message.text,
    failureType: message.failureType,
    severity: message.severity,
    traceId: event.traceId,
    recoverable: event.recoverable && message.recoverable,
  }]

  // recoverable 且非 chat_busy/context_trimmed 时附加重试入口
  if (event.recoverable && message.recoverable && message.failureType !== 'chat_busy' && message.failureType !== 'context_trimmed') {
    actions.push({
      kind: 'show_recovery',
      failureType: message.failureType,
      traceId: event.traceId,
      detail: event.detail,
    })
  }

  return actions
}

// ───────────────────────── failure 文案矩阵 ─────────────────────────

/**
 * failure.hint keyword → UI 文案 + severity + recoverable。
 *
 * 覆盖：
 *   - 后端实际发出 8 个 keyword
 *   - 前端 legacy 3 个 keyword（保留兼容，后端当前不发）
 *   - 未知 keyword 兜底
 *
 * 注意：派生失败类型（tool_failed / approval_rejected / job_stale_cancelled / approval_duplicated）
 * 不经过此函数，由各自 dispatch 分支直接产 show_tool_card / show_failure_message。
 */
export function failureMessageFor(
  keyword: string,
  ctx: DispatcherContext,
): { text: string; failureType: FailureType; severity: FailureSeverity; recoverable: boolean } {
  switch (keyword) {
    // ── 后端实际发出 ──
    case 'model_empty_response':
      return {
        text: '模型请求成功但没有返回文本，请打开诊断查看本轮模型状态。',
        failureType: 'model_empty_response',
        severity: 'warning',
        recoverable: true,
      }
    case 'tool_executed_no_summary':
      return {
        text: ctx.sawToolEvent
          ? '工具已执行，但模型没有返回总结，结果见上方卡片。'
          : '本轮没有返回可显示内容，请打开诊断查看原因。',
        failureType: 'tool_executed_no_summary',
        severity: 'info',
        recoverable: true,
      }
    case 'provider_connection_failed':
      return {
        text: '模型服务连接失败，请检查当前 provider/API 配置。',
        failureType: 'provider_connection_failed',
        severity: 'error',
        recoverable: true,
      }
    case 'command_timeout':
      return {
        text: '命令执行超时或连接失败，可重试。',
        failureType: 'command_timeout',
        severity: 'warning',
        recoverable: true,
      }
    case 'write_permission':
      return {
        text: '写入权限被拒绝，请检查配置/权限。',
        failureType: 'write_permission',
        severity: 'error',
        recoverable: false,
      }
    case 'dependency_missing':
      return {
        text: '依赖未找到，请进入设置/doctor 检查。',
        failureType: 'dependency_missing',
        severity: 'warning',
        recoverable: true,
      }
    case 'syntax_mismatch':
      return {
        text: '语法/解析错误，可重试。',
        failureType: 'syntax_mismatch',
        severity: 'warning',
        recoverable: true,
      }
    case 'runtime_failure':
      return {
        text: '运行时异常，请打开诊断查看详情。',
        failureType: 'runtime_failure',
        severity: 'error',
        recoverable: true,
      }

    // ── 前端 legacy（保留兼容） ──
    case 'model_stream_timeout':
      return {
        text: '模型流式响应超时，请稍后重试。',
        failureType: 'model_stream_timeout',
        severity: 'warning',
        recoverable: true,
      }
    case 'chat_busy':
      return {
        text: '上一轮仍在处理，请等它结束后再发送。',
        failureType: 'chat_busy',
        severity: 'info',
        recoverable: false,
      }
    case 'context_trimmed':
      return {
        text: '本轮上下文已裁剪，部分旧历史没有带入。',
        failureType: 'context_trimmed',
        severity: 'info',
        recoverable: true,
      }

    // ── 未知 keyword 兜底 ──
    default:
      return {
        text: '本轮没有返回可显示内容，请打开诊断查看原因。',
        failureType: 'unknown_failure',
        severity: 'warning',
        recoverable: true,
      }
  }
}

// ───────────────────────── 辅助：流结束兜底 ─────────────────────────

/**
 * 当流结束但未收到 text.final 时，根据 ctx 决定兜底 action。
 *
 * 使用场景：ChatPage 在 streamLocalChat 完成后，如果 !hasStreamedReply，
 * 调用此函数获取兜底文案 action。
 *
 * @param lastFailureHint 本轮最后一个 failure.hint 事件（可能为 null）
 * @param ctx dispatcher 上下文
 */
export function fallbackActionWhenNoReply(
  lastFailureHint: FailureHintEvent | null,
  ctx: DispatcherContext,
): ShowFailureMessageAction {
  if (lastFailureHint) {
    const message = failureMessageFor(lastFailureHint.keyword, ctx)
    return {
      kind: 'show_failure_message',
      text: message.text,
      failureType: message.failureType,
      severity: message.severity,
      traceId: lastFailureHint.traceId,
      recoverable: lastFailureHint.recoverable && message.recoverable,
    }
  }

  // 无 failure.hint：根据是否有 tool event 决定文案
  return {
    kind: 'show_failure_message',
    text: ctx.sawToolEvent
      ? '已执行操作，详见上方卡片。'
      : '模型没有返回内容，请打开诊断查看原因。',
    failureType: 'unknown_failure',
    severity: 'warning',
    recoverable: true,
  }
}
