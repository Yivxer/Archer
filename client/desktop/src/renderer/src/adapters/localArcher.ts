import type {
  ArcherAdapter,
  BackgroundJob,
  BackgroundJobActionResult,
  BackgroundJobCreateResult,
  BackgroundJobListResult,
  ChatRequestMessage,
  FileRef,
  MemoryContextMode,
  MemoryGroup,
  MemoryStats,
  ModeSwitchResult,
  MemoryResolveResult,
  ObsidianContextMode,
  SavedSession,
  SessionDetail,
  SettingsDraft,
  SettingsSaveResult,
  SettingsValidationResult,
  SoulImportResult,
  ReviewPeriod,
  ToolApprovalResult,
  ToolEvent
} from '../types'
import { jobSnapshotToAgentEvent, pythonApprovalToAgentEvent, pythonToolEventToAgentEvent } from '../../../agent'
import type { AgentEvent } from '../../../agent'

const BASE_URL = 'http://127.0.0.1:8765'
const TOKEN_STORAGE_KEY = 'archer-desktop-api-token'

export type ApiError = {
  type: 'network' | 'server' | 'validation' | 'not_found' | 'unauthorized' | 'missing_token' | 'unknown'
  message: string
  status?: number
}

export function getDesktopApiToken(): string {
  return localStorage.getItem(TOKEN_STORAGE_KEY) || ''
}

export async function resolveDesktopApiToken(): Promise<string> {
  const saved = getDesktopApiToken()
  if (saved) return saved
  const token = await window.archerDesktop?.getApiToken?.()
  if (token) {
    saveDesktopApiToken(token)
    return token
  }
  return ''
}

export function saveDesktopApiToken(token: string): void {
  const clean = token.trim()
  if (clean) localStorage.setItem(TOKEN_STORAGE_KEY, clean)
  else localStorage.removeItem(TOKEN_STORAGE_KEY)
}

export function clearDesktopApiToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY)
}

function parseError(response: Response, body?: unknown): ApiError {
  const status = response.status
  if (!response.ok) {
    // 尝试解析错误体
    if (body && typeof body === 'object' && 'message' in body) {
      const errorBody = body as { error?: string; message?: string }
      const message = errorBody.message || errorBody.error || 'Unknown error'
      if (status === 400) return { type: 'validation', message, status }
      if (status === 401) return { type: 'unauthorized', message, status }
      if (status === 404) return { type: 'not_found', message, status }
      return { type: 'server', message, status }
    }
    if (status === 401) return { type: 'unauthorized', message: 'desktop API token is required', status }
    return { type: 'network', message: `HTTP ${status}`, status }
  }
  return { type: 'unknown', message: 'Unknown error', status }
}

async function refreshTokenFromMainProcess(): Promise<string | null> {
  try {
    const freshToken = await window.archerDesktop?.getApiToken?.()
    if (freshToken && freshToken !== getDesktopApiToken()) {
      saveDesktopApiToken(freshToken)
      return freshToken
    }
    return null
  } catch {
    return null
  }
}

async function apiFetch(path: string, init: RequestInit = {}, auth = true): Promise<Response> {
  const headers = new Headers(init.headers)
  if (auth) {
    const token = await resolveDesktopApiToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }
  try {
    const response = await fetch(`${BASE_URL}${path}`, { ...init, headers })

    // Token mismatch auto-recovery: if 401, try re-fetching token from Electron main process
    if (auth && response.status === 401) {
      const freshToken = await refreshTokenFromMainProcess()
      if (freshToken) {
        headers.set('Authorization', `Bearer ${freshToken}`)
        return fetch(`${BASE_URL}${path}`, { ...init, headers })
      }
    }

    return response
  } catch (error) {
    throw new Error(error instanceof Error ? `[network] ${error.message}` : '[network] Local API is unreachable')
  }
}

export async function checkLocalApiHealth(): Promise<boolean> {
  const response = await apiFetch('/health', {}, false)
  return response.ok
}

