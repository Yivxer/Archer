export type Route = 'Chat' | 'Today' | 'Sessions' | 'Tasks' | 'Memory' | 'Soul' | 'Skills' | 'Projects' | 'Settings'
export type Theme = 'light' | 'dark'
export type MemoryContextMode = 'off' | 'conservative' | 'full'
export type ObsidianContextMode = 'off' | 'summary' | 'full'
export type ConversationMode = string
export type ApiConnectionState = 'idle' | 'loading' | 'connected' | 'api_offline' | 'missing_token' | 'bad_token' | 'error'
export type MemoryStatus = 'confirmed' | 'pending' | 'rejected'
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'

export type WorkIntent = {
  workflowName?: string
  action?: string
  targets?: Array<{ label?: string; path?: string; url?: string }>
  steps?: string[]
  verifyPlan?: string
  rollbackPlan?: string
}

export type WorkReceipt = {
  done: string
  source: string
  target: string
  verification: string
  rollback: string
  traceId?: string
}

export type TokenUsageStatus = {
  sessionTotal: number
  sessionPrompt: number
  sessionCompletion: number
  callCount: number
  lastCallTotal: number
  lastCallPrompt: number
  lastCallCompletion: number
  limit: number
  percentUsed: number
}

export type ArcherStatus = {
  adapter: 'mock' | 'local'
  model: string
  modelProfile?: 'lite' | 'pro' | 'max'
  expertId?: string
  expertLabel?: string
  mode: string
  memoryCount: number
  pendingMemoryCount?: number
  skillCount: number
  accountName?: string
  isLoggedIn?: boolean
  archerId?: string
  tokenUsage?: TokenUsageStatus
}

export type ChatMessage = {
  id: number
  role: 'assistant' | 'user' | 'system'
  text: string
  detail?: string
  fileRefs?: FileRef[]
  /** 等待首 token 时的短暂承接语，不写入会话存档 */
  mutter?: string
}

export type ChatRequestMessage = {
  role: 'assistant' | 'user' | 'system'
  content: string
}

export type FileRef = {
  path: string
  name: string
  size?: number
  previewDataUrl?: string
  attachStatus?: 'ready' | 'reading' | 'ok' | 'failed'
  attachDetail?: string
  content?: string
  contentChars?: number
  truncated?: boolean
}

export type ToolProgress = {
  name: string
  state: 'ready' | 'mock' | 'next'
  active?: boolean
}

export type ToolEvent = {
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
    // obsidian_write draft
    path?: string
    mode?: string
    contentPreview?: string
    // shell.execute draft
    command?: string
    timeout?: number
    // github draft
    action?: string
    repo?: string
    title?: string
    body?: string
    size?: number
    injectedChars?: number
    truncated?: boolean
    // obsidian_write diff preview
    beforeText?: string
    afterText?: string
    previewMode?: string
    previewExists?: boolean
    workIntent?: WorkIntent
    sourcePath?: string
    targetUrl?: string
  }
  receipt?: WorkReceipt
}

export type SessionItem = {
  id: string
  title: string
  date: string
  turns: number
  tone: string
  preview?: string
  threadId?: string
  expertId?: string
  expertLabel?: string
}

export type SessionDetail = SessionItem & {
  messages: ChatMessage[]
}

export type SessionSearchResult = SessionItem & {
  snippet: string
  matchRole: string
}

export type SavedSession = {
  id: string
  path: string
  messages: number
  appended?: number
  threadId?: string
}

export type ConversationThread = {
  id: string
  title: string
  summary: string
  createdAt: string
  updatedAt: string
  sessionIds: string[]
  projectId?: string
  archived?: boolean
}

export type MemoryResolveResult = {
  ok: boolean
  id: number
  accepted: boolean
  writtenIds?: number[]
  deleted?: number
}

export type SoulImportResult = {
  ok: boolean
  imported: number
  pendingIds: number[]
  message: string
}

