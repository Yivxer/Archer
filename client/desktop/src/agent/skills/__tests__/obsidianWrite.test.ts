import { describe, expect, it } from 'vitest'
import { obsidianWriteSkill } from '../obsidianWrite'

describe('obsidianWriteSkill', () => {
  it('has correct skill definition', () => {
    expect(obsidianWriteSkill.def.name).toBe('obsidian_write')
    expect(obsidianWriteSkill.def.risk).toBe('medium')
  })

  it('returns error when path is empty', async () => {
    const result = await obsidianWriteSkill.run({ path: '', content: 'test' })
    expect(result.ok).toBe(false)
    expect(result.error).toContain('path is required')
  })

  it('returns error when content is empty', async () => {
    const result = await obsidianWriteSkill.run({ path: 'test.md', content: '' })
    expect(result.ok).toBe(false)
    expect(result.error).toContain('content is required')
  })

  it('returns error when path is outside vault', async () => {
    const result = await obsidianWriteSkill.run({ path: '/etc/passwd', content: 'hack' })
    expect(result.ok).toBe(false)
    expect(result.error).toContain('路径被拒绝')
  })
})