async function getJson<T>(path: string): Promise<T> {
  const response = await apiFetch(path)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const error = parseError(response, body)
    throw new Error(`[${error.type}] ${error.message}`)
  }
  return response.json() as Promise<T>
}

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const error = parseError(response, body)
    throw new Error(`[${error.type}] ${error.message}`)
  }
  return response.json() as Promise<T>
}

export async function loadLocalArcher(): Promise<ArcherAdapter> {
  const reviewPeriods: ReviewPeriod[] = ['weekly', 'monthly', 'life_stage']
  const [status, sessions, memory, skills, modes, proactive, soulProfile, soulFiles, periodReviewsList, journalReview, settings] = await Promise.all([
    getJson<ArcherAdapter['status']>('/status'),
    getJson<ArcherAdapter['sessions']>('/sessions'),
    getJson<ArcherAdapter['memory']>('/memory?include_rejected=true'),
    getJson<ArcherAdapter['skills']>('/skills'),
    getJson<ArcherAdapter['modes']>('/modes'),
    getJson<ArcherAdapter['proactive']>('/proactive-touch'),
    getJson<ArcherAdapter['soulProfile']>('/soul-profile'),
    getJson<ArcherAdapter['soulFiles']>('/soul-files'),
    Promise.all(reviewPeriods.map((period) => getJson<ArcherAdapter['periodReviews'][ReviewPeriod]>(`/reviews?period=${period}`))),
    getJson<ArcherAdapter['journalReview']>('/journal-review?days=30'),
    getJson<ArcherAdapter['settings']>('/settings')
  ])
  const periodReviews = Object.fromEntries(
    reviewPeriods.map((period, index) => [period, periodReviewsList[index]])
  ) as ArcherAdapter['periodReviews']

  return {
    status,
    chat: {
      initialMessages: [],
      toolProgress: [
        { name: 'GET /status', state: 'ready', active: true },
        { name: 'GET /memory', state: 'ready' },
        { name: 'POST /chat/stream', state: 'ready' }
      ],
      toolEvents: [
        {
          id: 'local-status',
          name: 'status.load',
          status: 'complete',
          risk: 'low',
          summary: '读取本地 Archer 状态、模型和计数',
          detail: 'source: GET /status'
        },
        {
          id: 'local-session-save',
          name: 'session.save',
          status: 'complete',
          risk: 'low',
          summary: '聊天完成后写入本地 Sessions',
          detail: 'target: memory/sessions/*.json'
        },
        {
          id: 'local-tool-approval',
          name: 'tool.approval',
          status: 'waiting',
          risk: 'high',
          summary: '未来真实工具调用前在这里确认',
          detail: 'allow / deny / inspect arguments',
          requiresApproval: true
        }
      ],
      mockReply: '本地 API 已连接。当前聊天会走纯模型回复，还没有工具调用。'
    },
    sessions,
    memory,
    skills,
    modes,
    proactive,
    soulProfile,
    soulFiles,
    periodReviews,
    journalReview,
    settings
  }
}

export async function loadLocalSession(sessionId: string): Promise<SessionDetail> {
  return getJson<SessionDetail>(`/sessions/${encodeURIComponent(sessionId)}`)
}

export async function sendLocalChat(messages: ChatRequestMessage[]): Promise<string> {
  const response = await postJson<{ role: 'assistant'; text: string }>('/chat', { messages })
  return response.text
}

export async function saveLocalSession(messages: ChatRequestMessage[]): Promise<SavedSession> {
  return postJson<SavedSession>('/sessions', { messages })
}

export async function appendLocalSession(sessionId: string, messages: ChatRequestMessage[]): Promise<SavedSession> {
  return postJson<SavedSession>(`/sessions/${encodeURIComponent(sessionId)}/append`, { messages })
}

export async function resolvePendingMemory(id: number, accepted: boolean): Promise<MemoryResolveResult> {
  return postJson<MemoryResolveResult>(`/memory/pending/${id}/${accepted ? 'accept' : 'reject'}`, {})
}

