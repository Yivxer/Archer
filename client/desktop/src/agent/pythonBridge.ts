import type { AgentEvent, ApprovalDecision, PlanStatus, RiskLevel, ToolStatus } from './contracts'

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

type PythonPlanEvent = {
  id: string
  title: string
  status: PlanStatus
  detail: string
  prompt?: string
  steps: Array<{
    id: number
    action: string
    tool: string
    requiresApproval: boolean
  }>
}

type PythonOrchestrationEvent = {
  id: string
  intent: string
  subIntent: string
  mode: string
  depth: string
  labels: string[]
  needsMemory: boolean
  needsJob: boolean
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

export function pythonPlanToAgentEvent(sessionId: string, plan: PythonPlanEvent): AgentEvent {
  return {
    type: 'plan.event',
    id: plan.id,
    sessionId,
    createdAt: nowIso(),
    title: plan.title,
    status: plan.status,
    detail: plan.detail,
    prompt: plan.prompt,
    steps: plan.steps,
  }
}

export function pythonOrchestrationToAgentEvent(
  sessionId: string,
  snapshot: PythonOrchestrationEvent,
): AgentEvent {
  return {
    type: 'orchestration.event',
    id: snapshot.id,
    sessionId,
    createdAt: nowIso(),
    intent: snapshot.intent,
    subIntent: snapshot.subIntent,
    mode: snapshot.mode,
    depth: snapshot.depth,
    labels: snapshot.labels,
    needsMemory: snapshot.needsMemory,
    needsJob: snapshot.needsJob,
  }
}

type PythonStatusEvent = {
  intentType: string
  intentLabel: string
  matchedSkills: string[]
  isBackground: boolean
  memoryScope: string[]
}

export function pythonStatusToAgentEvent(
  sessionId: string,
  snapshot: PythonStatusEvent,
): AgentEvent {
  return {
    type: 'status.event',
    id: `status-${crypto.randomUUID().slice(0, 8)}`,
    sessionId,
    createdAt: nowIso(),
    intentType: snapshot.intentType,
    intentLabel: snapshot.intentLabel,
    matchedSkills: snapshot.matchedSkills ?? [],
    isBackground: snapshot.isBackground ?? false,
    memoryScope: snapshot.memoryScope ?? [],
  }
}
