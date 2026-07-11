import type {
  ArcherAdapter,
  BackgroundJob,
  BackgroundJobActionResult,
  BackgroundJobCreateResult,
  BackgroundJobListResult,
  ChatRequestMessage,
  ConversationThread,
  FileRef,
  MemoryContextMode,
  MemoryGroup,
  MemoryStats,
  HypothesisItem,
  HypothesisListResult,
  ModeSwitchResult,
  ExpertSettings,
  ExpertSwitchResult,
  MemoryResolveResult,
  ObsidianContextMode,
  SavedSession,
  SessionDetail,
  SessionSearchResult,
  SettingsDraft,
  ModelProfileTestResult,
  SettingsSaveResult,
  SettingsValidationResult,
  ScheduledTask,
  ScheduleListResult,
  ScheduleMutationResult,
  SoulImportResult,
  ReviewPeriod,
  ToolApprovalResult,
  ToolEvent,
  VaultReflection,
  VaultReflectionResult
} from '../types'
import { assertSupportedContractVersion, jobSnapshotToAgentEvent, pythonApprovalToAgentEvent, pythonStreamPayloadToAgentEvents } from '../../../agent'
import type { AgentEvent, PythonStreamPayload } from '../../../agent'
const BASE_URL = 'http://127.0.0.1:8765'
const TOKEN_STORAGE_KEY = 'archer-desktop-api-token'
const API_TIMEOUT_MS = 15_000

export class StreamIdleTimeoutError extends Error {
  constructor(message = '回复超时（长时间没有新输出），模型或工具可能还在等待，请稍后重试') {
    super(message)
    this.name = 'StreamIdleTimeoutError'
  }
}

export class ChatBusyError extends Error {
  constructor(message = '上一轮对话仍在处理中，请等待它结束后再发送。') {
    super(message)
    this.name = 'ChatBusyError'
  }
}

export type ApiError = {
  type: 'network' | 'server' | 'validation' | 'not_found' | 'unauthorized' | 'missing_token' | 'busy' | 'unknown'
  message: string
  status?: number
}

export function getDesktopApiToken(): string {
  return localStorage.getItem(TOKEN_STORAGE_KEY) || ''
}

export async function resolveDesktopApiToken(): Promise<string> {
  const token = await window.archerDesktop?.getApiToken?.()
  if (token) {
    if (token !== getDesktopApiToken()) saveDesktopApiToken(token)
    return token
  }
  return getDesktopApiToken()
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
      if (status === 429 && errorBody.error === 'chat_busy') return { type: 'busy', message, status }
      return { type: 'server', message, status }
    }
    if (status === 429) return { type: 'busy', message: '上一轮对话仍在处理中，请等待它结束后再发送。', status }
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

async function apiFetch(path: string, init: RequestInit = {}, auth = true, timeoutMs: number | null = API_TIMEOUT_MS): Promise<Response> {
  const headers = new Headers(init.headers)
  if (auth) {
    const token = await resolveDesktopApiToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }
  const signal = timeoutMs === null
    ? init.signal
    : init.signal
      ? AbortSignal.any([init.signal, AbortSignal.timeout(timeoutMs)])
      : AbortSignal.timeout(timeoutMs)
  try {
    const response = await fetch(`${BASE_URL}${path}`, { ...init, headers, signal })

    // Token mismatch auto-recovery: if 401, try re-fetching token from Electron main process
    if (auth && response.status === 401) {
      const freshToken = await refreshTokenFromMainProcess()
      if (freshToken) {
        headers.set('Authorization', `Bearer ${freshToken}`)
        const retrySignal = timeoutMs === null
          ? init.signal
          : init.signal
            ? AbortSignal.any([init.signal, AbortSignal.timeout(timeoutMs)])
            : AbortSignal.timeout(timeoutMs)
        return fetch(`${BASE_URL}${path}`, { ...init, headers, signal: retrySignal })
      }
    }

    return response
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new Error('[network] Local API request timed out')
    }
    throw new Error(error instanceof Error ? `[network] ${error.message}` : '[network] Local API is unreachable')
  }
}

