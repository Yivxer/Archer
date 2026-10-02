import { beforeEach, describe, expect, it, vi } from 'vitest'
import { postJson } from './localArcher'
import { transitionThreadClue } from './threadClues'

vi.mock('./localArcher', () => ({ postJson: vi.fn() }))

beforeEach(() => vi.resetAllMocks())

describe('thread clue controls', () => {
  it.each(['resolved', 'closed', 'dismissed', 'expired'] as const)('uses the cue endpoint for %s', async (status) => {
    vi.mocked(postJson).mockResolvedValue({ ok: true, id: 42, status, changed: true })
    await expect(transitionThreadClue(42, status)).resolves.toMatchObject({ status })
    expect(postJson).toHaveBeenCalledWith('/initiative-threads/42/status', { status })
  })
  it.each([0, -1, NaN, 1.1, Number.MAX_SAFE_INTEGER + 1])('rejects invalid cue id %s without a request', async (id) => {
    await expect(transitionThreadClue(id, 'closed')).rejects.toThrow()
    expect(postJson).not.toHaveBeenCalled()
  })
  it('does not report success when the backend rejected or identified another cue', async () => {
    vi.mocked(postJson).mockResolvedValue({ ok: false, id: 42, status: 'closed' })
    await expect(transitionThreadClue(42, 'closed')).rejects.toThrow('未保存')
    vi.mocked(postJson).mockResolvedValue({ ok: true, id: 43, status: 'closed' })
    await expect(transitionThreadClue(42, 'closed')).rejects.toThrow('未保存')
  })
})
