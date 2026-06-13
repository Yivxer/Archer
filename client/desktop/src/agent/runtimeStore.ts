import type { AgentEvent, ApprovalResultEvent, JobEvent, OrchestrationEvent, PlanEvent, RuntimeSession, ToolRequestEvent } from './contracts'

export type RuntimeState = RuntimeSession & {
  streamingText: string
  pendingApprovals: ToolRequestEvent[]
  toolResults: Record<string, ApprovalResultEvent>
  jobs: Record<string, JobEvent>
  plans: Record<string, PlanEvent>
  orchestrations: Record<string, OrchestrationEvent>
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

  if (event.type === 'runtime.error') {
    return {
      ...state,
      events,
      status: 'error',
    }
  }

  return { ...state, events }
}
