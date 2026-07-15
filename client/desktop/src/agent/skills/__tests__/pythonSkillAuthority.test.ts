import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'


describe('python skill authority', () => {
  it('does not expose Desktop skill execution entry points', () => {
    const mainSource = readFileSync(resolve('src/main/index.ts'), 'utf8')
    const buildConfig = readFileSync(resolve('electron.vite.config.ts'), 'utf8')

    expect(mainSource).not.toContain('localSkillBridge')
    expect(mainSource).not.toContain('archer:execute-local-skill')
    expect(mainSource).not.toContain('archer:list-local-skills')
    expect(buildConfig).not.toContain('runLocalSkill')
    expect(existsSync(resolve('src/main/runLocalSkill.ts'))).toBe(false)
    expect(existsSync(resolve('src/agent/skills/localSkillBridge.ts'))).toBe(false)
  })
})
