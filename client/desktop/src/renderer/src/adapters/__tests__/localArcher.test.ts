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

import { clearDesktopApiToken, getDesktopApiToken, resolveDesktopApiToken, saveDesktopApiToken } from '../localArcher'

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
})
