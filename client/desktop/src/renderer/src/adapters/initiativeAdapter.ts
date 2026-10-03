/** Initiative HTTP projection; failed reads never become successful empty reports. */
import { getJson, postJson } from './localArcher'
import type { InitiativeShadowReview } from '../types'
import {
  defaultInitiativeShadowExposureReport,
  defaultInitiativeShadowReport,
  normalizeInitiativeShadowExposureReport,
  normalizeInitiativeShadowReport,
} from './initiativeReports'
export async function fetchInitiativeReview(): Promise<InitiativeShadowReview> {
  const paths = ['/initiative-shadow?limit=5', '/initiative-shadow/report', '/initiative-shadow/long-term-report', '/initiative-shadow/delivery-gate', '/initiative-shadow/review-packet', '/initiative-shadow/exposure-report?surface=chat_workspace&days=14']
  const parts = await Promise.all(paths.map((path) => getJson<Record<string, unknown>>(path)))
  if (parts.some((part) => part.ok !== true)) throw new Error('观察数据未完整读取，请刷新重试')
  if (!Array.isArray(parts[0].items) || !parts[1].report || !parts[2].report || !parts[3].gate || !parts[3].optIn || !parts[4].manualReport || !parts[4].deliveryGate || !parts[5].report) {
    throw new Error('观察数据缺少完整报告，请刷新重试')
  }
  return normalizeInitiativeShadow(parts[0] as InitiativeShadowReview, ...parts.slice(1) as RawInitiativeShadowReportResponse[])
}

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
  raw: InitiativeShadowReview,
  reportRaw?: RawInitiativeShadowReportResponse,
  longTermReportRaw?: RawInitiativeShadowReportResponse,
  deliveryGateRaw?: RawInitiativeShadowReportResponse,
  reviewPacketRaw?: RawInitiativeShadowReportResponse,
  exposureReportRaw?: RawInitiativeShadowReportResponse,
): InitiativeShadowReview {
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
    exposureReport: normalizeInitiativeShadowExposureReport(exposureReportRaw?.report),
  }
}

function defaultInitiativeShadowLongTermReport(): InitiativeShadowReview['longTermReport'] {
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

function normalizeInitiativeShadowLongTermReport(report?: Record<string, unknown>): InitiativeShadowReview['longTermReport'] {
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

function defaultInitiativeShadowDeliveryGate(): InitiativeShadowReview['deliveryGate'] {
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

function normalizeInitiativeShadowDeliveryGate(gate?: Record<string, unknown>): InitiativeShadowReview['deliveryGate'] {
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

function defaultInitiativeShadowReviewPacket(): InitiativeShadowReview['reviewPacket'] {
  return {
    recommendedAction: 'keep_shadow',
    optIn: defaultInitiativeShadowOptIn(),
    manualReport: defaultInitiativeShadowReport(),
    longTermReport: defaultInitiativeShadowLongTermReport(),
    deliveryGate: defaultInitiativeShadowDeliveryGate(),
  }
}

function normalizeInitiativeShadowReviewPacket(raw?: RawInitiativeShadowReportResponse): InitiativeShadowReview['reviewPacket'] {
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

export async function submitInitiativeFeedback(
  id: number,
  feedback: 'acknowledged' | 'too_frequent',
  surface?: 'chat_workspace' | 'today',
): Promise<{ ok: boolean; id: number; feedback: string }> {
  return postJson(`/initiative-shadow/${id}/feedback`, { feedback, ...(surface ? { surface } : {}) })
}

export async function setInitiativePresence(
  state: 'idle' | 'muted',
  surface?: 'chat_workspace' | 'today',
): Promise<{ ok: boolean; state: 'engaged' | 'idle' | 'muted'; reason: string }> {
  return postJson('/initiative-shadow/presence', { state, ...(surface ? { surface } : {}) })
}

export async function claimInitiativeReviewCandidate(): Promise<import('../types').InitiativeShadowReviewCandidate> {
  const raw = await postJson<Record<string, unknown>>('/initiative-shadow/review-candidate', {
    surface: 'chat_workspace',
  })
  const item = raw.item && typeof raw.item === 'object' && !Array.isArray(raw.item)
    ? normalizeInitiativeShadowItem(raw.item as Record<string, unknown>)
    : null
  const reason = String(raw.reason || 'no_candidate')
  return {
    ok: Boolean(raw.ok),
    shadow: raw.shadow !== false,
    delivered: false,
    surface: 'chat_workspace',
    exposureDate: String(raw.exposure_date || raw.exposureDate || ''),
    reason: reason === 'candidate' || reason === 'already_reviewed_today' || reason === 'muted'
      ? reason
      : 'no_candidate',
    item,
  }
}

export async function setInitiativeDeliveryOptIn(
  enabled: boolean,
): Promise<{
  ok: boolean
  shadow: boolean
  optIn: InitiativeShadowReview['optIn']
  gate: InitiativeShadowReview['deliveryGate']
}> {
  return postJson('/initiative-shadow/opt-in', {
    enabled,
    reason: enabled ? 'desktop_today_opt_in' : 'desktop_today_revoke',
  })
}

export function defaultInitiativeShadowOptIn(): InitiativeShadowReview['optIn'] {
  return {
    enabled: false,
    updatedAt: null,
    reason: 'not_set',
  }
}

export function normalizeInitiativeShadowOptIn(raw?: unknown): InitiativeShadowReview['optIn'] {
  const fallback = defaultInitiativeShadowOptIn()
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return fallback
  const item = raw as Record<string, unknown>
  return {
    enabled: Boolean(item.enabled),
    updatedAt: item.updated_at || item.updatedAt ? String(item.updated_at ?? item.updatedAt) : fallback.updatedAt,
    reason: String(item.reason || fallback.reason),
  }
}

export function normalizeInitiativeShadowItem(
  item: Record<string, unknown>,
): InitiativeShadowReview['items'][number] {
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
