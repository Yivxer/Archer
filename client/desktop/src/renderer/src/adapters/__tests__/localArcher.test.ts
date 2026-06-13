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
  getDesktopApiToken,
  resolveDesktopApiToken,
  saveDesktopApiToken,
  spawnChildJobs,
  streamLocalChat,
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

  it('uses the provided runtime session id for stream agent events', async () => {
    const encoder = new TextEncoder()
    const payload = [
      'data: ' + JSON.stringify({
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
      'data: ' + JSON.stringify({ done: true }) + '\n\n',
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
      () => {},
      undefined,
      (event) => events.push({ sessionId: event.sessionId }),
      undefined,
      'session-current'
    )

    expect(events).toEqual([{ sessionId: 'session-current' }])
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
})
