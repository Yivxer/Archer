import type { AgentEvent, ApprovalResultEvent, FailureHintEvent, JobEvent, OrchestrationEvent, PlanEvent, RuntimeContextEvent, RuntimeSession, ToolRequestEvent } from './contracts'

export const RESTORED_ACTIVE_JOB_STALE_MS = 15 * 60 * 1000

export type RuntimeState = RuntimeSession & {
  streamingText: string
  pendingApprovals: ToolRequestEvent[]
  toolResults: Record<string, ApprovalResultEvent>
  jobs: Record<string, JobEvent>
  plans: Record<string, PlanEvent>
  orchestrations: Record<string, OrchestrationEvent>
  runtimeContext?: RuntimeContextEvent
  failureHints: Record<string, FailureHintEvent>
}

export function createInitialRuntimeState(sessionId: string): RuntimeState {
  return {
    id: sessionId,
    messages: [],
    events: [],
    status: 'idle',
    streamingText: '',
    pendingApprovals: [],
    toolResults: {},
    jobs: {},
    plans: {},
    orchestrations: {},
    failureHints: {},
  }
}

export function restoreRuntimeStateFromEvents(
  sessionId: string,
  events: AgentEvent[],
  options: { now?: number; activeJobStaleMs?: number } = {},
): RuntimeState {
  // 按 createdAt 排序后再 reduce，避免乱序事件导致状态不一致
  // （如 text.final 在 text.delta 前处理会导致状态错误）
  const sorted = [...events].sort((a, b) => {
    // createdAt 是 ISO 字符串，用 Date.parse 转换为时间戳比较
    const ta = a.createdAt ? Date.parse(a.createdAt) : 0
    const tb = b.createdAt ? Date.parse(b.createdAt) : 0
    return ta - tb
  })
  const restored = sorted
    .filter((event) => event.sessionId === sessionId)
    .reduce((current, event) => reduceRuntimeEvent(current, event), createInitialRuntimeState(sessionId))
  return markStaleRestoredJobs(restored, options.now ?? Date.now(), options.activeJobStaleMs ?? RESTORED_ACTIVE_JOB_STALE_MS)
}

function markStaleRestoredJobs(state: RuntimeState, now: number, activeJobStaleMs: number): RuntimeState {
  const jobs = { ...state.jobs }
  let changed = false
  for (const [jobId, job] of Object.entries(jobs)) {
    const isActive = job.status === 'queued' || job.status === 'running' || job.status === 'waiting_approval'
    const createdAt = Date.parse(job.createdAt || '')
    if (!isActive || !Number.isFinite(createdAt) || now - createdAt < activeJobStaleMs) continue
    jobs[jobId] = {
      ...job,
      status: 'cancelled',
      stale: true,
      detail: job.detail ? `重启后检测到任务长时间无进展，已标记取消。${job.detail}` : '重启后检测到任务长时间无进展，已标记取消。',
    }
    changed = true
  }
  if (!changed) return state
  const hasActive = Object.values(jobs).some((job) => job.status === 'queued' || job.status === 'running' || job.status === 'waiting_approval')
  return {
    ...state,
    status: hasActive ? 'running_job' : state.pendingApprovals.length ? 'waiting_approval' : 'idle',
    jobs,
  }
}

export function reduceRuntimeEvent(state: RuntimeState, event: AgentEvent): RuntimeState {
  const events = state.events.some((item) => item.id === event.id)
    ? state.events
    : [...state.events, event]

  if (event.type === 'text.delta') {
    return {
      ...state,
      events,
      status: 'streaming',
      streamingText: state.streamingText + event.text,
    }
  }

  if (event.type === 'text.final') {
    return {
      ...state,
      events,
      status: 'idle',
      streamingText: '',
      messages: [
        ...state.messages,
        { id: event.id, role: 'assistant', text: event.text },
      ],
    }
  }

  if (event.type === 'tool.request') {
    const pendingApprovals = event.requiresApproval && !event.blocked
      ? [...state.pendingApprovals.filter((item) => item.id !== event.id), event]
      : state.pendingApprovals
    return {
      ...state,
      events,
      status: pendingApprovals.length ? 'waiting_approval' : state.status,
      pendingApprovals,
    }
  }

  if (event.type === 'approval.result') {
    const pendingApprovals = state.pendingApprovals.filter((item) => item.id !== event.requestId)
    return {
      ...state,
      events,
      status: pendingApprovals.length ? 'waiting_approval' : 'idle',
      pendingApprovals,
      toolResults: {
        ...state.toolResults,
        [event.requestId]: event,
      },
    }
  }

  if (event.type === 'job.event') {
    const isActiveJob = event.status === 'queued' || event.status === 'running' || event.status === 'waiting_approval'
    return {
      ...state,
      events,
      status: isActiveJob
        ? 'running_job'
        : state.pendingApprovals.length
          ? 'waiting_approval'
          : 'idle',
      jobs: {
        ...state.jobs,
        [event.jobId]: event,
      },
    }
  }

  if (event.type === 'plan.event') {
    return {
      ...state,
      events,
      plans: {
        ...state.plans,
        [event.id]: event,
      },
    }
  }

  if (event.type === 'orchestration.event') {
    return {
      ...state,
      events,
      orchestrations: {
        ...state.orchestrations,
        [event.id]: event,
      },
    }
  }

  if (event.type === 'runtime.context') {
    return {
      ...state,
      events,
      runtimeContext: event,
    }
  }

  if (event.type === 'failure.hint') {
    return {
      ...state,
      events,
      failureHints: {
        ...state.failureHints,
        [event.id]: event,
      },
    }
  }

  if (event.type === 'runtime.error') {
    return {
      ...state,
      events,
      status: 'error',
    }
  }

  return { ...state, events }
}
