import type { AgentEvent, ApprovalDecision, PermissionLevel, PlanStatus, RiskLevel, ToolStatus, WorkReceipt } from './contracts'

type PythonToolEvent = {
  id: string
  traceId?: string
  name: string
  status: 'running' | 'waiting' | 'complete' | 'blocked' | 'denied'
  risk: RiskLevel
  permissionLevel?: PermissionLevel
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

export type PythonApprovalResult = {
  ok: boolean
  eventId: string
  traceId?: string
  decision: ApprovalDecision
  permissionLevel?: PermissionLevel
  executed: boolean
  output?: string
  message: string
  receipt?: WorkReceipt
  workReceipt?: WorkReceipt
}

type PythonPlanEvent = {
  id: string
  traceId?: string
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
  traceId?: string
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
    traceId: event.traceId,
    toolName: String(draft.skillName || event.name),
    displayName: String(draft.displayName || event.name),
    risk: event.risk,
    permissionLevel: event.permissionLevel,
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
  const receipt = result.receipt || result.workReceipt
  return {
    type: 'approval.result',
    id: `approval-${result.eventId}`,
    sessionId,
    createdAt: nowIso(),
    traceId: result.traceId,
    requestId: result.eventId,
    decision: result.decision,
    permissionLevel: result.permissionLevel,
    executed: result.executed,
    ok: result.ok,
    output: result.output || '',
    message: result.message,
    receipt,
  }
}

export function pythonPlanToAgentEvent(sessionId: string, plan: PythonPlanEvent): AgentEvent {
  return {
    type: 'plan.event',
    id: plan.id,
    sessionId,
    createdAt: nowIso(),
    traceId: plan.traceId,
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
    traceId: snapshot.traceId,
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
  traceId?: string
  intentType: string
  intentLabel: string
  matchedSkills: string[]
  isBackground: boolean
  memoryScope: string[]
}

type PythonInitiativeEvent = {
  id: string
  traceId?: string
  kind: string
  title: string
  message: string
  shadow?: boolean
  delivered?: boolean
  decisionTrace?: Record<string, unknown>
}

type PythonRuntimeContextEvent = {
  id?: string
  traceId?: string
  task: string
  phase: string
  userIntent: string
  lastResult?: string
  expectedNext: string
  matchedSkills?: string[]
}

type PythonFailureHintEvent = {
  id?: string
  traceId?: string
  keyword: string
  stage: string
  recoverable?: boolean
  detail?: string
}

export type PythonStreamPayload = {
  toolEvent?: PythonToolEvent
  planEvent?: PythonPlanEvent
  orchestrationEvent?: PythonOrchestrationEvent
  statusEvent?: PythonStatusEvent
  initiativeEvent?: PythonInitiativeEvent
  runtimeContextEvent?: PythonRuntimeContextEvent
  failureHintEvent?: PythonFailureHintEvent
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
    traceId: snapshot.traceId,
    intentType: snapshot.intentType,
    intentLabel: snapshot.intentLabel,
    matchedSkills: snapshot.matchedSkills ?? [],
    isBackground: snapshot.isBackground ?? false,
    memoryScope: snapshot.memoryScope ?? [],
  }
}

export function pythonInitiativeToAgentEvent(
  sessionId: string,
  snapshot: PythonInitiativeEvent,
): AgentEvent {
  return {
    type: 'initiative.event',
    id: snapshot.id,
    sessionId,
    createdAt: nowIso(),
    traceId: snapshot.traceId,
    kind: snapshot.kind,
    title: snapshot.title,
    message: snapshot.message,
    shadow: snapshot.shadow ?? true,
    delivered: snapshot.delivered ?? false,
    decisionTrace: snapshot.decisionTrace ?? {},
  }
}

export function pythonRuntimeContextToAgentEvent(
  sessionId: string,
  snapshot: PythonRuntimeContextEvent,
): AgentEvent {
  return {
    type: 'runtime.context',
    id: snapshot.id || `runtime-context-${crypto.randomUUID().slice(0, 8)}`,
    sessionId,
    createdAt: nowIso(),
    traceId: snapshot.traceId,
    task: snapshot.task,
    phase: snapshot.phase,
    userIntent: snapshot.userIntent,
    lastResult: snapshot.lastResult || '',
    expectedNext: snapshot.expectedNext,
    matchedSkills: snapshot.matchedSkills ?? [],
  }
}

export function pythonFailureHintToAgentEvent(
  sessionId: string,
  snapshot: PythonFailureHintEvent,
): AgentEvent {
  return {
    type: 'failure.hint',
    id: snapshot.id || `failure-hint-${crypto.randomUUID().slice(0, 8)}`,
    sessionId,
    createdAt: nowIso(),
    traceId: snapshot.traceId,
    keyword: snapshot.keyword,
    stage: snapshot.stage,
    recoverable: snapshot.recoverable ?? true,
    detail: snapshot.detail || '',
  }
}

export function pythonStreamPayloadToAgentEvents(
  sessionId: string,
  payload: PythonStreamPayload,
): AgentEvent[] {
  const events: AgentEvent[] = []
  if (payload.runtimeContextEvent) {
    events.push(pythonRuntimeContextToAgentEvent(sessionId, payload.runtimeContextEvent))
  }
  if (payload.toolEvent) {
    events.push(pythonToolEventToAgentEvent(sessionId, payload.toolEvent))
  }
  if (payload.orchestrationEvent) {
    events.push(pythonOrchestrationToAgentEvent(sessionId, payload.orchestrationEvent))
  }
  if (payload.statusEvent) {
    events.push(pythonStatusToAgentEvent(sessionId, payload.statusEvent))
  }
  if (payload.planEvent) {
    events.push(pythonPlanToAgentEvent(sessionId, payload.planEvent))
  }
  if (payload.initiativeEvent) {
    events.push(pythonInitiativeToAgentEvent(sessionId, payload.initiativeEvent))
  }
  if (payload.failureHintEvent) {
    events.push(pythonFailureHintToAgentEvent(sessionId, payload.failureHintEvent))
  }
  return events
}
