import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConversationThread, SessionDetail, SessionItem } from '../../types'

const api = vi.hoisted(() => ({
  listLocalSessions: vi.fn(), listLocalThreads: vi.fn(), loadLocalSession: vi.fn(),
  searchLocalSessions: vi.fn(), saveLocalSession: vi.fn(), appendLocalSession: vi.fn(),
  deleteLocalSession: vi.fn(), updateLocalThread: vi.fn(), createLocalThread: vi.fn(), addLocalSessionToThread: vi.fn(),
}))
vi.mock('../../adapters/conversationAdapter', () => api)
import { appendSessionMessages, deleteSession, getSessionStoreState, loadSessionDetail, loadSessionList, resetSessionStore, saveSessionMessages, searchSessions } from '../sessionStore'
import { getThreadStoreState, loadThreadList, resetThreadStore, setCurrentThread, updateThread } from '../threadStore'

const item: SessionItem = { id: 'session', threadId: 'thread', title: 'Server title', date: '', turns: 2, tone: '' }
const thread: ConversationThread = { id: 'thread', title: 'Server thread', summary: 'Confirmed server context', sessionIds: ['session'], createdAt: '', updatedAt: '' }
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

beforeEach(() => {
  vi.resetAllMocks()
  resetSessionStore(); resetThreadStore()
  api.listLocalSessions.mockResolvedValue([item])
  api.listLocalThreads.mockResolvedValue([thread])
  api.saveLocalSession.mockResolvedValue({ id: 'session', path: '/synthetic/session', threadId: 'thread' })
  api.appendLocalSession.mockResolvedValue({ id: 'session', path: '/synthetic/session', threadId: 'thread' })
  api.deleteLocalSession.mockResolvedValue({ ok: true, id: 'session', threadRemoved: 'thread' })
})

for (const domain of ['session', 'thread'] as const) {
  const load = domain === 'session' ? loadSessionList : loadThreadList
  const reset = domain === 'session' ? resetSessionStore : resetThreadStore
  const read = domain === 'session' ? getSessionStoreState : getThreadStoreState
  const fetch = () => domain === 'session' ? api.listLocalSessions : api.listLocalThreads
  const data = domain === 'session' ? [item] : [thread]
  describe(`${domain} list concurrency`, () => {
    it('coalesces normal requests', async () => {
      const pending = deferred<typeof data>()
      fetch().mockReturnValueOnce(pending.promise)
      const first = load(); const second = load()
      expect(fetch()).toHaveBeenCalledOnce()
      pending.resolve(data)
      await Promise.all([first, second])
      expect(read().items).toEqual(data)
    })
    it.each(['success', 'failure'])('ignores stale %s after a forced refresh', async (outcome) => {
      const older = deferred<typeof data>()
      fetch().mockReturnValueOnce(older.promise).mockResolvedValueOnce(data)
      const first = load()
      await load({ force: true })
      if (outcome === 'success') older.resolve([])
      else older.reject(new Error('old error'))
      await first
      expect(read()).toMatchObject({ items: data, loadState: 'ready', error: '' })
    })
    it('does not repopulate after reset', async () => {
      const pending = deferred<typeof data>()
      fetch().mockReturnValueOnce(pending.promise)
      const first = load()
      reset()
      pending.resolve(data)
      await first
      expect(read()).toMatchObject({ items: [], loadState: 'idle' })
    })
    it('retains the previous content on failure and clears the error on recovery', async () => {
      await load()
      fetch().mockRejectedValueOnce(new Error('offline'))
      await load()
      expect(read()).toMatchObject({ items: data, loadState: 'error', error: 'offline' })
      await load()
      expect(read()).toMatchObject({ items: data, loadState: 'ready', error: '' })
    })
  })
}

