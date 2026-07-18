import { beforeEach, describe, expect, it, vi } from 'vitest'

const store: Record<string, string> = {}
vi.stubGlobal('localStorage', {
  getItem: vi.fn((key: string) => store[key] ?? null),
  setItem: vi.fn((key: string, value: string) => { store[key] = value }),
  removeItem: vi.fn((key: string) => { delete store[key] }),
})
vi.stubGlobal('window', { archerDesktop: undefined })

import { fetchPendingCompanionMessage, respondToCompanionMessage } from '../companion'

describe('memory-grounded companion adapter', () => {
  beforeEach(() => { Object.keys(store).forEach((key) => delete store[key]) })

  it('reads and responds to a companion message', async () => {
    const item = { id: 9, message: '要继续吗？', threadId: '3', sessionId: 's1', source: 'episodic', confidence: 0.9 }
    const fetchSpy = vi.fn(async (_url: string, init?: RequestInit) => new Response(JSON.stringify(
      !init?.method || init.method === 'GET'
        ? { ok: true, item }
        : { ok: true, id: 9, status: 'continued', memoryResult: 'skipped' }
    ), { status: 200 }))
    vi.stubGlobal('fetch', fetchSpy)
    await expect(fetchPendingCompanionMessage()).resolves.toEqual(item)
    await expect(respondToCompanionMessage(9, 'continue', '继续')).resolves.toMatchObject({ status: 'continued' })
    expect(String(fetchSpy.mock.calls[0][0])).toContain('/companion/pending')
    expect(String(fetchSpy.mock.calls[1][0])).toContain('/companion/9/respond')
  })
})
