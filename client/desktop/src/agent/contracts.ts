export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type PermissionLevel = 'read-only' | 'write-local' | 'write-vault' | 'deploy-remote'
export type ToolStatus = 'running' | 'waiting_approval' | 'complete' | 'blocked' | 'denied'
export type ApprovalDecision = 'approved' | 'denied'
export type JobStatus = 'queued' | 'running' | 'waiting_approval' | 'complete' | 'failed' | 'cancelled'

export type WorkReceipt = {
  done: string
  source: string
  target: string
  verification: string
  rollback: string
  traceId?: string
}

export type AgentEventBase = {
  id: string
  sessionId: string
  createdAt: string
  traceId?: string
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
  permissionLevel?: PermissionLevel
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
  permissionLevel?: PermissionLevel
  receipt?: WorkReceipt
}

export type ApprovalResultEvent = AgentEventBase & {
  type: 'approval.result'
  requestId: string
  decision: ApprovalDecision
  permissionLevel?: PermissionLevel
  executed: boolean
  ok: boolean
  output: string
  message: string
  receipt?: WorkReceipt
}

export type JobEvent = AgentEventBase & {
  type: 'job.event'
  jobId: string
  title: string
  status: JobStatus
  detail: string
  stale?: boolean
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

export type TaskRouteSnapshot = {
  mode: 'foreground' | 'background'
  reason: string
  title: string
  timeoutSeconds: number
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
  taskRoute: TaskRouteSnapshot
}

export type StatusEvent = AgentEventBase & {
  type: 'status.event'
  intentType: string
  intentLabel: string
  matchedSkills: string[]
  isBackground: boolean
  memoryScope: string[]
  phase?: 'retry' | 'fallback'
  attempt?: number
  maxAttempts?: number
  fallbackProfile?: string
}

export type InitiativeEvent = AgentEventBase & {
  type: 'initiative.event'
  kind: string
  title: string
  message: string
  shadow: boolean
  delivered: boolean
  decisionTrace: Record<string, unknown>
}

export type RuntimeContextEvent = AgentEventBase & {
  type: 'runtime.context'
  task: string
  phase: string
  userIntent: string
  lastResult: string
  expectedNext: string
  matchedSkills?: string[]
  contextReceipt?: {
    sources: {
      persona: boolean
      working: boolean
      episodic: boolean
      semantic: boolean
    }
    workingMessageCount: number
    summaryVersion: number
    degraded: boolean
    retrieval: {
      triggered: boolean
      reason: string
      hitCount: number
      injectedCount: number
      degraded?: boolean
    }
  }
  provider?: string
  model?: string
  baseUrlSummary?: string
  outcome?: 'complete' | 'failed'
  ttftMs?: number
  totalDurationMs?: number
  contextBuildMs?: number
  toolDurationMs?: number
  cpuTimeMs?: number
  peakRssBytes?: number
  tokenUsage?: {
    promptTokens?: number
    completionTokens?: number
    totalTokens?: number
    historyEstimatedTokens?: number
    tokenLimit?: number
    compressionTriggered?: boolean
  }
}

export type FailureHintEvent = AgentEventBase & {
  type: 'failure.hint'
  keyword: string
  stage: string
  recoverable: boolean
  detail: string
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
  | InitiativeEvent
  | RuntimeContextEvent
  | FailureHintEvent
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
