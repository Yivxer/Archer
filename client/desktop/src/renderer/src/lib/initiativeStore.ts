/** Coherent server-owned Part 8 observation; no automatic delivery or authority. */
import type { InitiativeEvent } from '../../../agent/contracts'
import * as api from '../adapters/initiativeAdapter'
import type { InitiativeShadowReview, InitiativeShadowReviewCandidate } from '../types'
import { transitionThreadClue, type ThreadClueStatus } from '../adapters/threadClues'
import { createExternalStore, useExternalStore, type LoadState } from './externalStore'

export type InitiativeStoreState = {
  review: InitiativeShadowReview | null
  reviewCandidate: InitiativeShadowReviewCandidate | null
  candidateState: LoadState
  loadState: LoadState
  error: string
  loadError: string
  candidateError: string
  actionError: string
  busy: boolean
}
const initialState: InitiativeStoreState = {
  review: null, reviewCandidate: null, candidateState: 'idle', loadState: 'idle',
  error: '', loadError: '', candidateError: '', actionError: '', busy: false,
}
const store = createExternalStore<InitiativeStoreState>(initialState)
let loadGeneration = 0
let candidateGeneration = 0
let resetGeneration = 0
let pendingLoad: Promise<void> | null = null
let pendingCandidate: Promise<void> | null = null
const seenEvents = new Set<string>()
const errorText = (error: unknown): string => error instanceof Error ? error.message : String(error)

export function getInitiativeStoreState(): InitiativeStoreState { return store.getState() }
export function subscribeInitiativeStore(listener: () => void): () => void { return store.subscribe(listener) }

export function loadAllInitiative(options: { force?: boolean } = {}): Promise<void> {
  if (pendingLoad && !options.force) return pendingLoad
  const generation = ++loadGeneration
  store.setState((s) => ({ ...s, loadState: 'loading', loadError: '' }))
  pendingLoad = readReview(generation)
  return pendingLoad
}

async function readReview(generation: number): Promise<void> {
  try {
    const review = await api.fetchInitiativeReview()
    if (generation !== loadGeneration) return
    mergeInitiativeReview(review)
  } catch (error) {
    if (generation !== loadGeneration) return
    store.setState((s) => ({ ...s, loadState: 'error', loadError: errorText(error), error: errorText(error) }))
  } finally {
    if (generation === loadGeneration) pendingLoad = null
  }
}

/** Only committed by the domain reader or synthetic tests, never the overall adapter. */
export function mergeInitiativeReview(review: InitiativeShadowReview): void {
  store.setState((s) => ({
    ...s, review, loadState: 'ready', loadError: '', error: '',
    reviewCandidate: review.presenceState === 'muted' ? null : s.reviewCandidate,
  }))
}

function assertReceipt(result: { ok: boolean }): void {
  if (!result.ok) throw new Error('操作未保存，请刷新后重试')
}

/** POST success survives a failed follow-up read; never synthesize reports or resend it. */
async function mutate(action: () => Promise<{ ok: boolean }>): Promise<void> {
  const state = store.getState()
  if (state.busy) throw new Error('正在保存，请稍后再试')
  if (state.loadState !== 'ready') throw new Error('观察数据尚未读取成功，请刷新后重试')
  const epoch = resetGeneration
  store.setState((s) => ({ ...s, busy: true, actionError: '' }))
  try {
    const result = await action()
    assertReceipt(result)
    if (epoch !== resetGeneration) return
    candidateGeneration += 1
    pendingCandidate = null
    store.setState((s) => ({ ...s, reviewCandidate: null, candidateState: s.candidateState === 'idle' ? 'idle' : 'ready', candidateError: '' }))
    await loadAllInitiative({ force: true })
  } catch (error) {
    if (epoch === resetGeneration) store.setState((s) => ({ ...s, actionError: errorText(error), error: errorText(error) }))
    throw error
  } finally {
    if (epoch === resetGeneration) store.setState((s) => ({ ...s, busy: false }))
  }
}

export async function submitInitiativeFeedbackAction(id: number, feedback: 'acknowledged' | 'too_frequent', surface?: 'chat_workspace' | 'today'): Promise<void> {
  await mutate(() => api.submitInitiativeFeedback(id, feedback, surface))
}

export async function transitionThreadClueAction(id: number, status: ThreadClueStatus): Promise<void> {
  await mutate(() => transitionThreadClue(id, status))
}

export async function setInitiativePresenceAction(state: 'idle' | 'muted', surface?: 'chat_workspace' | 'today'): Promise<void> {
  await mutate(() => api.setInitiativePresence(state, surface))
}

export async function setInitiativeDeliveryOptInAction(enabled: boolean): Promise<void> {
  await mutate(() => api.setInitiativeDeliveryOptIn(enabled))
}

/** Claiming is an exposure mutation; coalesce to one server receipt and refresh reports. */
export function claimInitiativeReviewCandidateAction(): Promise<void> {
  if (pendingCandidate) return pendingCandidate
  const state = store.getState()
  if (state.loadState !== 'ready' || state.busy || state.review?.presenceState === 'muted') return Promise.resolve()
  const generation = ++candidateGeneration
  const epoch = resetGeneration
  store.setState((s) => ({ ...s, candidateState: 'loading', candidateError: '' }))
  pendingCandidate = readCandidate(generation, epoch)
  return pendingCandidate
}

async function readCandidate(generation: number, epoch: number): Promise<void> {
  try {
    const result = await api.claimInitiativeReviewCandidate()
    if (generation !== candidateGeneration || epoch !== resetGeneration) return
    assertReceipt(result)
    store.setState((s) => ({ ...s, reviewCandidate: result, candidateState: 'ready', candidateError: '' }))
    await loadAllInitiative({ force: true })
  } catch (error) {
    if (generation !== candidateGeneration || epoch !== resetGeneration) return
    store.setState((s) => ({ ...s, reviewCandidate: null, candidateState: 'error', candidateError: errorText(error), error: errorText(error) }))
  } finally {
    if (generation === candidateGeneration) pendingCandidate = null
  }
}

/** SSE is a refresh hint; reports and gates stay a single HTTP projection. */
export function mergeSseInitiativeEvent(event: InitiativeEvent): void {
  if (!event.shadow || event.delivered || seenEvents.has(event.id)) return
  seenEvents.add(event.id)
  if (seenEvents.size > 100) seenEvents.delete(seenEvents.values().next().value!)
  void loadAllInitiative({ force: true })
}

export function resetInitiativeStore(): void {
  loadGeneration += 1
  candidateGeneration += 1
  resetGeneration += 1
  pendingLoad = null
  pendingCandidate = null
  seenEvents.clear()
  store.setState(() => initialState)
}

export function useInitiativeStore<U>(selector: (state: InitiativeStoreState) => U): U { return useExternalStore(store, selector) }
