import type { RiskLevel } from '../contracts'

/** Mirror of Python's SKILL dict */
export type SkillDef = {
  name: string
  description: string
  version: string
  author: string
  /** Risk level for approval gating (low: auto-approve, medium+: needs user) */
  risk: RiskLevel
}

/** Parameters expected by the skill's run function */
export type SkillArgs = Record<string, unknown>

/** Result from skill execution */
export type SkillResult = {
  ok: boolean
  output: string
  error?: string
}

/** A registered skill with its run handler */
export type Skill = {
  def: SkillDef
  /** Execute the skill with the given arguments. Called by the registry. */
  run: (args: SkillArgs) => Promise<SkillResult>
}

/** Registry of registered TypeScript skills, keyed by skill name */
export type SkillRegistry = {
  register: (skill: Skill) => void
  get: (name: string) => Skill | undefined
  list: () => SkillDef[]
  has: (name: string) => boolean
  run: (name: string, args: SkillArgs) => Promise<SkillResult>
  clear: () => void
}

export function createSkillRegistry(): SkillRegistry {
  const skills = new Map<string, Skill>()

  return {
    register(skill) {
      skills.set(skill.def.name, skill)
    },

    get(name) {
      return skills.get(name)
    },

    list() {
      return Array.from(skills.values()).map((s) => s.def)
    },

    has(name) {
      return skills.has(name)
    },

    async run(name, args) {
      const skill = skills.get(name)
      if (!skill) {
        return { ok: false, output: '', error: `skill ${name} not found in TS registry` }
      }
      try {
        return await skill.run(args)
      } catch (err) {
        return { ok: false, output: '', error: err instanceof Error ? err.message : String(err) }
      }
    },

    clear() {
      skills.clear()
    },
  }
}
