import type { Skill, SkillDef } from './types'
import { readFileSync, existsSync } from 'node:fs'
import { resolveNotePath } from './vault'

export const obsidianReadSkill: Skill = {
  def: {
    name: 'obsidian_read',
    description: '按路径读取 Obsidian vault 中的笔记内容（TS 实现）',
    version: '1.0.0-ts',
    author: 'archer-builtin',
    risk: 'low',
  } satisfies SkillDef,

  async run(args) {
    const rawPath = String(args.path || '').trim()
    const maxChars = Number(args.max_chars || args.maxChars || 4000)

    if (!rawPath) {
      return { ok: false, output: '', error: 'path is required' }
    }

    const notePath = resolveNotePath(rawPath)
    if (!notePath) {
      return { ok: false, output: '', error: `路径被拒绝或 vault 未配置: ${rawPath}` }
    }

    if (!existsSync(notePath)) {
      return { ok: false, output: '', error: `笔记不存在: ${notePath}` }
    }

    try {
      const text = readFileSync(notePath, 'utf8')
      if (text.length > maxChars) {
        return { ok: true, output: text.slice(0, maxChars) + `\n\n…（已截断，共 ${text.length} 字符）` }
      }
      return { ok: true, output: text }
    } catch (err) {
      return { ok: false, output: '', error: `读取失败: ${err instanceof Error ? err.message : String(err)}` }
    }
  },
}