export async function batchResolvePendingMemory(accepted: boolean): Promise<{ ok: boolean; count?: number; deleted?: number }> {
  return postJson(`/memory/pending/batch/${accepted ? 'accept' : 'reject'}`, {})
}

export async function importSoul(soulData: Record<string, unknown>): Promise<SoulImportResult> {
  return postJson<SoulImportResult>('/soul/import', { soulData })
}

export async function fetchMemoryStats(): Promise<MemoryStats> {
  return getJson<MemoryStats>('/memory/stats')
}

export async function fetchMemoryGroups(): Promise<Record<string, MemoryGroup>> {
  return getJson<Record<string, MemoryGroup>>('/memory/groups')
}

export async function updateMemory(id: number, content: string): Promise<{ ok: boolean; id: number }> {
  return postJson('/memory/update', { id, content })
}

export async function evolveMemory(id: number, content: string, type?: string, importance?: number, depth?: number): Promise<{ ok: boolean; id: number }> {
  return postJson('/memory/evolve', { id, content, type, importance, depth })
}

export async function toggleSkill(name: string, enabled: boolean): Promise<{ ok: boolean; name: string; enabled: boolean }> {
  return postJson('/skills/toggle', { name, enabled })
}

export async function switchLocalMode(mode: string): Promise<ModeSwitchResult> {
  return postJson<ModeSwitchResult>('/modes/current', { mode })
}

export async function validateLocalSettings(settings: SettingsDraft): Promise<SettingsValidationResult> {
  return postJson<SettingsValidationResult>('/settings/validate', { settings })
}

export async function saveLocalSettings(settings: SettingsDraft): Promise<SettingsSaveResult> {
  return postJson<SettingsSaveResult>('/settings/save', { settings })
}

export async function createBackgroundJob(payload: {
  title: string
  kind?: string
  prompt: string
  autoStart?: boolean
  timeoutSeconds?: number
}): Promise<BackgroundJobCreateResult> {
  return postJson<BackgroundJobCreateResult>('/jobs', payload)
}

export async function createBackgroundJobEvent(
  sessionId: string,
  payload: {
    title: string
    kind?: string
    prompt: string
    autoStart?: boolean
    timeoutSeconds?: number
  }
): Promise<{ result: BackgroundJobCreateResult; event: AgentEvent }> {
  const result = await createBackgroundJob(payload)
  return {
    result,
    event: jobSnapshotToAgentEvent(sessionId, result.job),
  }
}

export async function listBackgroundJobs(): Promise<BackgroundJobListResult> {
  return getJson<BackgroundJobListResult>('/jobs')
}

export async function fetchBackgroundJob(jobId: string): Promise<BackgroundJob> {
  const result = await getJson<BackgroundJobCreateResult>(`/jobs/${encodeURIComponent(jobId)}`)
  return result.job
}

export async function cancelBackgroundJob(jobId: string): Promise<BackgroundJobActionResult> {
  return postJson<BackgroundJobActionResult>(`/jobs/${encodeURIComponent(jobId)}/cancel`, {})
}

export async function retryBackgroundJob(jobId: string): Promise<BackgroundJobActionResult> {
  return postJson<BackgroundJobActionResult>(`/jobs/${encodeURIComponent(jobId)}/retry`, {})
}

export async function approveJobTool(
  jobId: string,
  eventId: string,
  decision: 'approved' | 'denied'
): Promise<BackgroundJobActionResult> {
  return postJson<BackgroundJobActionResult>(`/jobs/${encodeURIComponent(jobId)}/approve`, { eventId, decision })
}

export type SpawnChildSpec = {
  title: string
  kind?: string
  prompt: string
  autoStart?: boolean
  timeoutSeconds?: number
}

export type SpawnChildrenResult = {
  ok: boolean
  id: string
  spawned: number
  children: BackgroundJob[]
}

export async function spawnChildJobs(
  jobId: string,
  children: SpawnChildSpec[]
): Promise<SpawnChildrenResult> {
  return postJson<SpawnChildrenResult>(`/jobs/${encodeURIComponent(jobId)}/spawn`, { children })
}

