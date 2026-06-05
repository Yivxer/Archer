import type { SkillArgs, SkillRegistry } from './types'
import { createSkillRegistry } from './types'
import { obsidianReadSkill } from './obsidianRead'
import { obsidianWriteSkill } from './obsidianWrite'

/** Shared singleton skill registry with all TS-implemented skills registered */
let _registry: SkillRegistry | null = null

export function getSkillRegistry(): SkillRegistry {
  if (!_registry) {
    _registry = createSkillRegistry()
    _registry.register(obsidianReadSkill)
    _registry.register(obsidianWriteSkill)
  }
  return _registry
}

export function resetSkillRegistry(): void {
  _registry = null
}

/**
 * Try to execute a skill locally via the TS registry.
 * Returns null if the skill is not registered in TS (caller should fall back to Python).
 */
export async function tryExecuteLocalSkill(
  name: string,
  args: SkillArgs
): Promise<{ ok: boolean; output: string; error?: string } | null> {
  const registry = getSkillRegistry()
  if (!registry.has(name)) return null
  return registry.run(name, args)
}

/**
 * List all skills available in the TS registry.
 * Useful for filtering which tool events can be handled locally.
 */
export function listLocalSkills(): string[] {
  return getSkillRegistry().list().map((s) => s.name)
}

/**
 * Check if a skill is available locally (in TS registry).
 */
export function hasLocalSkill(name: string): boolean {
  return getSkillRegistry().has(name)
}
