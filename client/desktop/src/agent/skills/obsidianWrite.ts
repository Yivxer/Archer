import type { Skill, SkillDef } from './types'
import { writeFileSync, appendFileSync, readFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname } from 'node:path'
import { resolveNotePath } from './vault'

function timestamp(): string {
  return new Date().toISOString().replace('T', ' ').slice(0, 19)
}

export const obsidianWriteSkill: Skill = {
  def: {
    name: 'obsidian_write',
    description: '写入或追加内容到 Obsidian vault 中的笔记（TS 实现）',
    version: '1.0.0-ts',
    author: 'archer-builtin',
    risk: 'medium',
  } satisfies SkillDef,

  async run(args) {
    const rawPath = String(args.path || '').trim()
    const content = String(args.content || '')
    const mode = String(args.mode || 'append')
    const addTs = Boolean(args.add_timestamp || args.addTimestamp)

    if (!rawPath) return { ok: false, output: '', error: 'path is required' }
    if (!content) return { ok: false, output: '', error: 'content is required' }

    const notePath = resolveNotePath(rawPath)
    if (!notePath) {
      return { ok: false, output: '', error: `路径被拒绝或 vault 未配置: ${rawPath}` }
    }

    try {
      // Ensure parent directory exists
      mkdirSync(dirname(notePath), { recursive: true })

      let finalContent = content
      if (addTs && mode === 'append') {
        finalContent = `\n\n---\n**${timestamp()}**\n${content}`
      }

      if (mode === 'overwrite') {
        writeFileSync(notePath, finalContent, 'utf8')
        return { ok: true, output: `已覆盖写入: ${notePath}` }
      } else if (mode === 'prepend') {
        const existing = existsSync(notePath) ? readFileSync(notePath, 'utf8') : ''
        writeFileSync(notePath, finalContent + '\n\n' + existing, 'utf8')
        return { ok: true, output: `已插入开头: ${notePath}` }
      } else {
        // append (default)
        appendFileSync(notePath, finalContent + '\n', 'utf8')
        return { ok: true, output: `已追加写入: ${notePath}` }
      }
    } catch (err) {
      return { ok: false, output: '', error: `写入失败: ${err instanceof Error ? err.message : String(err)}` }
    }
  },
}
