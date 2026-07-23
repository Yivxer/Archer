import { describe, expect, it, vi } from 'vitest'
import { apiRetryDelayMs, brainStatusReason, probeExistingApi, probeReadyApi, reclaimApiPort, resolveApiLaunchPaths, verifyApiToken, waitForHealthyApi, waitForReadyApi } from './apiProcess'

describe('resolveApiLaunchPaths', () => {
  it('uses the self-use defaults when no overrides are set', () => {
    expect(resolveApiLaunchPaths({})).toEqual({
      archerRoot: '/Users/Yivxer/Projects/Archer',
      pythonBin: '/Users/Yivxer/Projects/Archer/.venv/bin/python3',
      apiScript: '/Users/Yivxer/Projects/Archer/terminal/api/fastapi_app.py',
    })
  })

  it('allows env overrides for root, python, and API script', () => {
    expect(resolveApiLaunchPaths({
      ARCHER_ROOT: '/tmp/Archer',
      ARCHER_PYTHON_BIN: '/opt/python',
      ARCHER_API_SCRIPT: '/tmp/api.py',
    })).toEqual({
      archerRoot: '/tmp/Archer',
      pythonBin: '/opt/python',
      apiScript: '/tmp/api.py',
    })
  })

  it('derives python and script paths from an overridden root', () => {
    expect(resolveApiLaunchPaths({ ARCHER_ROOT: '/tmp/Archer' })).toEqual({
      archerRoot: '/tmp/Archer',
      pythonBin: '/tmp/Archer/.venv/bin/python3',
      apiScript: '/tmp/Archer/terminal/api/fastapi_app.py',
    })
  })
})

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

  it('treats 429 from /health as alive to avoid restart storms during rate limiting', async () => {
    await expect(probeExistingApi(async () => ({ ok: false, status: 429 }), 'http://127.0.0.1:8765')).resolves.toBe(true)
  })
})

describe('probeReadyApi', () => {
  it('checks /ready rather than /health', async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true }))

    await expect(probeReadyApi(fetchImpl, 'http://127.0.0.1:8765')).resolves.toBe(true)

    expect(fetchImpl).toHaveBeenCalledWith('http://127.0.0.1:8765/ready', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('returns false when readiness fails', async () => {
    await expect(probeReadyApi(async () => ({ ok: false }), 'http://127.0.0.1:8765')).resolves.toBe(false)
    await expect(probeReadyApi(async () => { throw new Error('network') }, 'http://127.0.0.1:8765')).resolves.toBe(false)
  })

  it('treats 429 from /ready as alive to avoid heartbeat-triggered respawns', async () => {
    await expect(probeReadyApi(async () => ({ ok: false, status: 429 }), 'http://127.0.0.1:8765')).resolves.toBe(true)
  })
})

describe('brainStatusReason', () => {
  const ready = {
    pythonOk: true,
    scriptOk: true,
    portOk: true,
    readyOk: true,
    tokenOk: true,
    owned: false,
  }

  it('prioritizes local launch problems before port state', () => {
    expect(brainStatusReason({ ...ready, pythonOk: false, portOk: true })).toBe('missing_python')
    expect(brainStatusReason({ ...ready, scriptOk: false, portOk: true })).toBe('missing_script')
  })

  it('distinguishes down, not ready, token mismatch, and ownership states', () => {
    expect(brainStatusReason({ ...ready, portOk: false })).toBe('port_down')
    expect(brainStatusReason({ ...ready, readyOk: false })).toBe('not_ready')
    expect(brainStatusReason({ ...ready, tokenOk: false })).toBe('token_mismatch')
    expect(brainStatusReason({ ...ready, owned: true })).toBe('owned')
    expect(brainStatusReason(ready)).toBe('reused')
  })
})

describe('apiRetryDelayMs', () => {
  it('backs off exponentially and caps at five seconds', () => {
    expect(apiRetryDelayMs(0)).toBe(1000)
    expect(apiRetryDelayMs(1)).toBe(2000)
    expect(apiRetryDelayMs(2)).toBe(4000)
    expect(apiRetryDelayMs(3)).toBe(5000)
    expect(apiRetryDelayMs(10)).toBe(5000)
  })

  it('normalizes invalid attempts to the first delay', () => {
    expect(apiRetryDelayMs(-1)).toBe(1000)
    expect(apiRetryDelayMs(Number.NaN)).toBe(1000)
  })
})

describe('reclaimApiPort', () => {
  it('waits until the previous listener actually releases the port', async () => {
    const listPids = vi.fn()
      .mockResolvedValueOnce([4312])
      .mockResolvedValueOnce([4312])
      .mockResolvedValueOnce([])
    const killProcess = vi.fn()
    const sleep = vi.fn(async () => {})

    await expect(reclaimApiPort(8765, {
      timeoutMs: 1000,
      intervalMs: 10,
      listPids,
      killProcess,
      sleep,
    })).resolves.toBe(true)

    expect(killProcess).toHaveBeenCalledOnce()
    expect(killProcess).toHaveBeenCalledWith(4312)
    expect(sleep).toHaveBeenCalledOnce()
  })

  it('returns false when the listener remains after the timeout', async () => {
    const listPids = vi.fn(async () => [4312])
    const killProcess = vi.fn()
    const sleep = vi.fn(async () => {})

    await expect(reclaimApiPort(8765, {
      timeoutMs: 0,
      listPids,
      killProcess,
      sleep,
    })).resolves.toBe(false)

    expect(killProcess).toHaveBeenCalledWith(4312)
    expect(sleep).not.toHaveBeenCalled()
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

  it('does not treat 429 from /status as token mismatch', async () => {
    await expect(verifyApiToken(async () => ({ ok: false, status: 429 }), 'abc123')).resolves.toBe(true)
  })
})

describe('waitForHealthyApi', () => {
  it('polls until /health succeeds', async () => {
    let calls = 0
    const fetchImpl = vi.fn(async (_url: string) => {
      calls += 1
      return { ok: calls >= 2 }
    })

    await expect(waitForHealthyApi(fetchImpl, 'http://127.0.0.1:8765', 2000, 50)).resolves.toBe(true)
    expect(fetchImpl.mock.calls.length).toBeGreaterThanOrEqual(2)
  })
})

describe('waitForReadyApi', () => {
  it('polls /ready until readiness succeeds', async () => {
    let calls = 0
    const fetchImpl = vi.fn(async (_url: string) => {
      calls += 1
      return { ok: calls >= 2 }
    })

    await expect(waitForReadyApi(fetchImpl, 'http://127.0.0.1:8765', 2000, 50)).resolves.toBe(true)
    expect(fetchImpl.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(fetchImpl.mock.calls[0][0]).toBe('http://127.0.0.1:8765/ready')
  })
})
