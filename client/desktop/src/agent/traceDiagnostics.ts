import type { AgentEvent, FailureHintEvent, RuntimeContextEvent } from './contracts'

const TRACE_EVENT_TYPES = new Set<AgentEvent['type']>([
  'runtime.context',
  'status.event',
  'tool.request',
  'tool.result',
  'approval.result',
  'failure.hint',
  'job.event',
])

export type TraceDiagnostics = {
  traceId: string
  empty: boolean
  runtimeContext?: RuntimeContextEvent
  failureHint?: FailureHintEvent
  recentEvents: AgentEvent[]
}

export function buildTraceDiagnostics(events: AgentEvent[], traceId: string, limit = 5): TraceDiagnostics {
  const relevant = events.filter((event) => (
    event.traceId === traceId && TRACE_EVENT_TYPES.has(event.type)
  ))
  const recentEvents = relevant.slice(-Math.max(1, limit))
  const runtimeContext = [...relevant].reverse().find((event): event is RuntimeContextEvent => event.type === 'runtime.context')
  const failureHint = [...relevant].reverse().find((event): event is FailureHintEvent => event.type === 'failure.hint')

  return {
    traceId,
    empty: relevant.length === 0,
    runtimeContext,
    failureHint,
    recentEvents,
  }
}