export type ToolApprovalResult = {
  ok: boolean
  eventId: string
  decision: 'approved' | 'denied'
  executed: boolean
  message: string
  validatedPath?: string
  output?: string
  draft?: ToolEvent['draft']
  receipt?: WorkReceipt
  workReceipt?: WorkReceipt
}

export type BackgroundJobStatus = 'queued' | 'running' | 'waiting_approval' | 'complete' | 'failed' | 'cancelled'

export type BackgroundJob = {
  id: string
  title: string
  kind: string
  prompt: string
  status: BackgroundJobStatus
  result: string
  createdAt: string
  updatedAt: string
  timeoutSeconds?: number
  error?: string
  stale?: boolean
  /** Isolated subagent context (P5.4) */
  isolated?: boolean
  /** Pending tool approval context when status is 'waiting_approval' */
  pendingTool?: BackgroundJobPendingTool
  /** Parent job ID when this is a child/sub-agent job */
  parentJobId?: string
  /** Child job IDs when this job has spawned sub-agents */
  childJobIds?: string[]
  /** Child job summaries (returned by GET /jobs/{id}) */
  children?: BackgroundJobChildSummary[]
}

export type BackgroundJobPendingTool = {
  eventId: string
  toolName: string
  displayName: string
  risk: RiskLevel
  summary: string
  detail: string
  draft?: Record<string, unknown>
  createdAt: string
}

export type BackgroundJobChildSummary = {
  id: string
  title: string
  status: BackgroundJobStatus
  createdAt: string
  parentJobId?: string
  isolated?: boolean
  result?: string
  error?: string
}

export type BackgroundJobCreateResult = {
  ok: boolean
  job: BackgroundJob
}

export type BackgroundJobListResult = {
  ok: boolean
  jobs: BackgroundJob[]
}

export type BackgroundJobActionResult = {
  ok: boolean
  job: BackgroundJob
  message: string
  error?: string
}

export type MemoryBlockType = 'human' | 'persona' | 'preference' | 'decision' | 'event' | 'insight'

export type MemoryItem = {
  id: number
  status: MemoryStatus
  type: string
  content: string
  confidence: string
  source: string
  sessionId?: string
  suggestReason?: string
  sessionSummary?: string
  depth?: number
  blockType?: MemoryBlockType
  label?: string
}

export type MemoryStats = {
  dbPath: string
  activeCount: number
  pendingCount: number
  rejectedCount: number
  groups: Record<string, number>
  contradictions: number
  stale: number
}

export type MemoryGroup = {
  label: string
  icon: string
  types: string[]
  question: string
  count: number
  memories: MemoryItem[]
}

export type HypothesisEvidence = {
  content: string
  source: string
  createdAt: string
}

export type HypothesisStatus = 'active' | 'verified' | 'rejected' | 'dismissed'

export type HypothesisItem = {
  id: number
  title: string
  statement: string
  status: HypothesisStatus
  source: string
  triggerType: string
  confidence: number
  evidence: HypothesisEvidence[]
  validateAfter: string
  createdAt: string
  updatedAt: string
  lastReviewedAt?: string
  verifiedAt?: string
  sessionId?: string
  verificationNote?: string
  mutedUntil?: string
}

export type HypothesisListResult = {
  ok: boolean
  hypotheses: HypothesisItem[]
}

export type SkillItem = {
  name: string
  description: string
  risk: RiskLevel
  enabled: boolean
  permissionLevel?: 'read-only' | 'write-local' | 'write-vault' | 'deploy-remote' | 'unknown'
}

export type ModeItem = {
  id: string
  label: string
  source: 'file' | 'toml'
  active: boolean
}

export type ModeSettings = {
  current: string
  default: string
  modes: ModeItem[]
}

export type ModeSwitchResult = {
  ok: boolean
  current: string
  label: string
  modes: ModeItem[]
}

export type ExpertStarter = {
  label: string
  prompt: string
}

export type ExpertItem = {
  id: string
  label: string
  note: string
  modelProfile: 'lite' | 'pro' | 'max'
  skillCount: number
  configured: boolean
  modelConfigured?: boolean
  starters?: ExpertStarter[]
  source?: string
  custom?: boolean
}

