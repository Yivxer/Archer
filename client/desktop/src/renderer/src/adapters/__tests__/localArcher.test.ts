import { describe, expect, it, beforeEach, vi } from 'vitest'

// Mock localStorage for Node test environment
const store: Record<string, string> = {}
vi.stubGlobal('localStorage', {
  getItem: vi.fn((key: string) => store[key] ?? null),
  setItem: vi.fn((key: string, value: string) => { store[key] = value }),
  removeItem: vi.fn((key: string) => { delete store[key] }),
})

// Mock window.archerDesktop for Node test environment
vi.stubGlobal('window', {
  archerDesktop: undefined,
})

import {
  clearDesktopApiToken,
  ChatBusyError,
  ensureLocalConnection,
  getDesktopApiToken,
  loadLocalArcher,
  resolveDesktopApiToken,
  saveDesktopApiToken,
  setInitiativeDeliveryOptIn,
  StreamIdleTimeoutError,
  spawnChildJobs,
  streamLocalChat,
  submitInitiativeFeedback,
  setInitiativePresence,
  switchLocalActiveProfile,
} from '../localArcher'

describe('localArcher token management', () => {
  beforeEach(() => {
    Object.keys(store).forEach((key) => delete store[key])
  })

  it('saves and retrieves token from localStorage', () => {
    saveDesktopApiToken('test-token-abc')
    expect(getDesktopApiToken()).toBe('test-token-abc')
  })

  it('clears token when empty string is saved', () => {
    saveDesktopApiToken('test-token-abc')
    saveDesktopApiToken('')
    expect(getDesktopApiToken()).toBe('')
  })

  it('clears token via clearDesktopApiToken', () => {
    saveDesktopApiToken('test-token-abc')
    clearDesktopApiToken()
    expect(getDesktopApiToken()).toBe('')
  })

  it('trims whitespace from saved token', () => {
    saveDesktopApiToken('  token-with-spaces  ')
    expect(getDesktopApiToken()).toBe('token-with-spaces')
  })

  it('resolveDesktopApiToken returns saved token when available', async () => {
    saveDesktopApiToken('saved-token')
    const result = await resolveDesktopApiToken()
    expect(result).toBe('saved-token')
  })

  it('resolveDesktopApiToken returns empty string when no token saved (no IPC in test env)', async () => {
    const result = await resolveDesktopApiToken()
    expect(result).toBe('')
  })

  it('ensureLocalConnection checks /ready after ensuring the API process', async () => {
    vi.stubGlobal('window', {
      archerDesktop: {
        ensureApi: vi.fn(async () => ({ ok: true, reason: 'owned' })),
      },
    })
    const fetchSpy = vi.fn(async (_url: string) => new Response(JSON.stringify({ contractVersion: 1, ok: true, ready: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)

    await expect(ensureLocalConnection()).resolves.toBe(true)

    expect(fetchSpy).toHaveBeenCalledOnce()
    expect(String(fetchSpy.mock.calls[0][0])).toContain('/ready')
  })

  it('confirms active profile by reading settings after switching models', async () => {
    saveDesktopApiToken('test-token')
    const fetchSpy = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes('/settings/profile/switch')) {
        expect(JSON.parse(String(init?.body))).toEqual({ profileId: 'max' })
        return new Response(JSON.stringify({ ok: true, profileId: 'max' }), { status: 200 })
      }
      if (String(url).includes('/settings')) {
        return new Response(JSON.stringify({ activeProfile: 'max' }), { status: 200 })
      }
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchSpy)

    await expect(switchLocalActiveProfile('max')).resolves.toMatchObject({
      ok: true,
      profileId: 'max',
      activeProfile: 'max',
    })
    expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining('/settings/profile/switch'), expect.any(Object))
    expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining('/settings'), expect.any(Object))
  })

  it('reports a model switch failure when settings read-back does not match', async () => {
    saveDesktopApiToken('test-token')
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('/settings/profile/switch')) {
        return new Response(JSON.stringify({ ok: true, profileId: 'max' }), { status: 200 })
      }
      if (String(url).includes('/settings')) {
        return new Response(JSON.stringify({ activeProfile: 'pro' }), { status: 200 })
      }
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    }))

    await expect(switchLocalActiveProfile('max')).resolves.toMatchObject({
      ok: false,
      profileId: 'max',
      activeProfile: 'pro',
    })
  })

  it('submits initiative feedback and presence controls to the local API', async () => {
    const fetchSpy = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)

    await submitInitiativeFeedback(7, 'too_frequent')
    await setInitiativePresence('muted')
    await setInitiativeDeliveryOptIn(true)

    expect(String(fetchSpy.mock.calls[0][0])).toContain('/initiative-shadow/7/feedback')
    expect(JSON.parse(String(fetchSpy.mock.calls[0][1]?.body))).toEqual({ feedback: 'too_frequent' })
    expect(String(fetchSpy.mock.calls[1][0])).toContain('/initiative-shadow/presence')
    expect(JSON.parse(String(fetchSpy.mock.calls[1][1]?.body))).toEqual({ state: 'muted' })
    expect(String(fetchSpy.mock.calls[2][0])).toContain('/initiative-shadow/opt-in')
    expect(JSON.parse(String(fetchSpy.mock.calls[2][1]?.body))).toMatchObject({ enabled: true })
  })

  it('uses the provided runtime session id for stream agent events', async () => {
    const encoder = new TextEncoder()
    const payload = [
      'data: ' + JSON.stringify({
        contractVersion: 1,
        planEvent: {
          id: 'plan-1',
          title: '提炼内容并写入 Obsidian',
          status: 'proposed',
          detail: '先整理，再请求写入确认',
          steps: [
            { id: 1, action: 'read_source', tool: 'input_context', requiresApproval: false },
          ],
        },
      }) + '\n\n',
      'data: ' + JSON.stringify({ contractVersion: 1, done: true }) + '\n\n',
    ].join('')
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode(payload))
          controller.close()
        },
      }),
      { status: 200 }
    )))

    const events: Array<{ sessionId: string }> = []
    await streamLocalChat(
      [{ role: 'user', content: '测试' }],
      'off',
      'off',
      [],
      null,
      () => {},
      undefined,
      (event) => events.push({ sessionId: event.sessionId }),
      undefined,
      'session-current'
    )

    expect(events).toEqual([{ sessionId: 'session-current' }])
  })

  it('does not wrap chat stream cancellation in the short API timeout signal', async () => {
    const encoder = new TextEncoder()
    const fetchSpy = vi.fn(async () => new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('data: ' + JSON.stringify({ contractVersion: 1, done: true }) + '\n\n'))
          controller.close()
        },
      }),
      { status: 200 }
    ))
    vi.stubGlobal('fetch', fetchSpy)
    const controller = new AbortController()

    await streamLocalChat(
      [{ role: 'user', content: '第二轮测试' }],
      'off',
      'off',
      [],
      null,
      () => {},
      undefined,
      undefined,
      controller.signal,
      'session-current'
    )

    const [, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit]
    expect(init.signal).toBe(controller.signal)
  })

  it('preserves AbortError for manually cancelled chat streams', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new DOMException('The operation was aborted.', 'AbortError')
    }))

    await expect(streamLocalChat(
      [{ role: 'user', content: '停一下' }],
      'off',
      'off',
      [],
      null,
      () => {}
    )).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('throws a typed idle timeout when the stream stops producing frames', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      new ReadableStream({
        start() {
          // Keep the stream open without frames to exercise the idle timeout path.
        },
      }),
      { status: 200 }
    )))

    const promise = streamLocalChat(
      [{ role: 'user', content: '慢响应测试' }],
      'off',
      'off',
      [],
      null,
      () => {}
    )
    const rejection = expect(promise).rejects.toBeInstanceOf(StreamIdleTimeoutError)
    await vi.advanceTimersByTimeAsync(90_000)

    await rejection
    vi.useRealTimers()
  })

  it('throws a typed busy error when another chat stream is still running', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({
        error: 'chat_busy',
        message: '上一轮对话仍在处理中，请等待它结束后再发送。',
      }),
      { status: 429, headers: { 'Content-Type': 'application/json' } }
    )))

    await expect(streamLocalChat(
      [{ role: 'user', content: '第二轮' }],
      'off',
      'off',
      [],
      null,
      () => {}
    )).rejects.toBeInstanceOf(ChatBusyError)
  })

  it('sends thread context alongside chat stream messages', async () => {
    const encoder = new TextEncoder()
    const fetchSpy = vi.fn(async () => new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('data: ' + JSON.stringify({ contractVersion: 1, done: true }) + '\n\n'))
          controller.close()
        },
      }),
      { status: 200 }
    ))
    vi.stubGlobal('fetch', fetchSpy)

    await streamLocalChat(
      [{ role: 'user', content: '继续这个话题' }],
      'conservative',
      'summary',
      [],
      { title: '枫弋札记发布', summary: '目标：把文章发布到 Hugo 博客。' },
      () => {},
    )

    const [, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit]
    expect(JSON.parse(String(init.body))).toMatchObject({
      threadContext: {
        title: '枫弋札记发布',
        summary: '目标：把文章发布到 Hugo 博客。',
      },
    })
  })

  it('posts child job specs to the spawn endpoint', async () => {
    const fetchSpy = vi.fn(async () => new Response(JSON.stringify({
      ok: true,
      id: 'job-parent',
      spawned: 1,
      children: [{
        id: 'job-child',
        title: '[子] 检查计划入口',
        kind: 'review',
        prompt: '检查计划卡',
        status: 'queued',
        result: '',
        createdAt: '2026-06-12T10:00:00',
        updatedAt: '2026-06-12T10:00:00',
        parentJobId: 'job-parent',
      }],
    }), { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)

    const result = await spawnChildJobs('job-parent', [{
      title: '检查计划入口',
      kind: 'review',
      prompt: '检查计划卡',
      autoStart: false,
    }])

    expect(result.spawned).toBe(1)
    expect(fetchSpy).toHaveBeenCalledOnce()
    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit]
    expect(String(url)).toContain('/jobs/job-parent/spawn')
    expect(JSON.parse(String(init?.body))).toEqual({
      children: [{
        title: '检查计划入口',
        kind: 'review',
        prompt: '检查计划卡',
        autoStart: false,
      }],
    })
  })

  it('loads initiative shadow logs as read-only review data', async () => {
    const fetchSpy = vi.fn(async (url: string) => {
      const path = new URL(String(url)).pathname + new URL(String(url)).search
      const payloads: Record<string, unknown> = {
        '/status': { adapter: 'local', model: 'kimi', mode: 'chat', memoryCount: 0, skillCount: 0 },
        '/settings': {},
        '/experts': { current: '', experts: [] },
        '/modes': { current: 'chat', default: 'chat', modes: [] },
        '/sessions': [],
        '/memory?include_rejected=true': [],
        '/hypotheses?status=all': { ok: true, hypotheses: [] },
        '/skills': [],
        '/proactive-touch': { enabled: false, items: [] },
        '/soul-profile': { empty: true, sections: [] },
        '/soul-files': {},
        '/journal-review?days=30': {
          configured: false,
          window: { days: 30, start: '', end: '' },
          metrics: { entries: 0, characters: 0 },
          entries: [],
          journal_emotions: {},
          session_emotions: {},
          markdown: '',
        },
        '/config/doctor': {
          ok: false,
          checkedAt: '2026-06-28T10:00:00',
          configPath: '/Users/Yivxer/Projects/Archer/archer.toml',
          summary: { error: 1, warn: 1, info: 0 },
          issues: [{
            code: 'missing_api_key',
            level: 'error',
            message: 'api.api_key 未配置',
            nextAction: '填写 API key',
          }],
          nextActions: ['填写 API key'],
        },
        '/tool-approval-audit?limit=10': {
          ok: true,
          path: '/Users/Yivxer/Library/Application Support/archer-desktop/tool-approval-audit.jsonl',
          limit: 10,
          items: [{
            timestamp: 1782630000,
            eventId: 'tool-audit-1',
            decision: 'approved',
            skillName: 'obsidian_write',
            risk: 'medium',
            policyDecision: 'confirm',
            policyReason: 'write vault',
            executed: true,
            message: 'done',
            reused: false,
          }],
        },
        '/initiative-shadow?limit=5': {
          ok: true,
          shadow: true,
          delivered: false,
          limit: 5,
          globalThrottleActive: true,
          items: [{
            id: 1,
            event_type: 'initiative_due',
            kind: 'thread_resume',
            title: '拾起未闭合话题',
            message: '上次还留着一个话题。',
            delivered: false,
            decision_trace: { reason: 'stale_open_thread' },
            created_at: '2026-06-25T10:00:00',
            feedback: '',
            archived_at: null,
          }],
        },
        '/initiative-shadow/report': {
          ok: true,
          shadow: true,
          report: {
            observation_days: 8,
            total_candidates: 12,
            daily_average: 1.5,
            feedback_count: 5,
            recognition_rate: 0.8,
            ready_for_manual_review: true,
            reasons: [],
            thresholds: {
              required_days: 7,
              max_daily_average: 3,
              min_feedback: 3,
              min_recognition_rate: 0.7,
            },
          },
        },
        '/initiative-shadow/long-term-report': {
          ok: true,
          shadow: true,
          report: {
            observed_days: 14,
            candidate_count: 12,
            ready_for_delivery_review: false,
            reasons: ['continue_shadow_observation'],
            metrics: {
              frequency: {
                daily_average: 0.857,
                max_daily_count: 2,
              },
              relevance: {
                feedback_count: 5,
                recognition_rate: 0.8,
                too_frequent_rate: 0.2,
              },
              continuity: {
                thread_resume_count: 7,
              },
            },
          },
        },
        '/initiative-shadow/delivery-gate': {
          ok: true,
          shadow: true,
          optIn: {
            enabled: false,
            updatedAt: null,
            reason: 'not_set',
          },
          gate: {
            can_enable_delivery: false,
            shadow_only: true,
            reasons: ['explicit_opt_in_required'],
            requirements: {
              required_observation_days: 14,
              explicit_opt_in: true,
              manual_review: true,
            },
            timeline: {
              first_observed_at: '2026-06-01T09:00:00',
              earliest_review_at: '2026-06-15T09:00:00',
              remaining_observation_days: 0,
            },
          },
        },
        '/initiative-shadow/review-packet': {
          ok: true,
          shadow: true,
          optIn: {
            enabled: false,
            updatedAt: null,
            reason: 'not_set',
          },
          recommendedAction: 'keep_shadow',
          manualReport: {
            observedDays: 8,
            candidateCount: 12,
            dailyAverage: 1.5,
            feedbackCount: 5,
            recognitionRate: 0.8,
            tooFrequentCount: 0,
            readyForManualReview: true,
            reasons: [],
          },
          longTermReport: {
            observedDays: 14,
            candidateCount: 12,
            firstObservedAt: '2026-06-01T09:00:00',
            readyForDeliveryReview: false,
            reasons: ['continue_shadow_observation'],
            metrics: {
              frequency: { dailyAverage: 0.857, maxDailyCount: 2 },
              relevance: { feedbackCount: 5, recognitionRate: 0.8, tooFrequentRate: 0.2 },
              continuity: { threadResumeCount: 7 },
            },
          },
          deliveryGate: {
            canEnableDelivery: false,
            shadowOnly: true,
            reasons: ['explicit_opt_in_required'],
            requirements: {
              requiredObservationDays: 14,
              explicitOptIn: true,
              manualReview: true,
            },
            timeline: {
              firstObservedAt: '2026-06-01T09:00:00',
              earliestReviewAt: '2026-06-15T09:00:00',
              remainingObservationDays: 0,
            },
          },
        },
      }
      if (path.startsWith('/reviews?period=')) {
        return new Response(JSON.stringify({
          period: path.split('=').at(-1),
          title: 'review',
          window: { days: 0, start: '', end: '' },
          metrics: { sessions: 0, user_turns: 0, memories: 0, deep_memories: 0 },
          themes: [],
          highlights: [],
          growth_markers: [],
          suggested_questions: [],
          markdown: '',
        }), { status: 200 })
      }
      return new Response(JSON.stringify(payloads[path] ?? {}), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchSpy)

    const data = await loadLocalArcher()

    expect(data.initiativeShadow.globalThrottleActive).toBe(true)
    expect(data.initiativeShadow.items).toHaveLength(1)
    expect(data.initiativeShadow.items[0]).toMatchObject({
      kind: 'thread_resume',
      delivered: false,
      decisionTrace: { reason: 'stale_open_thread' },
    })
    expect(data.initiativeShadow.report).toMatchObject({
      observationDays: 8,
      totalCandidates: 12,
      dailyAverage: 1.5,
      feedbackCount: 5,
      recognitionRate: 0.8,
      readyForManualReview: true,
      reasons: [],
      thresholds: {
        requiredDays: 7,
        maxDailyAverage: 3,
        minFeedback: 3,
        minRecognitionRate: 0.7,
      },
    })
    expect(data.initiativeShadow.longTermReport).toMatchObject({
      observedDays: 14,
      candidateCount: 12,
      readyForDeliveryReview: false,
      reasons: ['continue_shadow_observation'],
      metrics: {
        frequency: {
          dailyAverage: 0.857,
          maxDailyCount: 2,
        },
        relevance: {
          feedbackCount: 5,
          recognitionRate: 0.8,
          tooFrequentRate: 0.2,
        },
        continuity: {
          threadResumeCount: 7,
        },
      },
    })
    expect(data.initiativeShadow.deliveryGate).toMatchObject({
      canEnableDelivery: false,
      shadowOnly: true,
      reasons: ['explicit_opt_in_required'],
      requirements: {
        requiredObservationDays: 14,
        explicitOptIn: true,
        manualReview: true,
      },
      timeline: {
        firstObservedAt: '2026-06-01T09:00:00',
        earliestReviewAt: '2026-06-15T09:00:00',
        remainingObservationDays: 0,
      },
    })
    expect(data.initiativeShadow.optIn).toMatchObject({
      enabled: false,
      reason: 'not_set',
    })
    expect(data.initiativeShadow.reviewPacket).toMatchObject({
      recommendedAction: 'keep_shadow',
      optIn: { enabled: false },
      manualReport: { readyForManualReview: true },
      longTermReport: { observedDays: 14 },
      deliveryGate: { shadowOnly: true },
    })
    expect(data.configDoctor).toMatchObject({
      ok: false,
      summary: { error: 1, warn: 1, info: 0 },
      issues: [{ code: 'missing_api_key' }],
    })
    expect(data.toolApprovalAudit.items[0]).toMatchObject({
      eventId: 'tool-audit-1',
      skillName: 'obsidian_write',
      executed: true,
    })
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/config/doctor'),
      expect.any(Object),
    )
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/tool-approval-audit?limit=10'),
      expect.any(Object),
    )
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/initiative-shadow?limit=5'),
      expect.any(Object),
    )
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/initiative-shadow/report'),
      expect.any(Object),
    )
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/initiative-shadow/long-term-report'),
      expect.any(Object),
    )
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/initiative-shadow/delivery-gate'),
      expect.any(Object),
    )
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/initiative-shadow/review-packet'),
      expect.any(Object),
    )
  })
})