it('saving supersedes both older lists and keeps authoritative thread context', async () => {
  const oldSessions = deferred<SessionItem[]>()
  const oldThreads = deferred<ConversationThread[]>()
  api.listLocalSessions.mockReturnValueOnce(oldSessions.promise)
  api.listLocalThreads.mockReturnValueOnce(oldThreads.promise)
  const first = loadSessionList(); const second = loadThreadList()
  const saved = await saveSessionMessages([{ role: 'assistant', content: 'Unconfirmed suggestion' }])
  oldSessions.resolve([]); oldThreads.resolve([])
  await Promise.all([first, second])
  expect(saved.threadId).toBe('thread')
  expect(getSessionStoreState().items).toEqual([item])
  expect(getThreadStoreState().items[0].summary).toBe(thread.summary)
})

it('a successful append with failed refresh must not be presented as a failed write', async () => {
  await loadSessionList()
  api.listLocalSessions.mockRejectedValueOnce(new Error('refresh failed'))
  await expect(appendSessionMessages('session', [{ role: 'user', content: 'Next' }])).resolves.toMatchObject({ id: 'session' })
  expect(api.appendLocalSession).toHaveBeenCalledOnce()
  expect(getSessionStoreState()).toMatchObject({ items: [item], loadState: 'error', listError: 'refresh failed' })
})

it('failed save neither refreshes lists nor invents a session', async () => {
  api.saveLocalSession.mockRejectedValueOnce(new Error('denied'))
  await expect(saveSessionMessages([])).rejects.toThrow('denied')
  expect(api.listLocalSessions).not.toHaveBeenCalled()
  expect(getSessionStoreState().items).toEqual([])
})

it('deletion invalidates in-flight detail and search and refreshes thread references', async () => {
  await loadSessionList(); await loadThreadList()
  const detail = deferred<SessionDetail>()
  const search = deferred<SessionItem[]>()
  api.loadLocalSession.mockReturnValueOnce(detail.promise)
  api.searchLocalSessions.mockReturnValueOnce(search.promise)
  const detailLoad = loadSessionDetail('session'); const searchLoad = searchSessions('Server')
  api.listLocalSessions.mockResolvedValueOnce([])
  api.listLocalThreads.mockResolvedValueOnce([])
  await expect(deleteSession('session')).resolves.toMatchObject({ ok: true })
  detail.resolve({ ...item, messages: [] }); search.resolve([item])
  await Promise.all([detailLoad, searchLoad])
  expect(getSessionStoreState()).toMatchObject({ items: [], currentDetail: null, searchResults: [], searchState: 'idle' })
  expect(getThreadStoreState().items).toEqual([])
})

it('rejected deletion preserves the session and the thread', async () => {
  await loadSessionList(); await loadThreadList()
  api.deleteLocalSession.mockResolvedValueOnce({ ok: false })
  expect(await deleteSession('session')).toEqual({ ok: false })
  expect(getSessionStoreState().items).toEqual([item])
  expect(getThreadStoreState().items).toEqual([thread])
})

it('a thread write supersedes an old list without losing the active thread', async () => {
  await loadThreadList(); setCurrentThread('thread')
  const pending = deferred<ConversationThread[]>()
  api.listLocalThreads.mockReturnValueOnce(pending.promise).mockResolvedValueOnce([{ ...thread, title: 'Renamed' }])
  api.updateLocalThread.mockResolvedValueOnce({ ...thread, title: 'Renamed' })
  const reading = loadThreadList()
  await updateThread('thread', { title: 'Renamed' })
  pending.resolve([thread]); await reading
  expect(getThreadStoreState().items[0].title).toBe('Renamed')
  expect(getThreadStoreState().currentThreadId).toBe('thread')
})

it('does not refresh or resurrect data when a write completes after reset', async () => {
  const pending = deferred<{ id: string; path: string }>()
  api.saveLocalSession.mockReturnValueOnce(pending.promise)
  const saving = saveSessionMessages([])
  resetSessionStore(); resetThreadStore()
  pending.resolve({ id: 'old', path: '/synthetic/old' })
  await saving
  expect(api.listLocalSessions).not.toHaveBeenCalled()
  expect(getSessionStoreState().items).toEqual([])
})