export type ExpertSettings = {
  current: string
  experts: ExpertItem[]
}

export type ExpertSwitchResult = {
  ok: boolean
  current: string
  label: string
  modelProfile: 'lite' | 'pro' | 'max'
  previous?: string
  error?: string
}

export type ProactiveTouchItem = {
  id: string
  kind: string
  severity: 'low' | 'medium' | 'high'
  title: string
  detail: string
  action: string
  target: Route
}

export type ProactiveTouch = {
  enabled: boolean
  items: ProactiveTouchItem[]
}

export type InitiativeShadowItem = {
  id: number
  eventType: string
  kind: string
  title: string
  message: string
  delivered: boolean
  decisionTrace: Record<string, unknown>
  createdAt: string
  feedback: string
  archivedAt: string | null
}

export type InitiativeShadowReview = {
  ok: boolean
  shadow: boolean
  delivered: boolean
  limit: number
  globalThrottleActive: boolean
  presenceState: 'engaged' | 'idle' | 'muted'
  items: InitiativeShadowItem[]
  report: InitiativeShadowReport
  longTermReport: InitiativeShadowLongTermReport
  deliveryGate: InitiativeShadowDeliveryGate
  optIn: InitiativeShadowOptIn
  reviewPacket: InitiativeShadowReviewPacket
}

export type InitiativeShadowReport = {
  observationDays: number
  totalCandidates: number
  dailyAverage: number
  feedbackCount: number
  recognitionRate: number
  readyForManualReview: boolean
  reasons: string[]
  thresholds: {
    requiredDays: number
    maxDailyAverage: number
    minFeedback: number
    minRecognitionRate: number
  }
}

export type InitiativeShadowLongTermReport = {
  observedDays: number
  candidateCount: number
  readyForDeliveryReview: boolean
  reasons: string[]
  metrics: {
    frequency: {
      dailyAverage: number
      maxDailyCount: number
    }
    relevance: {
      feedbackCount: number
      recognitionRate: number
      tooFrequentRate: number
    }
    continuity: {
      threadResumeCount: number
    }
  }
}

export type InitiativeShadowDeliveryGate = {
  canEnableDelivery: boolean
  shadowOnly: boolean
  reasons: string[]
  requirements: {
    requiredObservationDays: number
    explicitOptIn: boolean
    manualReview: boolean
  }
  timeline: {
    firstObservedAt: string | null
    earliestReviewAt: string | null
    remainingObservationDays: number
  }
}

export type InitiativeShadowOptIn = {
  enabled: boolean
  updatedAt: string | null
  reason: string
}

export type InitiativeShadowReviewPacket = {
  recommendedAction: string
  optIn: InitiativeShadowOptIn
  manualReport: InitiativeShadowReport
  longTermReport: InitiativeShadowLongTermReport
  deliveryGate: InitiativeShadowDeliveryGate
}

export type SoulFileName = 'SOUL.md' | 'MEMORY.md' | 'COVENANT.md' | 'PRESENCE.md'
export type SoulFiles = Record<SoulFileName, string>

export type SoulProfileSection = {
  id: string
  label: string
  items: string[]
}

export type SoulProfileSummary = {
  empty: boolean
  sections: SoulProfileSection[]
}

export type VaultReflection = {
  id: number
  note_path: string
  note_title: string
  reflected_at: string
  insights_count: number
  pending_ids: number[]
  soul_proposal_id: number | null
  confidence: number
  summary: string
}

export type VaultReflectionResult = {
  ok: boolean
  note_path?: string
  note_title?: string
  pending_ids?: number[]
  soul_proposal_id?: number | null
  confidence?: number
  summary?: string
  reflected?: VaultReflectionResult[]
  skipped?: { note_path: string; reason: string }[]
  total?: number
  reason?: string
  skipped_flag?: boolean
  error?: string
}

export type ReviewPeriod = 'weekly' | 'monthly' | 'life_stage'

