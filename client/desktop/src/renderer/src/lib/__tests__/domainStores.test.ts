/**
 * L3.2-L3.6 — 5 个领域 store 单元测试
 *
 * 覆盖：
 * - externalStore 共享工具（createExternalStore + subscribe + setState 引用对比）
 * - memoryStore / soulStore / sessionStore / jobStore / initiativeStore
 *   的初始 state shape + merge* 注入 + reset + subscribe 通知
 *
 * 不覆盖：依赖 API 的 action（loadAll/submit/cancel 等），留给集成测试。
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import type { InitiativeEvent } from '../../../../agent/contracts'
import type {
  ConversationThread,
  InitiativeShadowReview,
  MemoryItem,
  SessionItem,
  SoulFiles,
  SoulProfileSummary,
  BackgroundJob,
} from '../../types'

import {
  createExternalStore,
} from '../externalStore'
import {
  getMemoryStoreState,
  mergeMemoryItems,
  resetMemoryStore,
  subscribeMemoryStore,
} from '../memoryStore'
import {
  getSoulStoreState,
  loadAllSoul,
  resetSoulStore,
  subscribeSoulStore,
} from '../soulStore'
import {
  clearSessionDetail,
  getSessionStoreState,
  mergeSessionItems,
  resetSessionStore,
  searchSessions,
  subscribeSessionStore,
} from '../sessionStore'
import {
  clearJobDetail,
  getJobStoreState,
  mergeJobItems,
  mergeJobEvent,
  resetJobStore,
  subscribeJobStore,
} from '../jobStore'
import {
  getInitiativeStoreState,
  loadAllInitiative,
  mergeInitiativeReview,
  mergeSseInitiativeEvent,
  resetInitiativeStore,
  subscribeInitiativeStore,
} from '../initiativeStore'
import {
  getCurrentThread,
  getThreadStoreState,
  mergeThreadItems,
  resetThreadStore,
  setCurrentThread,
  subscribeThreadStore,
  upsertThreadFromSave,
} from '../threadStore'


vi.mock('../../adapters/soulAdapter', () => ({
  fetchSoulProfile: vi.fn(async () => soulProfile),
  fetchSoulFiles: vi.fn(async () => soulFiles),
  fetchVaultReflections: vi.fn(async () => ({ ok: true, reflections: [] })),
}))

// ───────────────────────── 测试夹具 ─────────────────────────

const memoryItem: MemoryItem = {
  id: 1,
  status: 'pending',
  type: 'insight',
  content: '测试记忆',
  confidence: '0.8',
  source: 'extract',
  depth: 3,
  blockType: 'insight',
}

const sessionItem: SessionItem = {
  id: 'sess-1',
  title: '测试会话',
  date: '2026-07-03',
  turns: 2,
  tone: 'calm',
}

const soulProfile: SoulProfileSummary = {
  empty: false,
  sections: [{ id: 'core', label: '核心', items: ['test'] }],
}

const soulFiles: SoulFiles = {
  'SOUL.md': '# Soul',
  'MEMORY.md': '# Memory',
  'COVENANT.md': '# Covenant',
  'PRESENCE.md': '# Presence',
}

const initiativeReview: InitiativeShadowReview = {
  ok: true,
  shadow: true,
  delivered: false,
  limit: 5,
  globalThrottleActive: false,
  presenceState: 'idle',
  items: [],
  exposureReport: {
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
  },
  report: {
    observationDays: 0,
    totalCandidates: 0,
    dailyAverage: 0,
    feedbackCount: 0,
    recognitionRate: 0,
    readyForManualReview: false,
    reasons: [],
    thresholds: { requiredDays: 7, maxDailyAverage: 3, minFeedback: 3, minRecognitionRate: 0.7 },
  },
  longTermReport: {
    observedDays: 0,
    candidateCount: 0,
    readyForDeliveryReview: false,
    reasons: [],
    metrics: {
      frequency: { dailyAverage: 0, maxDailyCount: 0 },
      relevance: { feedbackCount: 0, recognitionRate: 0, tooFrequentRate: 0 },
      continuity: { threadResumeCount: 0 },
    },
  },
  deliveryGate: {
    canEnableDelivery: false,
    shadowOnly: true,
    reasons: [],
    requirements: { requiredObservationDays: 7, explicitOptIn: true, manualReview: true },
    timeline: { firstObservedAt: null, earliestReviewAt: null, remainingObservationDays: 7 },
  },
  optIn: { enabled: false, updatedAt: null, reason: '' },
  reviewPacket: {
    recommendedAction: 'keep_shadow',
    optIn: { enabled: false, updatedAt: null, reason: '' },
    manualReport: {
      observationDays: 0,
      totalCandidates: 0,
      dailyAverage: 0,
      feedbackCount: 0,
      recognitionRate: 0,
      readyForManualReview: false,
      reasons: [],
      thresholds: { requiredDays: 7, maxDailyAverage: 3, minFeedback: 3, minRecognitionRate: 0.7 },
    },
    longTermReport: {
      observedDays: 0,
      candidateCount: 0,
      readyForDeliveryReview: false,
      reasons: [],
      metrics: {
        frequency: { dailyAverage: 0, maxDailyCount: 0 },
        relevance: { feedbackCount: 0, recognitionRate: 0, tooFrequentRate: 0 },
        continuity: { threadResumeCount: 0 },
      },
    },
    deliveryGate: {
      canEnableDelivery: false,
      shadowOnly: true,
      reasons: [],
      requirements: { requiredObservationDays: 7, explicitOptIn: true, manualReview: true },
      timeline: { firstObservedAt: null, earliestReviewAt: null, remainingObservationDays: 7 },
    },
  },
}

function makeInitiativeEvent(overrides: Partial<InitiativeEvent> = {}): InitiativeEvent {
  return {
    type: 'initiative.event',
    id: 'initiative-100',
    sessionId: 'sess-test',
    traceId: 'trace-test',
    createdAt: '2026-07-03T10:00:00',
    kind: 'reflection',
    title: '测试候选',
    message: '测试消息',
    shadow: true,
    delivered: false,
    decisionTrace: {},
    ...overrides,
  }
}

const thread: ConversationThread = {
  id: 'thread-1',
  title: '测试话题',
  summary: '目标：测试 threadStore',
  createdAt: '2026-07-03T10:00:00',
  updatedAt: '2026-07-03T10:00:00',
  sessionIds: ['sess-1'],
}

// ───────────────────────── externalStore 共享工具 ─────────────────────────

describe('externalStore — 共享工具', () => {
  it('createExternalStore 初始 state', () => {
    const store = createExternalStore<{ count: number }>({ count: 0 })
    expect(store.getState()).toEqual({ count: 0 })
  })

  it('setState 不可变更新 + 通知 listener', () => {
    const store = createExternalStore<{ count: number }>({ count: 0 })
    let calls = 0
    const unsub = store.subscribe(() => { calls += 1 })
    store.setState((s) => ({ ...s, count: 1 }))
    expect(store.getState().count).toBe(1)
    expect(calls).toBe(1)
    unsub()
  })

  it('setState 引用相同时跳过通知', () => {
    const store = createExternalStore<{ count: number }>({ count: 0 })
    let calls = 0
    store.subscribe(() => { calls += 1 })
    store.setState((s) => s) // 返回同一引用
    expect(calls).toBe(0)
  })

  it('subscribe 取消订阅后不再通知', () => {
    const store = createExternalStore<{ count: number }>({ count: 0 })
    let calls = 0
    const unsub = store.subscribe(() => { calls += 1 })
    unsub()
    store.setState((s) => ({ ...s, count: 1 }))
    expect(calls).toBe(0)
  })

  it('多个 listener 独立通知', () => {
    const store = createExternalStore<{ count: number }>({ count: 0 })
    let a = 0
    let b = 0
    store.subscribe(() => { a += 1 })
    store.subscribe(() => { b += 1 })
    store.setState((s) => ({ ...s, count: 1 }))
    expect(a).toBe(1)
    expect(b).toBe(1)
  })
})

// ───────────────────────── memoryStore ─────────────────────────

describe('memoryStore — L3.2', () => {
  beforeEach(() => {
    resetMemoryStore()
  })

  it('初始 state shape', () => {
    const state = getMemoryStoreState()
    expect(state.items).toEqual([])
    expect(state.stats).toBeNull()
    expect(state.groups).toEqual([])
    expect(state.loadState).toBe('idle')
    expect(state.error).toBe('')
    expect(state.busyIds).toBeInstanceOf(Set)
    expect(state.busyIds.size).toBe(0)
  })

  it('mergeMemoryItems 注入 items', () => {
    mergeMemoryItems([memoryItem])
    expect(getMemoryStoreState().items).toEqual([memoryItem])
  })

  it('mergeMemoryItems 二次注入替换（非追加）', () => {
    mergeMemoryItems([memoryItem])
    mergeMemoryItems([{ ...memoryItem, id: 2 }])
    expect(getMemoryStoreState().items).toHaveLength(1)
    expect(getMemoryStoreState().items[0].id).toBe(2)
  })

  it('resetMemoryStore 恢复初始 state', () => {
    mergeMemoryItems([memoryItem])
    resetMemoryStore()
    expect(getMemoryStoreState().items).toEqual([])
  })

  it('subscribeMemoryStore 在 merge 时通知', () => {
    let calls = 0
    const unsub = subscribeMemoryStore(() => { calls += 1 })
    mergeMemoryItems([memoryItem])
    expect(calls).toBe(1)
    unsub()
  })

  it('subscribeMemoryStore 取消订阅后不通知', () => {
    let calls = 0
    const unsub = subscribeMemoryStore(() => { calls += 1 })
    unsub()
    mergeMemoryItems([memoryItem])
    expect(calls).toBe(0)
  })
})

// ───────────────────────── soulStore ─────────────────────────

describe('soulStore — L3.3', () => {
  beforeEach(() => {
    resetSoulStore()
  })

  it('初始 state shape', () => {
    const state = getSoulStoreState()
    expect(state.profile).toBeNull()
    expect(state.files).toEqual({})
    expect(state.reflections).toEqual([])
    expect(state.loadState).toBe('idle')
    expect(state.error).toBe('')
    expect(state.importing).toBe(false)
    expect(state.importMessage).toBe('')
  })

  it('resetSoulStore 恢复初始 state', async () => {
    await loadAllSoul()
    resetSoulStore()
    expect(getSoulStoreState().profile).toBeNull()
    expect(getSoulStoreState().files).toEqual({})
  })

  it('subscribeSoulStore 在 HTTP 加载时通知', async () => {
    let calls = 0
    const unsub = subscribeSoulStore(() => { calls += 1 })
    await loadAllSoul()
    expect(calls).toBe(2)
    unsub()
  })
})

// ───────────────────────── sessionStore ─────────────────────────

describe('sessionStore — L3.4', () => {
  beforeEach(() => {
    resetSessionStore()
  })

  it('初始 state shape', () => {
    const state = getSessionStoreState()
    expect(state.items).toEqual([])
    expect(state.currentDetail).toBeNull()
    expect(state.searchResults).toEqual([])
    expect(state.searchQuery).toBe('')
    expect(state.loadState).toBe('idle')
    expect(state.detailState).toBe('idle')
    expect(state.searchState).toBe('idle')
    expect(state.error).toBe('')
  })

  it('mergeSessionItems 注入 items 并标记 ready', () => {
    mergeSessionItems([sessionItem])
    expect(getSessionStoreState().items).toEqual([sessionItem])
    expect(getSessionStoreState().loadState).toBe('ready')
  })

  it('clearSessionDetail 清空详情', () => {
    // 模拟已有详情（不通过 API，直接测 clear 逻辑）
    mergeSessionItems([sessionItem])
    clearSessionDetail()
    expect(getSessionStoreState().currentDetail).toBeNull()
    expect(getSessionStoreState().detailState).toBe('idle')
  })

  it('searchSessions 空查询清空结果', async () => {
    // 先注入非空状态
    mergeSessionItems([sessionItem])
    await searchSessions('   ')
    expect(getSessionStoreState().searchResults).toEqual([])
    expect(getSessionStoreState().searchQuery).toBe('')
    expect(getSessionStoreState().searchState).toBe('idle')
  })

  it('resetSessionStore 恢复初始 state', () => {
    mergeSessionItems([sessionItem])
    resetSessionStore()
    expect(getSessionStoreState().items).toEqual([])
  })

  it('subscribeSessionStore 在 merge 时通知', () => {
    let calls = 0
    const unsub = subscribeSessionStore(() => { calls += 1 })
    mergeSessionItems([sessionItem])
    expect(calls).toBe(1)
    unsub()
  })
})

// ───────────────────────── jobStore ─────────────────────────

describe('jobStore — L3.5', () => {
  const serverJob: BackgroundJob = {
    id: 'job-1',
    title: '服务端任务',
    kind: 'chat',
    prompt: '执行任务',
    status: 'queued',
    result: '',
    createdAt: '2026-07-15T00:00:00Z',
    updatedAt: '2026-07-15T00:00:00Z',
  }

  beforeEach(() => {
    resetJobStore()
  })

  it('初始 state shape', () => {
    const state = getJobStoreState()
    expect(state.jobs).toEqual([])
    expect(state.currentDetail).toBeNull()
    expect(state.loadState).toBe('idle')
    expect(state.detailState).toBe('idle')
    expect(state.error).toBe('')
    expect(state.busyIds).toBeInstanceOf(Set)
    expect(state.busyIds.size).toBe(0)
  })

  it('mergeJobEvent 对未知 job 忽略（不追加）', () => {
    const merged = mergeJobEvent('job-unknown', { status: 'running' })
    expect(getJobStoreState().jobs).toEqual([])
    expect(merged).toBe(false)
  })

  it('mergeJobEvent 对已知 job 局部更新', () => {
    mergeJobItems([serverJob])
    const merged = mergeJobEvent('job-1', { status: 'running', result: '服务端 SSE 进度' })

    expect(getJobStoreState().jobs).toEqual([{
      ...serverJob,
      status: 'running',
      result: '服务端 SSE 进度',
    }])
    expect(merged).toBe(true)
  })

  it('clearJobDetail 清空详情', () => {
    clearJobDetail()
    expect(getJobStoreState().currentDetail).toBeNull()
    expect(getJobStoreState().detailState).toBe('idle')
  })

  it('resetJobStore 恢复初始 state', () => {
    resetJobStore()
    expect(getJobStoreState().jobs).toEqual([])
  })

  it('subscribeJobStore 通知机制', () => {
    let calls = 0
    const unsub = subscribeJobStore(() => { calls += 1 })
    // mergeJobEvent 对空列表不会触发 setState（返回同一引用）
    mergeJobEvent('job-x', { status: 'running' })
    expect(calls).toBe(0) // 列表为空时 mergeJobEvent 不变更 state
    unsub()
  })
})

// ───────────────────────── initiativeStore ─────────────────────────

describe('initiativeStore — L3.6（只读，Part 8 边界）', () => {
  beforeEach(() => {
    resetInitiativeStore()
  })

  it('初始 state shape', () => {
    const state = getInitiativeStoreState()
    expect(state.review).toBeNull()
    expect(state.loadState).toBe('idle')
    expect(state.error).toBe('')
  })

  it('mergeInitiativeReview 注入 review 并标记 ready', () => {
    mergeInitiativeReview(initiativeReview)
    expect(getInitiativeStoreState().review).toEqual(initiativeReview)
    expect(getInitiativeStoreState().loadState).toBe('ready')
  })

  it('loadAllInitiative 在 review 缺失时标记 loading', async () => {
    await loadAllInitiative()
    expect(getInitiativeStoreState().loadState).toBe('loading')
  })

  it('loadAllInitiative 在 review 已存在时标记 ready', async () => {
    mergeInitiativeReview(initiativeReview)
    await loadAllInitiative()
    expect(getInitiativeStoreState().loadState).toBe('ready')
  })

  it('mergeSseInitiativeEvent 在 review 缺失时忽略', () => {
    mergeSseInitiativeEvent(makeInitiativeEvent())
    expect(getInitiativeStoreState().review).toBeNull()
  })

  it('mergeSseInitiativeEvent 在 review 已存在时合并 shadow 候选', () => {
    mergeInitiativeReview(initiativeReview)
    mergeSseInitiativeEvent(makeInitiativeEvent())
    const state = getInitiativeStoreState()
    expect(state.review?.items).toHaveLength(1)
    expect(state.review?.items[0].id).toBe(100)
    expect(state.review?.items[0].title).toBe('测试候选')
  })

  it('mergeSseInitiativeEvent 过滤 delivered=true 的事件（不写入）', () => {
    mergeInitiativeReview(initiativeReview)
    mergeSseInitiativeEvent(makeInitiativeEvent({ delivered: true }))
    expect(getInitiativeStoreState().review?.items).toHaveLength(0)
  })

  it('mergeSseInitiativeEvent 过滤 shadow=false 的事件', () => {
    mergeInitiativeReview(initiativeReview)
    mergeSseInitiativeEvent(makeInitiativeEvent({ shadow: false }))
    expect(getInitiativeStoreState().review?.items).toHaveLength(0)
  })

  it('mergeSseInitiativeEvent 同 id 去重', () => {
    mergeInitiativeReview(initiativeReview)
    mergeSseInitiativeEvent(makeInitiativeEvent())
    mergeSseInitiativeEvent(makeInitiativeEvent())
    expect(getInitiativeStoreState().review?.items).toHaveLength(1)
  })

  it('resetInitiativeStore 恢复初始 state', () => {
    mergeInitiativeReview(initiativeReview)
    resetInitiativeStore()
    expect(getInitiativeStoreState().review).toBeNull()
    expect(getInitiativeStoreState().loadState).toBe('idle')
  })

  it('subscribeInitiativeStore 在 merge 时通知', () => {
    let calls = 0
    const unsub = subscribeInitiativeStore(() => { calls += 1 })
    mergeInitiativeReview(initiativeReview)
    expect(calls).toBe(1)
    unsub()
  })

  it('subscribeInitiativeStore 取消订阅后不通知', () => {
    let calls = 0
    const unsub = subscribeInitiativeStore(() => { calls += 1 })
    unsub()
    mergeInitiativeReview(initiativeReview)
    expect(calls).toBe(0)
  })
})

// ───────────────────────── 跨 store 隔离验证 ─────────────────────────

describe('跨 store 隔离', () => {
  beforeEach(() => {
    resetMemoryStore()
    resetSoulStore()
    resetSessionStore()
    resetJobStore()
    resetInitiativeStore()
    resetThreadStore()
  })

  it('5 个 store 重置后互不影响', async () => {
    mergeMemoryItems([memoryItem])
    await loadAllSoul()
    mergeSessionItems([sessionItem])
    mergeInitiativeReview(initiativeReview)

    // 重置 memoryStore 不影响其他 store
    resetMemoryStore()
    expect(getMemoryStoreState().items).toEqual([])
    expect(getSoulStoreState().profile).toEqual(soulProfile)
    expect(getSessionStoreState().items).toEqual([sessionItem])
    expect(getInitiativeStoreState().review).toEqual(initiativeReview)
  })
})

// ───────────────────────── threadStore ─────────────────────────

describe('threadStore — L3.8（ConversationThread 连续性契约）', () => {
  beforeEach(() => {
    resetThreadStore()
  })

  it('初始 state shape', () => {
    const state = getThreadStoreState()
    expect(state.items).toEqual([])
    expect(state.currentThreadId).toBeNull()
    expect(state.loadState).toBe('idle')
    expect(state.error).toBe('')
  })

  it('mergeThreadItems 注入 items 并标记 ready', () => {
    mergeThreadItems([thread])
    expect(getThreadStoreState().items).toEqual([thread])
    expect(getThreadStoreState().loadState).toBe('ready')
  })

  it('mergeThreadItems 保留已存在的 currentThreadId', () => {
    mergeThreadItems([thread])
    setCurrentThread('thread-1')
    // 重新 merge（loadLocalArcher refresh），currentThreadId 应保留
    mergeThreadItems([{ ...thread, summary: '更新后' }])
    expect(getThreadStoreState().currentThreadId).toBe('thread-1')
  })

  it('mergeThreadItems 清空不存在的 currentThreadId', () => {
    mergeThreadItems([thread])
    setCurrentThread('thread-1')
    // merge 后 thread-1 不在新列表中
    mergeThreadItems([{ ...thread, id: 'thread-2' }])
    expect(getThreadStoreState().currentThreadId).toBeNull()
  })

  it('setCurrentThread 设置/清空当前 thread', () => {
    mergeThreadItems([thread])
    setCurrentThread('thread-1')
    expect(getThreadStoreState().currentThreadId).toBe('thread-1')
    setCurrentThread(null)
    expect(getThreadStoreState().currentThreadId).toBeNull()
  })

  it('upsertThreadFromSave 新 thread 追加到头部', () => {
    mergeThreadItems([thread])
    const newThread = { ...thread, id: 'thread-2', title: '新话题' }
    upsertThreadFromSave(newThread)
    expect(getThreadStoreState().items).toHaveLength(2)
    expect(getThreadStoreState().items[0].id).toBe('thread-2')
  })

  it('upsertThreadFromSave 已有 thread 替换（更新 summary/sessionIds）', () => {
    mergeThreadItems([thread])
    const updated = { ...thread, summary: '更新摘要', sessionIds: ['sess-1', 'sess-2'] }
    upsertThreadFromSave(updated)
    expect(getThreadStoreState().items).toHaveLength(1)
    expect(getThreadStoreState().items[0].summary).toBe('更新摘要')
    expect(getThreadStoreState().items[0].sessionIds).toEqual(['sess-1', 'sess-2'])
  })

  it('getCurrentThread 返回当前活跃 thread', () => {
    mergeThreadItems([thread])
    setCurrentThread('thread-1')
    expect(getCurrentThread()).toEqual(thread)
  })

  it('getCurrentThread 无 currentThreadId 时返回 null', () => {
    mergeThreadItems([thread])
    expect(getCurrentThread()).toBeNull()
  })

  it('getCurrentThread currentThreadId 不在 items 中时返回 null', () => {
    mergeThreadItems([thread])
    setCurrentThread('thread-x')
    expect(getCurrentThread()).toBeNull()
  })

  it('resetThreadStore 恢复初始 state', () => {
    mergeThreadItems([thread])
    setCurrentThread('thread-1')
    resetThreadStore()
    expect(getThreadStoreState().items).toEqual([])
    expect(getThreadStoreState().currentThreadId).toBeNull()
  })

  it('subscribeThreadStore 在 merge 时通知', () => {
    let calls = 0
    const unsub = subscribeThreadStore(() => { calls += 1 })
    mergeThreadItems([thread])
    expect(calls).toBe(1)
    unsub()
  })

  it('subscribeThreadStore 在 setCurrentThread 时通知', () => {
    mergeThreadItems([thread])
    let calls = 0
    const unsub = subscribeThreadStore(() => { calls += 1 })
    setCurrentThread('thread-1')
    expect(calls).toBe(1)
    unsub()
  })

  it('subscribeThreadStore 取消订阅后不通知', () => {
    let calls = 0
    const unsub = subscribeThreadStore(() => { calls += 1 })
    unsub()
    mergeThreadItems([thread])
    expect(calls).toBe(0)
  })
})
