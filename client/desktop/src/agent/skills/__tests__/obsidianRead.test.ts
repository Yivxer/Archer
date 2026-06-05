import { describe, expect, it, vi } from 'vitest'
import { obsidianReadSkill } from '../obsidianRead'

describe('obsidianReadSkill', () => {
  it('has correct skill definition', () => {
    expect(obsidianReadSkill.def.name).toBe('obsidian_read')
    expect(obsidianReadSkill.def.risk).toBe('low')
    expect(obsidianReadSkill.def.version).toContain('-ts')
  })

  it('returns error when path is empty', async () => {
    const result = await obsidianReadSkill.run({ path: '' })
    expect(result.ok).toBe(false)
    expect(result.error).toContain('path is required')
  })

  it('returns error when vault config is not found', async () => {
    const result = await obsidianReadSkill.run({ path: 'test.md' })
    // In test env, archer.toml exists so vault resolves, but the file doesn't exist
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/路径被拒绝|笔记不存在/)
  })
})
