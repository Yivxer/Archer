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
