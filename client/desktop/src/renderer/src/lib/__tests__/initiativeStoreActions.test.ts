import { beforeEach, expect, it, vi } from 'vitest'
import * as transport from '../../adapters/localArcher'
import { claimInitiativeReviewCandidateAction, getInitiativeStoreState, loadAllInitiative, mergeInitiativeReview, resetInitiativeStore, setInitiativePresenceAction, submitInitiativeFeedbackAction } from '../initiativeStore'
import { initiativeReviewFixture } from './initiativeFixture'

vi.mock('../../adapters/localArcher', () => ({ getJson: vi.fn(), postJson: vi.fn() }))
let review = structuredClone(initiativeReviewFixture)
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function mockReads() {
  vi.mocked(transport.getJson).mockImplementation(async (path) => {
    if (path.startsWith('/initiative-shadow?')) return review
    if (path === '/initiative-shadow/report') return { ok: true, shadow: true, report: review.report }
    if (path === '/initiative-shadow/long-term-report') return { ok: true, shadow: true, report: review.longTermReport }
    if (path === '/initiative-shadow/delivery-gate') return { ok: true, shadow: true, gate: review.deliveryGate, optIn: review.optIn }
    if (path === '/initiative-shadow/review-packet') return { ok: true, shadow: true, ...review.reviewPacket }
    if (path.startsWith('/initiative-shadow/exposure-report')) return { ok: true, shadow: true, report: review.exposureReport }
    throw new Error('Unknown synthetic read')
  })
}
beforeEach(() => {
  resetInitiativeStore(); vi.resetAllMocks(); review = structuredClone(initiativeReviewFixture)
  review.report.feedbackCount = 0; mockReads()
})

it('loads the actual six-endpoint domain instead of marking a placeholder', async () => {
  await loadAllInitiative()
  expect(getInitiativeStoreState().loadState).toBe('ready')
  expect(transport.getJson).toHaveBeenCalledTimes(6)
  expect(getInitiativeStoreState().review?.report.feedbackCount).toBe(0)
})

it('a failed endpoint retains the last coherent snapshot and marks it unavailable for writes', async () => {
  mergeInitiativeReview(review)
  vi.mocked(transport.getJson).mockRejectedValue(new Error('synthetic offline'))
  await loadAllInitiative({ force: true })
  expect(getInitiativeStoreState().review?.items).toEqual(review.items)
  expect(getInitiativeStoreState().loadState).toBe('error')
})

it('feedback refreshes statistics along with the candidate instead of only patching the item', async () => {
  mergeInitiativeReview(review)
  vi.mocked(transport.postJson).mockImplementation(async () => {
    review = { ...review, report: { ...review.report, feedbackCount: 1 } }
    return { ok: true, id: 1, feedback: 'acknowledged' }
  })
  await submitInitiativeFeedbackAction(1, 'acknowledged', 'today')
  expect(getInitiativeStoreState().review?.report.feedbackCount).toBe(1)
})

it('coalesces normal loads and ignores a forced load superseded by an older failure', async () => {
  const old = deferred<typeof review>()
  vi.mocked(transport.getJson).mockImplementationOnce(() => old.promise)
  const first = loadAllInitiative(); const second = loadAllInitiative()
  expect(transport.getJson).toHaveBeenCalledTimes(6)
  await loadAllInitiative({ force: true })
  old.reject(new Error('old unavailable')); await Promise.all([first, second])
  expect(getInitiativeStoreState().loadState).toBe('ready')
  expect(getInitiativeStoreState().loadError).toBe('')
})

it('reset discards late complete reads', async () => {
  const old = deferred<typeof review>()
  vi.mocked(transport.getJson).mockImplementationOnce(() => old.promise)
  const first = loadAllInitiative(); resetInitiativeStore(); old.resolve(review); await first
  expect(getInitiativeStoreState().review).toBeNull()
  expect(getInitiativeStoreState().loadState).toBe('idle')
})