export async function approveJobToolEvent(
  sessionId: string,
  jobId: string,
  eventId: string,
  decision: 'approved' | 'denied'
): Promise<{ result: BackgroundJobActionResult; event: AgentEvent }> {
  const result = await approveJobTool(jobId, eventId, decision)
  return {
    result,
    event: jobSnapshotToAgentEvent(sessionId, result.job),
  }
}

export async function cancelBackgroundJobEvent(
  sessionId: string,
  jobId: string
): Promise<{ result: BackgroundJobActionResult; event: AgentEvent }> {
  const result = await cancelBackgroundJob(jobId)
  return {
    result,
    event: jobSnapshotToAgentEvent(sessionId, result.job),
  }
}

export async function retryBackgroundJobEvent(
  sessionId: string,
  jobId: string
): Promise<{ result: BackgroundJobActionResult; event: AgentEvent }> {
  const result = await retryBackgroundJob(jobId)
  return {
    result,
    event: jobSnapshotToAgentEvent(sessionId, result.job),
  }
}

export async function fetchBackgroundJobEvent(
  sessionId: string,
  jobId: string
): Promise<{ job: BackgroundJob; event: AgentEvent }> {
  const job = await fetchBackgroundJob(jobId)
  return {
    job,
    event: jobSnapshotToAgentEvent(sessionId, job),
  }
}

export async function pollBackgroundJobEvents(
  sessionId: string,
  jobId: string,
  onAgentEvent: (event: AgentEvent) => void,
  options: {
    intervalMs?: number
    maxAttempts?: number
    signal?: AbortSignal
  } = {}
): Promise<BackgroundJob> {
  const intervalMs = options.intervalMs ?? 1200
  const maxAttempts = options.maxAttempts ?? 120
  let lastEventId = ''
  let latestJob: BackgroundJob | undefined

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (options.signal?.aborted) {
      throw new DOMException('Background job polling was aborted', 'AbortError')
    }
    const { job, event } = await fetchBackgroundJobEvent(sessionId, jobId)
    latestJob = job
    if (event.id !== lastEventId) {
      onAgentEvent(event)
      lastEventId = event.id
    }
    if (job.status === 'complete' || job.status === 'failed' || job.status === 'cancelled') {
      return job
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs))
  }

  if (latestJob) return latestJob
  throw new Error('[job] background job polling ended before receiving a job snapshot')
}

export async function submitToolApproval(
  eventId: string,
  decision: 'approved' | 'denied'
): Promise<ToolApprovalResult> {
  return postJson<ToolApprovalResult>('/tool-approvals', { eventId, decision })
}

export async function submitToolApprovalEvent(
  sessionId: string,
  eventId: string,
  decision: 'approved' | 'denied'
): Promise<{ result: ToolApprovalResult; event: AgentEvent }> {
  const result = await submitToolApproval(eventId, decision)
  return {
    result,
    event: pythonApprovalToAgentEvent(sessionId, result),
  }
}

export async function streamLocalChat(
  messages: ChatRequestMessage[],
  memoryMode: MemoryContextMode,
  obsidianMode: ObsidianContextMode,
  fileRefs: FileRef[],
  onText: (text: string) => void,
  onToolEvent?: (event: ToolEvent) => void,
  onAgentEvent?: (event: AgentEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const response = await apiFetch('/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, memoryMode, obsidianMode, fileRefs }),
    signal
  })
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}))
    const error = parseError(response, body)
    throw new Error(`[${error.type}] ${error.message}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const line = frame
        .split('\n')
        .find((part) => part.startsWith('data: '))
      if (!line) continue
      const payload = JSON.parse(line.slice(6)) as {
        text?: string
        done?: boolean
        error?: string
        toolEvent?: ToolEvent
      }
      if (payload.error) throw new Error(`[server] ${payload.error}`)
      if (payload.toolEvent) {
        onToolEvent?.(payload.toolEvent)
        onAgentEvent?.(pythonToolEventToAgentEvent('desktop-session', payload.toolEvent))
      }
      if (payload.text) onText(payload.text)
      if (payload.done) return
    }
  }
}
