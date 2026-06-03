export type Route = 'Chat' | 'Sessions' | 'Tasks' | 'Memory' | 'Soul' | 'Skills' | 'Settings'
export type Theme = 'light' | 'dark'
export type MemoryContextMode = 'off' | 'conservative' | 'full'
export type ObsidianContextMode = 'off' | 'summary' | 'full'
export type ConversationMode = string
export type ApiConnectionState = 'idle' | 'loading' | 'connected' | 'api_offline' | 'missing_token' | 'bad_token' | 'error'
export type MemoryStatus = 'confirmed' | 'pending' | 'rejected'
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'

export type ArcherStatus = {
  adapter: 'mock' | 'local'
  model: string
  mode: string
  memoryCount: number
  pendingMemoryCount?: number
  skillCount: number
  accountName?: string
  isLoggedIn?: boolean
  archerId?: string
}

export type ChatMessage = {
  id: number
  role: 'assistant' | 'user' | 'system'
  text: string
}

export type ChatRequestMessage = {
  role: 'assistant' | 'user' | 'system'
  content: string
}

export type FileRef = {
  path: string
  name: string
  size?: number
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
  }
}

export type SessionItem = {
  id: string
  title: string
  date: string
  turns: number
  tone: string
  preview?: string
}

export type SessionDetail = SessionItem & {
  messages: ChatMessage[]
}

export type SavedSession = {
  id: string
  path: string
  messages: number
  appended?: number
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

export type MemoryItem = {
  id: number
  status: MemoryStatus
  type: string
  content: string
  confidence: string
  source: string
  depth?: number
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

export type SkillItem = {
  name: string
  description: string
  risk: RiskLevel
  enabled: boolean
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
  provider: string
  baseUrl: string
  model: string
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

export type ArcherAdapter = {
  status: ArcherStatus
  chat: {
    initialMessages: ChatMessage[]
    toolProgress: ToolProgress[]
    toolEvents: ToolEvent[]
    mockReply: string
  }
  sessions: SessionItem[]
  memory: MemoryItem[]
  skills: SkillItem[]
  modes: ModeSettings
  proactive: ProactiveTouch
  soulProfile: SoulProfileSummary
  soulFiles: SoulFiles
  periodReviews: Record<ReviewPeriod, PeriodReview>
  journalReview: JournalReview
  settings: SettingsDraft
}
