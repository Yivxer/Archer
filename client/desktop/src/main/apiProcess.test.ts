import { describe, expect, it, vi } from 'vitest'
import { probeExistingApi, verifyApiToken, waitForHealthyApi } from './apiProcess'

describe('probeExistingApi', () => {
  it('reuses an already running API when /health responds ok', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true }))

    await expect(probeExistingApi(fetchImpl, 'http://127.0.0.1:8765')).resolves.toBe(true)

    expect(fetchImpl).toHaveBeenCalledWith('http://127.0.0.1:8765/health', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('does not reuse the API when /health fails or times out', async () => {
    await expect(probeExistingApi(async () => ({ ok: false }), 'http://127.0.0.1:8765')).resolves.toBe(false)
    await expect(probeExistingApi(async () => { throw new Error('network') }, 'http://127.0.0.1:8765')).resolves.toBe(false)
  })
})

describe('verifyApiToken', () => {
  it('accepts a valid bearer token against /status', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true }))
    await expect(verifyApiToken(fetchImpl, 'abc123')).resolves.toBe(true)
    expect(fetchImpl).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/status',
      expect.objectContaining({ headers: { Authorization: 'Bearer abc123' } })
    )
  })

  it('rejects empty or unauthorized tokens', async () => {
    await expect(verifyApiToken(async () => ({ ok: true }), '')).resolves.toBe(false)
    await expect(verifyApiToken(async () => ({ ok: false }), 'bad')).resolves.toBe(false)
  })
})

describe('waitForHealthyApi', () => {
  it('polls until /health succeeds', async () => {
    let calls = 0
    const fetchImpl = vi.fn(async () => {
      calls += 1
      return { ok: calls >= 2 }
    })

    await expect(waitForHealthyApi(fetchImpl, 'http://127.0.0.1:8765', 2000, 50)).resolves.toBe(true)
    expect(fetchImpl.mock.calls.length).toBeGreaterThanOrEqual(2)
  })
})
