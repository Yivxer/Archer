import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { listLocalSessions, listLocalThreads, saveLocalSession, deleteLocalSession } from '../conversationAdapter'
beforeEach(() => {
  vi.stubGlobal('localStorage', { getItem: () => 'synthetic-token' })
  vi.stubGlobal('window', {})
})
afterEach(() => vi.unstubAllGlobals())
it('unwraps the GET contract and preserves flat POST receipts and continuation identity', async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url).pathname
    if (!init?.method) return new Response(JSON.stringify({ contractVersion: 1, data: [{ id: path === '/threads' ? 'topic' : 'session' }] }))
    if (path.endsWith('/delete')) return new Response(JSON.stringify({ contractVersion: 1, ok: true, id: 'session', threadRemoved: 'topic', fileDeleted: true }))
    return new Response(JSON.stringify({ contractVersion: 1, id: 'new-session', path: '/synthetic/new', threadId: 'topic' }))
  })
  vi.stubGlobal('fetch', fetcher)
  expect(await listLocalSessions()).toEqual([{ id: 'session' }])
  expect(await listLocalThreads()).toEqual([{ id: 'topic' }])
  expect(await saveLocalSession([{ role: 'user', content: 'Continue' }], { threadId: 'topic' })).toMatchObject({ id: 'new-session', threadId: 'topic' })
  expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body))).toMatchObject({ threadId: 'topic' })
  expect(await deleteLocalSession('session')).toMatchObject({ ok: true, threadRemoved: 'topic' })
  expect(new Headers(fetcher.mock.calls[2][1]?.headers).get('Authorization')).toBe('Bearer synthetic-token')
})
it('failed list HTTP responses stay errors instead of becoming an empty list', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({message:'unavailable'}), {status:503})))
  await expect(listLocalSessions()).rejects.toThrow('unavailable')
})
