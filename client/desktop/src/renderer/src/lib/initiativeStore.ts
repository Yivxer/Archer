/**
 * L3.6 — initiativeStore（只读，Part 8 边界）
 *
 * 真值来源：loadLocalArcher 注入（合并 5 端点）+ SSE initiative.event 增量 + 3 个 mutation 动作
 * 订阅者：TodayPage、main.tsx（SSE 合并）、ReviewPanels
 *
 * Part 8 边界：只读消费 shadow 事件，不写入聊天（与 L2.5 一致）。
 * initiativeStore 不暴露任何"写 shadow / 推送到聊天"的 action。
 *
 * 契约：docs/api-contract.md §「initiativeStore（L3.6，只读）」
 */

import type { InitiativeEvent } from '../../../agent/contracts'
import {
  claimInitiativeReviewCandidate,
  setInitiativeDeliveryOptIn,
  setInitiativePresence,
  submitInitiativeFeedback,
} from '../adapters/localArcher'
import type { InitiativeShadowReview, InitiativeShadowReviewCandidate } from '../types'
import { transitionThreadClue, type ThreadClueStatus } from '../adapters/threadClues'
import { createExternalStore, useExternalStore, type LoadState } from './externalStore'
import { mergeInitiativeShadowEvent } from './initiativeShadow'

// ───────────────────────── State ─────────────────────────

export type InitiativeStoreState = {
  review: InitiativeShadowReview | null
  reviewCandidate: InitiativeShadowReviewCandidate | null
  candidateState: LoadState
  loadState: LoadState
  error: string
}

const initialState: InitiativeStoreState = {
  review: null,
  reviewCandidate: null,
  candidateState: 'idle',
  loadState: 'idle',
  error: '',
}

// ───────────────────────── Store 单例 ─────────────────────────

const store = createExternalStore<InitiativeStoreState>(initialState)

export function getInitiativeStoreState(): InitiativeStoreState {
  return store.getState()
}

export function subscribeInitiativeStore(listener: () => void): () => void {
  return store.subscribe(listener)
}

// ───────────────────────── Actions ─────────────────────────

/**
 * 全量加载入口（占位）。
 *
 * initiativeShadow 的 5 端点合并由 loadLocalArcher 完成，
 * 结果通过 mergeInitiativeReview 注入。loadAll 只负责标记状态：
 * - review 已存在 → 标记 ready
 * - review 缺失 → 标记 loading（等待 mergeInitiativeReview）
 */
export async function loadAllInitiative(): Promise<void> {
  const current = store.getState()
  if (current.review) {
    store.setState((s) => ({ ...s, loadState: 'ready', error: '' }))
    return
  }
  store.setState((s) => ({ ...s, loadState: 'loading', error: '' }))
}

/**
 * 由 loadLocalArcher 注入合并后的 review（不触发 API）。
 */
export function mergeInitiativeReview(review: InitiativeShadowReview): void {
  store.setState((s) => ({
    ...s,
    review,
    loadState: 'ready',
    error: '',
  }))
}

/**
 * 提交 shadow 候选反馈（acknowledged / too_frequent）。
 * 成功后局部更新 items 中对应条目的 feedback 字段，不重拉全量。
 */
export async function submitInitiativeFeedbackAction(
  id: number,
  feedback: 'acknowledged' | 'too_frequent',
  surface?: 'chat_workspace' | 'today',
): Promise<void> {
  try {
    await submitInitiativeFeedback(id, feedback, surface)
    store.setState((s) => {
      if (!s.review) return s
      const items = s.review.items.map((item) =>
        item.id === id ? { ...item, feedback } : item,
      )
      return {
        ...s,
        review: { ...s.review, items },
        reviewCandidate: s.reviewCandidate?.item?.id === id ? null : s.reviewCandidate,
      }
    })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

export async function transitionThreadClueAction(id: number, status: ThreadClueStatus): Promise<void> {
  await transitionThreadClue(id, status)
  store.setState((s) => ({
    ...s,
    review: s.review ? {
      ...s.review,
      items: s.review.items.filter((item) => Number(item.decisionTrace.threadId) !== id),
    } : null,
    reviewCandidate: Number(s.reviewCandidate?.item?.decisionTrace.threadId) === id ? null : s.reviewCandidate,
  }))
}

/**
 * 设置 presence（idle / muted）。
 * 成功后更新 review.presenceState。
 */
export async function setInitiativePresenceAction(
  state: 'idle' | 'muted',
  surface?: 'chat_workspace' | 'today',
): Promise<void> {
  try {
    const result = await setInitiativePresence(state, surface)
    store.setState((s) => {
      if (!s.review) return s
      return {
        ...s,
        review: { ...s.review, presenceState: result.state },
        reviewCandidate: result.state === 'muted' ? null : s.reviewCandidate,
      }
    })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

export async function claimInitiativeReviewCandidateAction(): Promise<void> {
  store.setState((s) => ({ ...s, candidateState: 'loading', error: '' }))
  try {
    const result = await claimInitiativeReviewCandidate()
    store.setState((s) => ({
      ...s,
      reviewCandidate: result,
      candidateState: 'ready',
      error: '',
    }))
  } catch (err) {
    store.setState((s) => ({
      ...s,
      reviewCandidate: null,
      candidateState: 'error',
      error: err instanceof Error ? err.message : String(err),
    }))
  }
}

/**
 * 开启/撤销 delivery opt-in。
 * 成功后更新 review.optIn + review.deliveryGate。
 */
export async function setInitiativeDeliveryOptInAction(
  enabled: boolean,
): Promise<void> {
  try {
    const result = await setInitiativeDeliveryOptIn(enabled)
    store.setState((s) => {
      if (!s.review) return s
      return {
        ...s,
        review: {
          ...s.review,
          optIn: result.optIn,
          deliveryGate: result.gate,
        },
      }
    })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

/**
 * 由 SSE initiative.event 合并到 review.items。
 * 复用 lib/initiativeShadow.ts 的 mergeInitiativeShadowEvent（去重 + shadow/delivered 过滤）。
 *
 * Part 8 边界：只更新 store 内部状态，不写入聊天流。
 */
export function mergeSseInitiativeEvent(event: InitiativeEvent): void {
  store.setState((s) => {
    if (!s.review) return s
    return {
      ...s,
      review: mergeInitiativeShadowEvent(s.review, event),
    }
  })
}

/**
 * 重置 store。
 */
export function resetInitiativeStore(): void {
  store.setState(() => initialState)
}

// ───────────────────────── React hook ─────────────────────────

export function useInitiativeStore<U>(selector: (state: InitiativeStoreState) => U): U {
  return useExternalStore(store, selector)
}