export type PeriodReview = {
  period: ReviewPeriod
  title: string
  window: {
    days: number
    start: string
    end: string
  }
  metrics: {
    sessions: number
    user_turns: number
    memories: number
    deep_memories: number
  }
  themes: { type: string; count: number }[]
  highlights: string[]
  growth_markers: string[]
  suggested_questions: string[]
  markdown: string
}

export type JournalReview = {
  configured: boolean
  window: {
    days: number
    start: string
    end: string
  }
  metrics: {
    entries: number
    characters: number
  }
  entries: {
    path: string
    date: string
    characters: number
    preview: string
  }[]
  journal_emotions: Record<string, number>
  session_emotions: Record<string, { date: string; avg_score: number }[]>
  markdown: string
}

export type SettingsDraft = {
  activeProfile: 'lite' | 'pro' | 'max'
  activeExpert?: string
  experts?: ExpertItem[]
  modelProfiles?: Array<{
    id: 'lite' | 'pro' | 'max'
    label: string
    provider: string
    baseUrl?: string
    model?: string
    apiKeyPreview?: string
    configured: boolean
  }>
  provider: string
  baseUrl: string
  model: string
  apiKey?: string
  apiKeyPreview: string
  configPath: string
  memoryDbPath: string
  sessionsPath: string
}

export type SettingsValidationResult = {
  ok: boolean
  dryRun: boolean
  writable: boolean
  allowedFields: string[]
  blockedFields: string[]
  errors: string[]
  message: string
}

export type SettingsSaveResult = {
  ok: boolean
  savedFields: string[]
  restartRequired: boolean
  errors?: string[]
  message: string
}

export type ModelProfileTestResult = {
  ok: boolean
  profile: string
  provider: string
  model: string
  baseUrl: string
  latencyMs: number
  message: string
  sample?: string
  errors: string[]
}

export type ScheduledTask = {
  id: number
  skillName: string
  label: string
  intervalHours: number
  intervalLabel: string
  enabled: boolean
  catchup: 'latest' | 'skip'
  args: Record<string, unknown>
  lastRunAt: string | null
  nextRunAt: string
  createdAt: string
}

export type ScheduleListResult = {
  ok: boolean
  jsonPath?: string
  tasks: ScheduledTask[]
}

export type ScheduleMutationResult = {
  ok: boolean
  task?: ScheduledTask
  id?: number
  summary?: string
  preview?: string
  error?: string
}

export type ConfigDoctorResult = {
  ok: boolean
  checkedAt: string
  configPath: string
  summary: {
    error: number
    warn: number
    info: number
  }
  issues: Array<{
    code: string
    level: 'ok' | 'info' | 'warn' | 'error'
    message: string
    nextAction: string
  }>
  nextActions: string[]
}

export type ToolApprovalAuditRecord = {
  timestamp: number
  eventId: string
  decision: string
  skillName: string
  risk: string
  permissionLevel?: 'read-only' | 'write-local' | 'write-vault' | 'deploy-remote'
  policyDecision: string
  policyReason: string
  executed: boolean
  message: string
  reused: boolean
}

export type ToolApprovalAuditResult = {
  ok: boolean
  path: string
  limit: number
  items: ToolApprovalAuditRecord[]
}

export type ArcherAdapter = {
  status: ArcherStatus
  chat: {
    initialMessages: ChatMessage[]
    toolProgress: ToolProgress[]
    toolEvents: ToolEvent[]
    mockReply: string
  }
  sessions: SessionItem[]
  threads: ConversationThread[]
  memory: MemoryItem[]
  hypotheses: HypothesisItem[]
  skills: SkillItem[]
  modes: ModeSettings
  experts: ExpertSettings
  proactive: ProactiveTouch
  initiativeShadow: InitiativeShadowReview
  soulProfile: SoulProfileSummary
  soulFiles: SoulFiles
  periodReviews: Record<ReviewPeriod, PeriodReview>
  journalReview: JournalReview
  settings: SettingsDraft
  configDoctor: ConfigDoctorResult
  toolApprovalAudit: ToolApprovalAuditResult
}
