import { describe, expect, it, vi } from 'vitest'
import { probeExistingApi } from './apiProcess'

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
