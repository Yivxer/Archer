export { createSkillRegistry } from './types'
export type { Skill, SkillArgs, SkillDef, SkillRegistry, SkillResult } from './types'

export { obsidianReadSkill } from './obsidianRead'
export { obsidianWriteSkill } from './obsidianWrite'

export { getSkillRegistry, hasLocalSkill, listLocalSkills, resetSkillRegistry, tryExecuteLocalSkill } from './localSkillBridge'
