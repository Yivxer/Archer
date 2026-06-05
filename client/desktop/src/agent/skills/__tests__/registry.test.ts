import { describe, expect, it, beforeEach } from 'vitest'
import { createSkillRegistry } from '../types'
import type { Skill } from '../types'

const testSkill: Skill = {
  def: {
    name: 'test_skill',
    description: 'A test skill for unit tests',
    version: '1.0.0',
    author: 'test',
    risk: 'low',
  },
  run: async (args) => {
    const text = String(args.text || 'default')
    return { ok: true, output: text.toUpperCase() }
  },
}

describe('skillRegistry', () => {
  let registry: ReturnType<typeof createSkillRegistry>

  beforeEach(() => {
    registry = createSkillRegistry()
  })

  it('registers and retrieves a skill', () => {
    registry.register(testSkill)
    expect(registry.has('test_skill')).toBe(true)
    expect(registry.get('test_skill')?.def.name).toBe('test_skill')
  })

  it('lists registered skills', () => {
    registry.register(testSkill)
    const list = registry.list()
    expect(list).toHaveLength(1)
    expect(list[0].name).toBe('test_skill')
    expect(list[0].risk).toBe('low')
  })

  it('runs a registered skill', async () => {
    registry.register(testSkill)
    const result = await registry.run('test_skill', { text: 'hello' })
    expect(result.ok).toBe(true)
    expect(result.output).toBe('HELLO')
  })

  it('returns error for unknown skill', async () => {
    const result = await registry.run('unknown', {})
    expect(result.ok).toBe(false)
    expect(result.error).toContain('not found')
  })

  it('returns error when run throws', async () => {
    const badSkill: Skill = {
      def: {...testSkill.def, name: 'bad'},
      run: async () => { throw new Error('boom') },
    }
    registry.register(badSkill)
    const result = await registry.run('bad', {})
    expect(result.ok).toBe(false)
    expect(result.error).toContain('boom')
  })

  it('clears all skills', () => {
    registry.register(testSkill)
    registry.clear()
    expect(registry.has('test_skill')).toBe(false)
    expect(registry.list()).toHaveLength(0)
  })

  it('supports multiple skill registrations', () => {
    registry.register(testSkill)
    const another: Skill = {
      def: {...testSkill.def, name: 'another'},
      run: async () => ({ ok: true, output: 'done' }),
    }
    registry.register(another)
    expect(registry.list()).toHaveLength(2)
  })
})
