import type { InitiativeShadowReview } from '../types'

export function defaultInitiativeShadowExposureReport(): InitiativeShadowReview['exposureReport'] {
  return {
    surface: 'chat_workspace',
    days: 14,
    exposureCount: 0,
    feedbackCount: 0,
    conversionRate: 0,
    acknowledgedCount: 0,
    recognitionRate: 0,
    tooFrequentCount: 0,
    tooFrequentRate: 0,
    muteCount: 0,
  }
}

export function normalizeInitiativeShadowExposureReport(
  report?: Record<string, unknown>,
): InitiativeShadowReview['exposureReport'] {
  const fallback = defaultInitiativeShadowExposureReport()
  if (!report) return fallback
  const surface = String(report.surface || fallback.surface)
  return {
    surface: surface === 'today' || surface === 'legacy' ? surface : 'chat_workspace',
    days: Number(report.days ?? fallback.days),
    exposureCount: Number(report.exposure_count ?? report.exposureCount ?? 0),
    feedbackCount: Number(report.feedback_count ?? report.feedbackCount ?? 0),
    conversionRate: Number(report.conversion_rate ?? report.conversionRate ?? 0),
    acknowledgedCount: Number(report.acknowledged_count ?? report.acknowledgedCount ?? 0),
    recognitionRate: Number(report.recognition_rate ?? report.recognitionRate ?? 0),
    tooFrequentCount: Number(report.too_frequent_count ?? report.tooFrequentCount ?? 0),
    tooFrequentRate: Number(report.too_frequent_rate ?? report.tooFrequentRate ?? 0),
    muteCount: Number(report.mute_count ?? report.muteCount ?? 0),
  }
}

export function defaultInitiativeShadowReport(): InitiativeShadowReview['report'] {
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

export function normalizeInitiativeShadowReport(
  report?: Record<string, unknown>,
): InitiativeShadowReview['report'] {
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
