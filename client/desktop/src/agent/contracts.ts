export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type ToolStatus = 'running' | 'waiting_approval' | 'complete' | 'blocked' | 'denied'
export type ApprovalDecision = 'approved' | 'denied'
export type JobStatus = 'queued' | 'running' | 'waiting_approval' | 'complete' | 'failed' | 'cancelled'

export type AgentEventBase = {
  id: string
  sessionId: string
  createdAt: string
}

export type TextDeltaEvent = AgentEventBase & {
  type: 'text.delta'
  text: string
}

export type TextFinalEvent = AgentEventBase & {
  type: 'text.final'
  text: string
}

export type ToolRequestEvent = AgentEventBase & {
  type: 'tool.request'
  toolName: string
  displayName: string
  risk: RiskLevel
  status: ToolStatus
  args: Record<string, unknown>
  summary: string
  detail: string
  requiresApproval: boolean
  blocked: boolean
  /** Rich display data from Python tool event draft (command, path, title, contentPreview, etc.) */
  draft?: Record<string, unknown>
}

export type ToolResultEvent = AgentEventBase & {
  type: 'tool.result'
  requestId: string
  toolName: string
  status: Extract<ToolStatus, 'complete' | 'blocked' | 'denied'>
  ok: boolean
  output: string
  message: string
}

export type ApprovalResultEvent = AgentEventBase & {
  type: 'approval.result'
  requestId: string
  decision: ApprovalDecision
  executed: boolean
  ok: boolean
  output: string
  message: string
}

export type JobEvent = AgentEventBase & {
  type: 'job.event'
  jobId: string
  title: string
  status: JobStatus
  detail: string
  progress?: {
    done: number
    total: number
  }
}

export type PlanStatus = 'proposed' | 'accepted' | 'dismissed'

export type PlanStep = {
  id: number
  action: string
  tool: string
  requiresApproval: boolean
}

export type PlanEvent = AgentEventBase & {
  type: 'plan.event'
  title: string
  status: PlanStatus
  detail: string
  steps: PlanStep[]
  /** Original user request that produced this plan. */
  prompt?: string
}

export type OrchestrationEvent = AgentEventBase & {
  type: 'orchestration.event'
  intent: string
  subIntent: string
  mode: string
  depth: string
  labels: string[]
  needsMemory: boolean
  needsJob: boolean
}

export type StatusEvent = AgentEventBase & {
  type: 'status.event'
  intentType: string
  intentLabel: string
  matchedSkills: string[]
  isBackground: boolean
  memoryScope: string[]
}

export type ErrorEvent = AgentEventBase & {
  type: 'runtime.error'
  scope: 'stream' | 'approval' | 'job' | 'adapter'
  message: string
  recoverable: boolean
}

export type AgentEvent =
  | TextDeltaEvent
  | TextFinalEvent
  | ToolRequestEvent
  | ToolResultEvent
  | ApprovalResultEvent
  | JobEvent
  | PlanEvent
  | OrchestrationEvent
  | StatusEvent
  | ErrorEvent

export type RuntimeMessage = {
  id: string
  role: 'user' | 'assistant' | 'system'
  text: string
}

export type RuntimeSession = {
  id: string
  messages: RuntimeMessage[]
  events: AgentEvent[]
  status: 'idle' | 'streaming' | 'waiting_approval' | 'running_job' | 'error'
}