it('one endpoint failure cannot publish partially refreshed statistics', async () => {
  mergeInitiativeReview(review)
  const prior = getInitiativeStoreState().review
  review = { ...review, report: { ...review.report, feedbackCount: 5 } }
  const getter = vi.mocked(transport.getJson).getMockImplementation()!
  vi.mocked(transport.getJson).mockImplementation(async (path) => {
    if (path === '/initiative-shadow/delivery-gate') throw new Error('gate unavailable')
    return getter(path)
  })
  await loadAllInitiative()
  expect(getInitiativeStoreState().review).toBe(prior)
  expect(getInitiativeStoreState().loadState).toBe('error')
})

it('feedback stays successful when the follow-up read fails, without a second POST', async () => {
  mergeInitiativeReview(review)
  vi.mocked(transport.postJson).mockResolvedValue({ ok: true, id: 1, feedback: 'acknowledged' })
  vi.mocked(transport.getJson).mockRejectedValue(new Error('read unavailable'))
  await expect(submitInitiativeFeedbackAction(1, 'acknowledged')).resolves.toBeUndefined()
  expect(transport.postJson).toHaveBeenCalledTimes(1)
  expect(getInitiativeStoreState().loadError).toBe('read unavailable')
  expect(getInitiativeStoreState().actionError).toBe('')
  expect(getInitiativeStoreState().busy).toBe(false)
})

it('writes require ready data and duplicate pending writes are blocked', async () => {
  await expect(submitInitiativeFeedbackAction(1, 'acknowledged')).rejects.toThrow('尚未读取成功')
  expect(transport.postJson).not.toHaveBeenCalled()
  mergeInitiativeReview(review)
  const receipt = deferred<{ ok: boolean }>()
  vi.mocked(transport.postJson).mockImplementationOnce(() => receipt.promise)
  const first = submitInitiativeFeedbackAction(1, 'acknowledged')
  await expect(submitInitiativeFeedbackAction(1, 'acknowledged')).rejects.toThrow('正在保存')
  receipt.resolve({ ok: true }); await first
  expect(transport.postJson).toHaveBeenCalledTimes(1)
})

it('an invalid POST receipt does not clear a candidate or invent a feedback', async () => {
  mergeInitiativeReview(review)
  const prior = getInitiativeStoreState().review
  vi.mocked(transport.postJson).mockResolvedValue({ ok: false })
  await expect(submitInitiativeFeedbackAction(1, 'acknowledged')).rejects.toThrow('未保存')
  expect(getInitiativeStoreState().review).toBe(prior)
  expect(getInitiativeStoreState().busy).toBe(false)
})

it('a late exposure receipt cannot bring a candidate back after muting', async () => {
  mergeInitiativeReview(review)
  const receipt = deferred<{ ok: boolean; item: unknown }>()
  vi.mocked(transport.postJson).mockImplementationOnce(() => receipt.promise).mockImplementationOnce(async () => {
    review = { ...review, presenceState: 'muted' }
    return { ok: true, state: 'muted', reason: 'synthetic' }
  })
  const pending = claimInitiativeReviewCandidateAction()
  await setInitiativePresenceAction('muted')
  receipt.resolve({ ok: true, item: { id: 1, kind: 'thread_resume', message: '合成候选' } }); await pending
  expect(getInitiativeStoreState().review?.presenceState).toBe('muted')
  expect(getInitiativeStoreState().reviewCandidate).toBeNull()
})

it('candidate claims share one exposure mutation and refresh its report', async () => {
  mergeInitiativeReview(review)
  const receipt = deferred<{ ok: boolean }>()
  vi.mocked(transport.postJson).mockImplementationOnce(() => receipt.promise)
  const first = claimInitiativeReviewCandidateAction(); const second = claimInitiativeReviewCandidateAction()
  expect(transport.postJson).toHaveBeenCalledTimes(1)
  receipt.resolve({ ok: true }); await Promise.all([first, second])
  expect(getInitiativeStoreState().candidateState).toBe('ready')
  expect(transport.getJson).toHaveBeenCalledTimes(6)
})