export async function checkLocalApiReady(): Promise<boolean> {
  const response = await apiFetch('/ready', {}, false)
  if (response.ok) assertSupportedContractVersion(await response.json() as { contractVersion?: unknown })
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

export async function ensureLocalConnection(): Promise<boolean> {
  await resolveDesktopApiToken()
  const ensured = await window.archerDesktop?.ensureApi?.()
  if (!ensured?.ok) return false
  try {
    return await checkLocalApiReady()
  } catch {
    return false
  }
}

export async function restartLocalApi(): Promise<{ ok: boolean; reason: string }> {
  await resolveDesktopApiToken()
  return window.archerDesktop?.restartApi?.() ?? { ok: false, reason: 'unavailable' }
}

export async function loadLocalArcher(): Promise<ArcherAdapter> {
  const reviewPeriods: ReviewPeriod[] = ['weekly', 'monthly', 'life_stage']

  async function safeJson<T>(path: string, fallback: T): Promise<T> {
    try {
      return await getJson<T>(path)
    } catch {
      return fallback
    }
  }

  const statusRaw = await getJson<ArcherAdapter['status']>('/status')
  const status: ArcherAdapter['status'] = { ...statusRaw, adapter: 'local' }

  const [settings, experts, modes] = await Promise.all([
    getJson<ArcherAdapter['settings']>('/settings'),
    getJson<ArcherAdapter['experts']>('/experts'),
    getJson<ArcherAdapter['modes']>('/modes'),
  ])

  const [
    sessions,
    threads,
    memory,
    hypothesisResult,
    skills,
    proactive,
    initiativeShadowRaw,
    initiativeShadowReportRaw,
    initiativeShadowLongTermReportRaw,
    initiativeShadowDeliveryGateRaw,
    initiativeShadowReviewPacketRaw,
    soulProfile,
    soulFiles,
    periodReviewsList,
    journalReview,
    configDoctor,
    toolApprovalAudit,
  ] = await Promise.all([
    safeJson('/sessions', [] as ArcherAdapter['sessions']),
    safeJson('/threads', [] as ArcherAdapter['threads']),
    safeJson('/memory?include_rejected=true', [] as ArcherAdapter['memory']),
    safeJson('/hypotheses?status=all', { ok: false, hypotheses: [] } as HypothesisListResult),
    safeJson('/skills', [] as ArcherAdapter['skills']),
    safeJson('/proactive-touch', { enabled: false, items: [] } as ArcherAdapter['proactive']),
    safeJson('/initiative-shadow?limit=5', {
      ok: true,
      shadow: true,
      delivered: false,
      limit: 5,
      globalThrottleActive: false,
      presenceState: 'idle',
      items: [],
      report: defaultInitiativeShadowReport(),
      longTermReport: defaultInitiativeShadowLongTermReport(),
      deliveryGate: defaultInitiativeShadowDeliveryGate(),
      optIn: defaultInitiativeShadowOptIn(),
      reviewPacket: defaultInitiativeShadowReviewPacket(),
    } as ArcherAdapter['initiativeShadow']),
    safeJson('/initiative-shadow/report', {
      ok: true,
      shadow: true,
      report: defaultInitiativeShadowReport(),
    }),
    safeJson('/initiative-shadow/long-term-report', {
      ok: true,
      shadow: true,
      report: defaultInitiativeShadowLongTermReport(),
    }),
    safeJson('/initiative-shadow/delivery-gate', {
      ok: true,
      shadow: true,
      optIn: defaultInitiativeShadowOptIn(),
      gate: defaultInitiativeShadowDeliveryGate(),
    }),
    safeJson('/initiative-shadow/review-packet', {
      ok: true,
      shadow: true,
      optIn: defaultInitiativeShadowOptIn(),
      recommendedAction: 'keep_shadow',
      manualReport: defaultInitiativeShadowReport(),
      longTermReport: defaultInitiativeShadowLongTermReport(),
      deliveryGate: defaultInitiativeShadowDeliveryGate(),
    }),
    safeJson('/soul-profile', { empty: true, sections: [] } as ArcherAdapter['soulProfile']),
    safeJson('/soul-files', {} as ArcherAdapter['soulFiles']),
    Promise.all(reviewPeriods.map((period) => safeJson(`/reviews?period=${period}`, {
      period,
      title: period,
      window: { days: 0, start: '', end: '' },
      metrics: { sessions: 0, user_turns: 0, memories: 0, deep_memories: 0 },
      themes: [],
      highlights: [],
      growth_markers: [],
      suggested_questions: [],
      markdown: '',
    } as ArcherAdapter['periodReviews'][ReviewPeriod]))),
    safeJson('/journal-review?days=30', {
      configured: false,
      window: { days: 30, start: '', end: '' },
      metrics: { entries: 0, characters: 0 },
      entries: [],
      journal_emotions: {},
      session_emotions: {},
      markdown: '',
    } as ArcherAdapter['journalReview']),
    safeJson('/config/doctor', {
      ok: false,
      checkedAt: '',
      configPath: '',
      summary: { error: 1, warn: 0, info: 0 },
      issues: [{
        code: 'config_doctor_unavailable',
        level: 'error',
        message: '配置自检暂不可用',
        nextAction: '确认本地 Archer API 已启动后重试。',
      }],
      nextActions: ['确认本地 Archer API 已启动后重试。'],
    } as ArcherAdapter['configDoctor']),
    safeJson('/tool-approval-audit?limit=10', {
      ok: true,
      path: '',
      limit: 10,
      items: [],
    } as ArcherAdapter['toolApprovalAudit']),
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
      toolEvents: [],
      mockReply: '本地 API 已连接。当前聊天会走纯模型回复，还没有工具调用。'
    },
    sessions,
    threads,
    memory,
    hypotheses: normalizeHypotheses(hypothesisResult.hypotheses),
    skills,
    modes,
    experts,
    proactive,
    initiativeShadow: normalizeInitiativeShadow(
      initiativeShadowRaw,
      initiativeShadowReportRaw,
      initiativeShadowLongTermReportRaw,
      initiativeShadowDeliveryGateRaw,
      initiativeShadowReviewPacketRaw,
    ),
    soulProfile,
    soulFiles,
    periodReviews,
    journalReview,
    settings,
    configDoctor,
    toolApprovalAudit
  }
}

type RawInitiativeShadowItem = Record<string, unknown>
type RawInitiativeShadowReportResponse = {
  report?: Record<string, unknown>
  gate?: Record<string, unknown>
  optIn?: Record<string, unknown>
  recommendedAction?: unknown
  manualReport?: Record<string, unknown>
  longTermReport?: Record<string, unknown>
  deliveryGate?: Record<string, unknown>
}

function normalizeInitiativeShadow(
  raw: ArcherAdapter['initiativeShadow'],
  reportRaw?: RawInitiativeShadowReportResponse,
  longTermReportRaw?: RawInitiativeShadowReportResponse,
  deliveryGateRaw?: RawInitiativeShadowReportResponse,
  reviewPacketRaw?: RawInitiativeShadowReportResponse,
): ArcherAdapter['initiativeShadow'] {
  return {
    ok: Boolean(raw.ok),
    shadow: raw.shadow !== false,
    delivered: Boolean(raw.delivered),
    limit: Number(raw.limit || 0),
    globalThrottleActive: Boolean(raw.globalThrottleActive),
    presenceState: raw.presenceState === 'engaged' || raw.presenceState === 'muted' ? raw.presenceState : 'idle',
    items: Array.isArray(raw.items)
      ? raw.items.map(normalizeInitiativeShadowItem).filter((item) => item.id && item.message)
      : [],
    report: normalizeInitiativeShadowReport(reportRaw?.report),
    longTermReport: normalizeInitiativeShadowLongTermReport(longTermReportRaw?.report),
    deliveryGate: normalizeInitiativeShadowDeliveryGate(deliveryGateRaw?.gate),
    optIn: normalizeInitiativeShadowOptIn(deliveryGateRaw?.optIn ?? reviewPacketRaw?.optIn),
    reviewPacket: normalizeInitiativeShadowReviewPacket(reviewPacketRaw),
  }
}

function defaultInitiativeShadowReport(): ArcherAdapter['initiativeShadow']['report'] {
  return {
    observationDays: 0,
    totalCandidates: 0,
    dailyAverage: 0,
    feedbackCount: 0,
    recognitionRate: 0,
    readyForManualReview: false,
    reasons: ['insufficient_observation_days'],
    thresholds: {
      requiredDays: 7,
      maxDailyAverage: 3,
      minFeedback: 3,
      minRecognitionRate: 0.7,
    },
  }
}

function normalizeInitiativeShadowReport(report?: Record<string, unknown>): ArcherAdapter['initiativeShadow']['report'] {
  const fallback = defaultInitiativeShadowReport()
  if (!report) return fallback
  const thresholds = report.thresholds && typeof report.thresholds === 'object' && !Array.isArray(report.thresholds)
    ? report.thresholds as Record<string, unknown>
    : {}
  return {
    observationDays: Number(report.observation_days ?? report.observationDays ?? fallback.observationDays),
    totalCandidates: Number(report.total_candidates ?? report.totalCandidates ?? fallback.totalCandidates),
    dailyAverage: Number(report.daily_average ?? report.dailyAverage ?? fallback.dailyAverage),
    feedbackCount: Number(report.feedback_count ?? report.feedbackCount ?? fallback.feedbackCount),
    recognitionRate: Number(report.recognition_rate ?? report.recognitionRate ?? fallback.recognitionRate),
    readyForManualReview: Boolean(report.ready_for_manual_review ?? report.readyForManualReview),
    reasons: Array.isArray(report.reasons) ? report.reasons.map(String) : fallback.reasons,
    thresholds: {
      requiredDays: Number(thresholds.required_days ?? thresholds.requiredDays ?? fallback.thresholds.requiredDays),
      maxDailyAverage: Number(thresholds.max_daily_average ?? thresholds.maxDailyAverage ?? fallback.thresholds.maxDailyAverage),
      minFeedback: Number(thresholds.min_feedback ?? thresholds.minFeedback ?? fallback.thresholds.minFeedback),
      minRecognitionRate: Number(thresholds.min_recognition_rate ?? thresholds.minRecognitionRate ?? fallback.thresholds.minRecognitionRate),
    },
  }
}

function defaultInitiativeShadowLongTermReport(): ArcherAdapter['initiativeShadow']['longTermReport'] {
  return {
    observedDays: 0,
    candidateCount: 0,
    readyForDeliveryReview: false,
    reasons: ['continue_shadow_observation'],
    metrics: {
      frequency: {
        dailyAverage: 0,
        maxDailyCount: 0,
      },
      relevance: {
        feedbackCount: 0,
        recognitionRate: 0,
        tooFrequentRate: 0,
      },
      continuity: {
        threadResumeCount: 0,
      },
    },
  }
}

function normalizeInitiativeShadowLongTermReport(report?: Record<string, unknown>): ArcherAdapter['initiativeShadow']['longTermReport'] {
  const fallback = defaultInitiativeShadowLongTermReport()
  if (!report) return fallback
  const metrics = report.metrics && typeof report.metrics === 'object' && !Array.isArray(report.metrics)
    ? report.metrics as Record<string, unknown>
    : {}
  const frequency = metrics.frequency && typeof metrics.frequency === 'object' && !Array.isArray(metrics.frequency)
    ? metrics.frequency as Record<string, unknown>
    : {}
  const relevance = metrics.relevance && typeof metrics.relevance === 'object' && !Array.isArray(metrics.relevance)
    ? metrics.relevance as Record<string, unknown>
    : {}
  const continuity = metrics.continuity && typeof metrics.continuity === 'object' && !Array.isArray(metrics.continuity)
    ? metrics.continuity as Record<string, unknown>
    : {}
  return {
    observedDays: Number(report.observed_days ?? report.observedDays ?? fallback.observedDays),
    candidateCount: Number(report.candidate_count ?? report.candidateCount ?? fallback.candidateCount),
    readyForDeliveryReview: Boolean(report.ready_for_delivery_review ?? report.readyForDeliveryReview),
    reasons: Array.isArray(report.reasons) ? report.reasons.map(String) : fallback.reasons,
    metrics: {
      frequency: {
        dailyAverage: Number(frequency.daily_average ?? frequency.dailyAverage ?? fallback.metrics.frequency.dailyAverage),
        maxDailyCount: Number(frequency.max_daily_count ?? frequency.maxDailyCount ?? fallback.metrics.frequency.maxDailyCount),
      },
      relevance: {
        feedbackCount: Number(relevance.feedback_count ?? relevance.feedbackCount ?? fallback.metrics.relevance.feedbackCount),
        recognitionRate: Number(relevance.recognition_rate ?? relevance.recognitionRate ?? fallback.metrics.relevance.recognitionRate),
        tooFrequentRate: Number(relevance.too_frequent_rate ?? relevance.tooFrequentRate ?? fallback.metrics.relevance.tooFrequentRate),
      },
      continuity: {
        threadResumeCount: Number(continuity.thread_resume_count ?? continuity.threadResumeCount ?? fallback.metrics.continuity.threadResumeCount),
      },
    },
  }
}

function defaultInitiativeShadowDeliveryGate(): ArcherAdapter['initiativeShadow']['deliveryGate'] {
  return {
    canEnableDelivery: false,
    shadowOnly: true,
    reasons: ['explicit_opt_in_required'],
    requirements: {
      requiredObservationDays: 14,
      explicitOptIn: true,
      manualReview: true,
    },
    timeline: {
      firstObservedAt: null,
      earliestReviewAt: null,
      remainingObservationDays: 14,
    },
  }
}

function normalizeInitiativeShadowDeliveryGate(gate?: Record<string, unknown>): ArcherAdapter['initiativeShadow']['deliveryGate'] {
  const fallback = defaultInitiativeShadowDeliveryGate()
  if (!gate) return fallback
  const requirements = gate.requirements && typeof gate.requirements === 'object' && !Array.isArray(gate.requirements)
    ? gate.requirements as Record<string, unknown>
    : {}
  const timeline = gate.timeline && typeof gate.timeline === 'object' && !Array.isArray(gate.timeline)
    ? gate.timeline as Record<string, unknown>
    : {}
  return {
    canEnableDelivery: Boolean(gate.can_enable_delivery ?? gate.canEnableDelivery),
    shadowOnly: gate.shadow_only === undefined && gate.shadowOnly === undefined
      ? fallback.shadowOnly
      : Boolean(gate.shadow_only ?? gate.shadowOnly),
    reasons: Array.isArray(gate.reasons) ? gate.reasons.map(String) : fallback.reasons,
    requirements: {
      requiredObservationDays: Number(requirements.required_observation_days ?? requirements.requiredObservationDays ?? fallback.requirements.requiredObservationDays),
      explicitOptIn: Boolean(requirements.explicit_opt_in ?? requirements.explicitOptIn ?? fallback.requirements.explicitOptIn),
      manualReview: Boolean(requirements.manual_review ?? requirements.manualReview ?? fallback.requirements.manualReview),
    },
    timeline: {
      firstObservedAt: timeline.first_observed_at || timeline.firstObservedAt ? String(timeline.first_observed_at ?? timeline.firstObservedAt) : fallback.timeline.firstObservedAt,
      earliestReviewAt: timeline.earliest_review_at || timeline.earliestReviewAt ? String(timeline.earliest_review_at ?? timeline.earliestReviewAt) : fallback.timeline.earliestReviewAt,
      remainingObservationDays: Number(timeline.remaining_observation_days ?? timeline.remainingObservationDays ?? fallback.timeline.remainingObservationDays),
    },
  }
}

function defaultInitiativeShadowReviewPacket(): ArcherAdapter['initiativeShadow']['reviewPacket'] {
  return {
    recommendedAction: 'keep_shadow',
    optIn: defaultInitiativeShadowOptIn(),
    manualReport: defaultInitiativeShadowReport(),
    longTermReport: defaultInitiativeShadowLongTermReport(),
    deliveryGate: defaultInitiativeShadowDeliveryGate(),
  }
}

function defaultInitiativeShadowOptIn(): ArcherAdapter['initiativeShadow']['optIn'] {
  return {
    enabled: false,
    updatedAt: null,
    reason: 'not_set',
  }
}

function normalizeInitiativeShadowOptIn(raw?: unknown): ArcherAdapter['initiativeShadow']['optIn'] {
  const fallback = defaultInitiativeShadowOptIn()
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return fallback
  const item = raw as Record<string, unknown>
  return {
    enabled: Boolean(item.enabled),
    updatedAt: item.updated_at || item.updatedAt ? String(item.updated_at ?? item.updatedAt) : fallback.updatedAt,
    reason: String(item.reason || fallback.reason),
  }
}

function normalizeInitiativeShadowReviewPacket(raw?: RawInitiativeShadowReportResponse): ArcherAdapter['initiativeShadow']['reviewPacket'] {
  const fallback = defaultInitiativeShadowReviewPacket()
  if (!raw) return fallback
  return {
    recommendedAction: String(raw.recommendedAction || fallback.recommendedAction),
    optIn: normalizeInitiativeShadowOptIn(raw.optIn),
    manualReport: normalizeInitiativeShadowReport(raw.manualReport),
    longTermReport: normalizeInitiativeShadowLongTermReport(raw.longTermReport),
    deliveryGate: normalizeInitiativeShadowDeliveryGate(raw.deliveryGate),
  }
}

function normalizeInitiativeShadowItem(item: RawInitiativeShadowItem): ArcherAdapter['initiativeShadow']['items'][number] {
  const trace = item.decision_trace ?? item.decisionTrace
  return {
    id: Number(item.id || 0),
    eventType: String(item.event_type || item.eventType || ''),
    kind: String(item.kind || ''),
    title: String(item.title || ''),
    message: String(item.message || ''),
    delivered: Boolean(item.delivered),
    decisionTrace: trace && typeof trace === 'object' && !Array.isArray(trace)
      ? trace as Record<string, unknown>
      : {},
    createdAt: String(item.created_at || item.createdAt || ''),
    feedback: String(item.feedback || ''),
    archivedAt: item.archived_at || item.archivedAt ? String(item.archived_at || item.archivedAt) : null,
  }
}

type RawHypothesis = Record<string, unknown>

function normalizeHypotheses(items: RawHypothesis[]): HypothesisItem[] {
  return items.map((item) => ({
    id: Number(item.id || 0),
    title: String(item.title || ''),
    statement: String(item.statement || ''),
    status: normalizeHypothesisStatus(item.status),
    source: String(item.source || ''),
    triggerType: String(item.trigger_type || item.triggerType || ''),
    confidence: Number(item.confidence ?? 0),
    evidence: Array.isArray(item.evidence)
      ? item.evidence.map((ev) => ({
        content: String((ev as RawHypothesis).content || ''),
        source: String((ev as RawHypothesis).source || ''),
        createdAt: String((ev as RawHypothesis).created_at || (ev as RawHypothesis).createdAt || ''),
      })).filter((ev) => ev.content)
      : [],
    validateAfter: String(item.validate_after || item.validateAfter || ''),
    createdAt: String(item.created_at || item.createdAt || ''),
    updatedAt: String(item.updated_at || item.updatedAt || ''),
    lastReviewedAt: String(item.last_reviewed_at || item.lastReviewedAt || ''),
    verifiedAt: String(item.verified_at || item.verifiedAt || ''),
    sessionId: String(item.session_id || item.sessionId || ''),
    verificationNote: String(item.verification_note || item.verificationNote || ''),
    mutedUntil: String(item.muted_until || item.mutedUntil || ''),
  })).filter((item) => item.id && item.statement)
}

function normalizeHypothesisStatus(status: unknown): HypothesisItem['status'] {
  if (status === 'verified' || status === 'rejected' || status === 'dismissed') return status
  return 'active'
}

export async function loadLocalSession(sessionId: string): Promise<SessionDetail> {
  return getJson<SessionDetail>(`/sessions/${encodeURIComponent(sessionId)}`)
}

export async function searchLocalSessions(query: string): Promise<SessionSearchResult[]> {
  if (!query.trim()) return []
  return getJson<SessionSearchResult[]>(`/sessions/search?q=${encodeURIComponent(query)}`)
}

export async function sendLocalChat(messages: ChatRequestMessage[]): Promise<string> {
  const response = await postJson<{ role: 'assistant'; text: string }>('/chat', { messages })
  return response.text
}

export type SessionSaveMeta = {
  expertId?: string
  expertLabel?: string
}

export async function saveLocalSession(
  messages: ChatRequestMessage[],
  meta: SessionSaveMeta = {},
): Promise<SavedSession> {
  return postJson<SavedSession>('/sessions', { messages, ...meta })
}

export async function appendLocalSession(sessionId: string, messages: ChatRequestMessage[]): Promise<SavedSession> {
  return postJson<SavedSession>(`/sessions/${encodeURIComponent(sessionId)}/append`, { messages })
}

export type SessionDeleteResult = {
  ok: boolean
  id: string
  fileDeleted: boolean
  threadRemoved?: string | null
}

export async function deleteLocalSession(sessionId: string): Promise<SessionDeleteResult> {
  return postJson<SessionDeleteResult>(`/sessions/${encodeURIComponent(sessionId)}/delete`, {})
}

export async function loadLocalThread(threadId: string): Promise<ConversationThread> {
  return getJson<ConversationThread>(`/threads/${encodeURIComponent(threadId)}`)
}

export async function createLocalThread(messages: ChatRequestMessage[], title?: string): Promise<ConversationThread> {
  return postJson<ConversationThread>('/threads', { messages, title })
}

export async function updateLocalThread(
  threadId: string,
  patch: Partial<Pick<ConversationThread, 'title' | 'summary' | 'projectId' | 'archived'>>,
): Promise<ConversationThread> {
  return postJson<ConversationThread>(`/threads/${encodeURIComponent(threadId)}`, patch)
}

export async function addLocalSessionToThread(threadId: string, sessionId: string): Promise<ConversationThread> {
  return postJson<ConversationThread>(`/threads/${encodeURIComponent(threadId)}/sessions`, { sessionId })
}

export async function resolvePendingMemory(id: number, accepted: boolean): Promise<MemoryResolveResult> {
  return postJson<MemoryResolveResult>(`/memory/pending/${id}/${accepted ? 'accept' : 'reject'}`, {})
}

export async function submitInitiativeFeedback(
  id: number,
  feedback: 'acknowledged' | 'too_frequent',
): Promise<{ ok: boolean; id: number; feedback: string }> {
  return postJson(`/initiative-shadow/${id}/feedback`, { feedback })
}

export async function setInitiativePresence(
  state: 'idle' | 'muted',
): Promise<{ ok: boolean; state: 'engaged' | 'idle' | 'muted'; reason: string }> {
  return postJson('/initiative-shadow/presence', { state })
}

export async function setInitiativeDeliveryOptIn(
  enabled: boolean,
): Promise<{
  ok: boolean
  shadow: boolean
  optIn: ArcherAdapter['initiativeShadow']['optIn']
  gate: ArcherAdapter['initiativeShadow']['deliveryGate']
}> {
  return postJson('/initiative-shadow/opt-in', {
    enabled,
    reason: enabled ? 'desktop_today_opt_in' : 'desktop_today_revoke',
  })
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

export async function fetchVaultReflections(limit: number = 20): Promise<{ ok: boolean; reflections: VaultReflection[] }> {
  return getJson<{ ok: boolean; reflections: VaultReflection[] }>(`/vault/reflection/recent?limit=${limit}`)
}

export async function triggerVaultReflection(payload: { path?: string; days?: number; maxNotes?: number; force?: boolean }): Promise<VaultReflectionResult> {
  return postJson<VaultReflectionResult>('/vault/reflection', payload)
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

export async function switchLocalExpert(expert: string): Promise<ExpertSwitchResult> {
  return postJson<ExpertSwitchResult>('/experts/current', { expert })
}

export async function fetchLocalExpertWorkbench(): Promise<{
  experts: ArcherAdapter['experts']
  status: ArcherAdapter['status']
}> {
  const [experts, statusRaw] = await Promise.all([
    getJson<ArcherAdapter['experts']>('/experts'),
    getJson<ArcherAdapter['status']>('/status'),
  ])
  return {
    experts,
    status: { ...statusRaw, adapter: 'local' },
  }
}

export async function validateLocalSettings(settings: SettingsDraft): Promise<SettingsValidationResult> {
  return postJson<SettingsValidationResult>('/settings/validate', { settings })
}

export async function saveLocalSettings(settings: SettingsDraft): Promise<SettingsSaveResult> {
  return postJson<SettingsSaveResult>('/settings/save', { settings })
}

export async function saveLocalProfileSettings(payload: {
  profileId: 'lite' | 'pro' | 'max'
  provider?: string
  baseUrl?: string
  model?: string
  apiKey?: string
}): Promise<{ ok: boolean; profileId?: string; error?: string; message?: string }> {
  return postJson('/settings/profile/save', payload)
}

export async function switchLocalActiveProfile(profileId: 'lite' | 'pro' | 'max'): Promise<{ ok: boolean; profileId?: string; activeProfile?: string; error?: string; message?: string }> {
  const result = await postJson<{ ok: boolean; profileId?: string; activeProfile?: string; error?: string; message?: string }>('/settings/profile/switch', { profileId })
  if (!result.ok) return result
  const settings = await getJson<ArcherAdapter['settings']>('/settings')
  if (settings.activeProfile !== profileId) {
    return {
      ok: false,
      profileId,
      activeProfile: settings.activeProfile,
      error: `模型切换未生效：当前仍是 ${settings.activeProfile}`,
    }
  }
  return {
    ...result,
    profileId,
    activeProfile: settings.activeProfile,
  }
}

export async function testLocalModelProfile(settings: SettingsDraft): Promise<ModelProfileTestResult> {
  return postJson<ModelProfileTestResult>('/settings/test-model', { settings })
}

export async function listSchedules(): Promise<ScheduleListResult> {
  return getJson<ScheduleListResult>('/schedules')
}

export async function addSchedule(payload: {
  skillName: string
  interval: string
  label?: string
  catchup?: 'latest' | 'skip'
}): Promise<ScheduleMutationResult> {
  return postJson<ScheduleMutationResult>('/schedules', payload)
}

export async function removeSchedule(taskId: number): Promise<ScheduleMutationResult> {
  return postJson<ScheduleMutationResult>(`/schedules/${taskId}/remove`, {})
}

export async function setScheduleEnabled(taskId: number, enabled: boolean): Promise<ScheduleMutationResult> {
  return postJson<ScheduleMutationResult>(`/schedules/${taskId}/${enabled ? 'enable' : 'disable'}`, {})
}

export async function runSchedule(taskId: number): Promise<ScheduleMutationResult> {
  return postJson<ScheduleMutationResult>(`/schedules/${taskId}/run`, {})
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
  decision: 'approved' | 'denied',
  draftFallback?: ToolEvent['draft']
): Promise<ToolApprovalResult> {
  return postJson<ToolApprovalResult>('/tool-approvals', { eventId, decision, draftFallback })
}

export async function submitToolApprovalEvent(
  sessionId: string,
  eventId: string,
  decision: 'approved' | 'denied',
  draftFallback?: ToolEvent['draft']
): Promise<{ result: ToolApprovalResult; event: AgentEvent }> {
  const result = await submitToolApproval(eventId, decision, draftFallback)
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
  threadContext: { title?: string; summary?: string; projectSummary?: string } | null,
  onText: (text: string) => void,
  onToolEvent?: (event: ToolEvent) => void,
  onAgentEvent?: (event: AgentEvent) => void,
  signal?: AbortSignal,
  runtimeSessionId = 'desktop-session'
): Promise<void> {
  const response = await apiFetch('/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, memoryMode, obsidianMode, fileRefs, threadContext }),
    signal
  }, true, null)
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}))
    const error = parseError(response, body)
    if (error.type === 'busy') {
      throw new ChatBusyError(error.message)
    }
    throw new Error(`[${error.type}] ${error.message}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  // SSE 读超时需要长于后端模型请求超时，避免长文本/换模型时前端先于 API 判定失败。
  const READ_TIMEOUT_MS = 90_000
  // 整体最大流时长：防止后端持续发心跳但不结束，导致 isSending 永远卡住
  const MAX_STREAM_DURATION_MS = 300_000
  const streamStart = Date.now()

  try {
    while (true) {
      // 整体超时守卫：超过 5 分钟强制中止
      if (Date.now() - streamStart > MAX_STREAM_DURATION_MS) {
        throw new StreamIdleTimeoutError()
      }
      // 用 Promise.race 实现读超时，防止 API 进程崩溃后 SSE 流卡住
      const readPromise = reader.read()
      let timeoutId: ReturnType<typeof setTimeout> | null = null
      const timeoutPromise = new Promise<never>((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error('SSE_READ_TIMEOUT')), READ_TIMEOUT_MS)
      })
      try {
        const { value, done } = await Promise.race([readPromise, timeoutPromise])
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''
        for (const frame of frames) {
          const line = frame
            .split('\n')
            .find((part) => part.startsWith('data: '))
          if (!line) continue
          const payload = JSON.parse(line.slice(6)) as PythonStreamPayload & {
            text?: string
            done?: boolean
            error?: string
            toolEvent?: ToolEvent
          }
          if (payload.error) throw new Error(`[server] ${payload.error}`)
          if (payload.toolEvent) {
            onToolEvent?.(payload.toolEvent)
          }
          for (const event of pythonStreamPayloadToAgentEvents(runtimeSessionId, payload)) onAgentEvent?.(event)
          if (payload.text) onText(payload.text)
          if (payload.done) return
        }
      } finally {
        if (timeoutId) clearTimeout(timeoutId)
      }
    }
  } catch (err) {
    // 读超时或异常：抛出明确错误，让上层显示提示而非无限卡住
    if (err instanceof Error && err.message === 'SSE_READ_TIMEOUT') {
      throw new StreamIdleTimeoutError()
    }
    throw err
  } finally {
    // 确保异常或提前 return 时释放 reader，避免连接池资源泄漏
    // 多轮对话中上一轮 reader 未清理会导致下一轮请求失败
    try {
      await reader.cancel()
    } catch {
      // reader 已被释放或流已关闭，忽略
    }
  }
}
