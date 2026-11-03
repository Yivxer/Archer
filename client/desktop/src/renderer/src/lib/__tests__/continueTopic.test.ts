import { beforeEach, expect, it, vi } from 'vitest'
import type { ConversationThread } from '../../types'

const api = vi.hoisted(() => ({
  listLocalThreads: vi.fn(),
  ensureLocalThread: vi.fn(),
  addLocalSessionToThread: vi.fn(),
  createLocalThread: vi.fn(),
  updateLocalThread: vi.fn(),
}))
vi.mock('../../adapters/conversationAdapter', () => api)

import { continueTopicFromReview } from '../continueTopic'
import { ensureThreadForContinue, getThreadStoreState, resetThreadStore } from '../threadStore'

const record: ConversationThread = {
  id: 'thread-missing',
  title: 'Synthetic topic',
  summary: '',
  sessionIds: ['20260101_000000'],
  createdAt: '',
  updatedAt: '',
}

beforeEach(() => {
  vi.resetAllMocks()
  resetThreadStore()
  api.listLocalThreads.mockResolvedValue([record])
  api.ensureLocalThread.mockResolvedValue(record)
})

it('upserts a missing thread then continues with that same id', async () => {
  const continueThread = vi.fn()
  await continueTopicFromReview({
    threadId: 'thread-missing',
    title: 'Synthetic topic',
    sessionId: '20260101_000000',
    indexed: false,
    ensure: (threadId, meta) => ensureThreadForContinue(threadId, meta),
    continueThread,
  })
  expect(api.ensureLocalThread).toHaveBeenCalledWith('thread-missing', {
    title: 'Synthetic topic',
    sessionId: '20260101_000000',
  })
  expect(api.ensureLocalThread.mock.calls[0][1]).not.toHaveProperty('messages')
  expect(getThreadStoreState().items.some((thread) => thread.id === 'thread-missing')).toBe(true)
  expect(continueThread).toHaveBeenCalledWith('thread-missing')
  expect(api.ensureLocalThread.mock.invocationCallOrder[0]).toBeLessThan(continueThread.mock.invocationCallOrder[0])
})

it('rejects an invalid threadId before ensure or continue', async () => {
  const ensure = vi.fn()
  const continueThread = vi.fn()
  await expect(continueTopicFromReview({
    threadId: '../invalid',
    title: 'Synthetic topic',
    sessionId: '20260101_000000',
    indexed: false,
    ensure,
    continueThread,
  })).rejects.toThrow('invalid threadId')
  expect(ensure).not.toHaveBeenCalled()
  expect(continueThread).not.toHaveBeenCalled()
})

it('continues a known thread without ensure', async () => {
  const ensure = vi.fn()
  const continueThread = vi.fn()
  await continueTopicFromReview({
    threadId: 'thread-known',
    title: 'Synthetic topic',
    sessionId: '20260101_000000',
    indexed: true,
    ensure,
    continueThread,
  })
  expect(ensure).not.toHaveBeenCalled()
  expect(continueThread).toHaveBeenCalledWith('thread-known')
})

it('does not continue when ensure returns a different id', async () => {
  const continueThread = vi.fn()
  await expect(continueTopicFromReview({
    threadId: 'thread-missing',
    title: 'Synthetic topic',
    sessionId: '20260101_000000',
    indexed: false,
    ensure: async () => ({ id: 'thread-other' }),
    continueThread,
  })).rejects.toThrow('invalid threadId')
  expect(continueThread).not.toHaveBeenCalled()
})

it('does not continue when ensure fails', async () => {
  api.ensureLocalThread.mockRejectedValue(new Error('invalid threadId'))
  const continueThread = vi.fn()
  await expect(continueTopicFromReview({
    threadId: 'thread-missing',
    title: 'Synthetic topic',
    sessionId: '20260101_000000',
    indexed: false,
    ensure: (threadId, meta) => ensureThreadForContinue(threadId, meta),
    continueThread,
  })).rejects.toThrow('invalid threadId')
  expect(continueThread).not.toHaveBeenCalled()
})
