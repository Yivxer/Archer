import type { AgentEvent, ApprovalDecision, RiskLevel, ToolStatus } from './contracts'

type PythonToolEvent = {
  id: string
  name: string
  status: 'running' | 'waiting' | 'complete' | 'blocked' | 'denied'
  risk: RiskLevel
  summary: string
  detail: string
  requiresApproval?: boolean
  draft?: {
    skillName?: string
    displayName?: string
    args?: Record<string, unknown>
    blocked?: boolean
    [key: string]: unknown
  }
}

type PythonApprovalResult = {
  ok: boolean
  eventId: string
  decision: ApprovalDecision
  executed: boolean
  output?: string
  message: string
}

function nowIso(): string {
  return new Date().toISOString()
}

function mapToolStatus(status: PythonToolEvent['status'], requiresApproval: boolean): ToolStatus {
  if (requiresApproval && status === 'waiting') return 'waiting_approval'
  if (status === 'waiting') return 'running'
  return status
}

export function pythonToolEventToAgentEvent(sessionId: string, event: PythonToolEvent): AgentEvent {
  const requiresApproval = Boolean(event.requiresApproval)
  const draft = event.draft || {}
  return {
    type: 'tool.request',
    id: event.id,
    sessionId,
    createdAt: nowIso(),
    toolName: String(draft.skillName || event.name),
    displayName: String(draft.displayName || event.name),
    risk: event.risk,
    status: mapToolStatus(event.status, requiresApproval),
    args: (draft.args as Record<string, unknown>) || {},
    summary: event.summary,
    detail: event.detail,
    requiresApproval,
    blocked: Boolean(draft.blocked || event.status === 'blocked'),
    draft,
  }
}

export function pythonApprovalToAgentEvent(sessionId: string, result: PythonApprovalResult): AgentEvent {
  return {
    type: 'approval.result',
    id: `approval-${result.eventId}`,
    sessionId,
    createdAt: nowIso(),
    requestId: result.eventId,
    decision: result.decision,
    executed: result.executed,
    ok: result.ok,
    output: result.output || '',
    message: result.message,
  }
}
