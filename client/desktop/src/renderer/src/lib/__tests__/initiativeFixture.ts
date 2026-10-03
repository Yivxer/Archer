import type { InitiativeShadowReview } from '../../types'
import { defaultInitiativeShadowExposureReport } from '../../adapters/initiativeReports'
export const initiativeReviewFixture: InitiativeShadowReview = {
    ok: true,
    shadow: true,
    delivered: false,
    limit: 5,
    globalThrottleActive: false,
    presenceState: 'idle',
    items: [],
    exposureReport: defaultInitiativeShadowExposureReport(),
    report: {
      observationDays: 3,
      totalCandidates: 5,
      dailyAverage: 1.7,
      feedbackCount: 1,
      recognitionRate: 0.6,
      readyForManualReview: false,
      reasons: ['insufficient_observation_days', 'insufficient_feedback'],
      thresholds: {
        requiredDays: 7,
        maxDailyAverage: 3,
        minFeedback: 3,
        minRecognitionRate: 0.7,
      },
    },
    longTermReport: {
      observedDays: 3,
      candidateCount: 5,
      readyForDeliveryReview: false,
      reasons: ['continue_shadow_observation'],
      metrics: {
        frequency: {
          dailyAverage: 1.7,
          maxDailyCount: 2,
        },
        relevance: {
          feedbackCount: 1,
          recognitionRate: 0.6,
          tooFrequentRate: 0,
        },
        continuity: {
          threadResumeCount: 2,
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
        observationDays: 3,
        totalCandidates: 5,
        dailyAverage: 1.7,
        feedbackCount: 1,
        recognitionRate: 0.6,
        readyForManualReview: false,
        reasons: ['insufficient_observation_days', 'insufficient_feedback'],
        thresholds: {
          requiredDays: 7,
          maxDailyAverage: 3,
          minFeedback: 3,
          minRecognitionRate: 0.7,
        },
      },
      longTermReport: {
        observedDays: 3,
        candidateCount: 5,
        readyForDeliveryReview: false,
        reasons: ['continue_shadow_observation'],
        metrics: {
          frequency: { dailyAverage: 1.7, maxDailyCount: 2 },
          relevance: { feedbackCount: 1, recognitionRate: 0.6, tooFrequentRate: 0 },
          continuity: { threadResumeCount: 2 },
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
