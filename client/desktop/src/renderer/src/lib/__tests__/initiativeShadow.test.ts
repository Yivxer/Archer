import { describe, expect, it } from 'vitest'
import { mergeInitiativeShadowEvent } from '../initiativeShadow'
import type { InitiativeEvent } from '../../../../agent/contracts'

const shadow = {
  ok: true,
  shadow: true,
  delivered: false,
  limit: 5,
  globalThrottleActive: false,
  presenceState: 'idle' as const,
  items: [],
  report: {
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
  },
  longTermReport: {
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
  },
  deliveryGate: {
    canEnableDelivery: false,
    shadowOnly: true,
    reasons: ['manual_review_not_ready', 'insufficient_long_term_observation', 'explicit_opt_in_required'],
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
  },
  optIn: {
    enabled: false,
    updatedAt: null,
    reason: 'not_set',
  },
  reviewPacket: {
    recommendedAction: 'keep_shadow',
    optIn: {
      enabled: false,
      updatedAt: null,
      reason: 'not_set',
    },
    manualReport: {
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
    },
    longTermReport: {
      observedDays: 0,
      candidateCount: 0,
      readyForDeliveryReview: false,
      reasons: ['continue_shadow_observation'],
      metrics: {
        frequency: { dailyAverage: 0, maxDailyCount: 0 },
        relevance: { feedbackCount: 0, recognitionRate: 0, tooFrequentRate: 0 },
        continuity: { threadResumeCount: 0 },
      },
    },
    deliveryGate: {
      canEnableDelivery: false,
      shadowOnly: true,
      reasons: ['manual_review_not_ready', 'insufficient_long_term_observation', 'explicit_opt_in_required'],
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
    },
  },
}

function initiativeEvent(overrides: Partial<InitiativeEvent> = {}): InitiativeEvent {
  return {
    type: 'initiative.event',
    id: 'initiative-12',
    sessionId: 'desktop-session',
    createdAt: '2026-06-26T18:00:00',
    kind: 'thread_resume',
    title: '拾起未闭合话题',
    message: '上次还留着一个话题。',
    shadow: true,
    delivered: false,
    decisionTrace: { reason: 'stale_open_thread' },
    ...overrides,
  }
}

describe('initiative shadow stream bridge', () => {
  it('adds a shadow initiative stream event for Today', () => {
    const next = mergeInitiativeShadowEvent(shadow, initiativeEvent())

    expect(next.items).toHaveLength(1)
    expect(next.items[0]).toMatchObject({
      id: 12,
      kind: 'thread_resume',
      delivered: false,
      decisionTrace: { reason: 'stale_open_thread' },
    })
  })

  it('ignores delivered events and duplicates', () => {
    const once = mergeInitiativeShadowEvent(shadow, initiativeEvent())

    expect(mergeInitiativeShadowEvent(once, initiativeEvent()).items).toHaveLength(1)
    expect(mergeInitiativeShadowEvent(once, initiativeEvent({ delivered: true }))).toEqual(once)
  })
})
