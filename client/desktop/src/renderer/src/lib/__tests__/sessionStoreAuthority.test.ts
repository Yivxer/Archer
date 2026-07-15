import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SessionDetail, SessionSearchResult } from '../../types'

const adapter = vi.hoisted(() => ({
  loadLocalSession: vi.fn(),
  searchLocalSessions: vi.fn(),
}))

vi.mock('../../adapters/localArcher', () => ({
  appendLocalSession: vi.fn(),
  deleteLocalSession: vi.fn(),
  loadLocalSession: adapter.loadLocalSession,
  saveLocalSession: vi.fn(),
  searchLocalSessions: adapter.searchLocalSessions,
}))

import {
  getSessionStoreState,
  loadSessionDetail,
  resetSessionStore,
  searchSessions,
} from '../sessionStore'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('sessionStore server authority', () => {
  beforeEach(() => {
    adapter.loadLocalSession.mockReset()
    adapter.searchLocalSessions.mockReset()
    resetSessionStore()
  })

  it('ignores an older detail response that arrives after the latest selection', async () => {
    const older = deferred<SessionDetail>()
    const latest = deferred<SessionDetail>()
    adapter.loadLocalSession.mockReturnValueOnce(older.promise).mockReturnValueOnce(latest.promise)

    const olderLoad = loadSessionDetail('older')
    const latestLoad = loadSessionDetail('latest')
    latest.resolve({ id: 'latest', title: '最新会话', date: '', turns: 0, tone: '', messages: [] })
    await latestLoad
    older.resolve({ id: 'older', title: '旧会话', date: '', turns: 0, tone: '', messages: [] })
    await olderLoad

    expect(getSessionStoreState().currentDetail?.id).toBe('latest')
  })

  it('ignores stale search results after the query changes', async () => {
    const older = deferred<SessionSearchResult[]>()
    const latest = deferred<SessionSearchResult[]>()
    adapter.searchLocalSessions.mockReturnValueOnce(older.promise).mockReturnValueOnce(latest.promise)

    const olderSearch = searchSessions('旧词')
    const latestSearch = searchSessions('新词')
    latest.resolve([{ id: 'latest', title: '新结果', date: '', turns: 1, tone: '', snippet: '', matchRole: 'user' }])
    await latestSearch
    older.resolve([{ id: 'older', title: '旧结果', date: '', turns: 1, tone: '', snippet: '', matchRole: 'user' }])
    await olderSearch

    expect(getSessionStoreState().searchResults.map((item) => item.id)).toEqual(['latest'])
  })
})
