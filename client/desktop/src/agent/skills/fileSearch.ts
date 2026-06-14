import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import type { Skill } from './types'

const SKIP_DIRS = new Set(['.git', 'node_modules', '__pycache__'])

function expandHome(rawPath: string): string {
  if (rawPath.startsWith('~/')) return join(homedir(), rawPath.slice(2))
  return rawPath
}

function resolveDirectory(rawPath: string): string {
  return resolve(expandHome(rawPath.trim()))
}

function* walkFiles(root: string): Generator<string> {
  const stack = [root]
  while (stack.length > 0) {
    const current = stack.pop()
    if (!current) continue

    let entries
    try {
      entries = readdirSync(current, { withFileTypes: true })
    } catch {
      continue
    }

    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue
      const fullPath = join(current, entry.name)
      if (entry.isDirectory()) {
        if (SKIP_DIRS.has(entry.name)) continue
        stack.push(fullPath)
        continue
      }
      if (entry.isFile()) yield fullPath
    }
  }
}

export const fileSearchSkill: Skill = {
  def: {
    name: 'file_search',
    description: '在本地磁盘搜索文件（TS：name + content 模式）',
    version: '1.0.0-ts',
    author: 'archer-builtin',
    risk: 'low',
  },

  async run(args) {
    const keyword = String(args.keyword || '').trim()
    const mode = String(args.mode || 'name').trim()
    const directory = String(args.directory || homedir()).trim()
    const ext = String(args.ext || '').trim().replace(/^\./, '')

    let limit = Number(args.limit || 20)
    if (!Number.isFinite(limit)) limit = 20
    limit = Math.max(1, Math.min(limit, 100))

    if (!keyword) {
      return { ok: false, output: '', error: '错误：keyword 不能为空' }
    }

    if (mode !== 'name' && mode !== 'content') {
      return { ok: false, output: '', error: '__fallback_python__' }
    }

    const directoryPath = resolveDirectory(directory)
    if (!existsSync(directoryPath)) {
      return { ok: false, output: '', error: `搜索失败：目录不存在：${directoryPath}` }
    }

    try {
      statSync(directoryPath)
    } catch (err) {
      return {
        ok: false,
        output: '',
        error: `搜索失败：${err instanceof Error ? err.message : String(err)}`,
      }
    }

    const needle = keyword.toLowerCase()
    const lines: string[] = []

    if (mode === 'name') {
      const suffix = ext ? `.${ext.toLowerCase()}` : ''
      for (const path of walkFiles(directoryPath)) {
        const name = path.split(/[/\\]/).pop()?.toLowerCase() || ''
        if (!name.includes(needle)) continue
        if (suffix && !name.endsWith(suffix)) continue
        lines.push(path)
        if (lines.length >= limit) break
      }
    } else {
      const allowedExts = ext
        ? new Set([`.${ext.toLowerCase()}`])
        : new Set(['.md', '.txt', '.py'])
      for (const path of walkFiles(directoryPath)) {
        const suffix = path.slice(path.lastIndexOf('.')).toLowerCase()
        if (!allowedExts.has(suffix)) continue
        try {
          const text = readFileSync(path, 'utf8')
          if (!text.toLowerCase().includes(needle)) continue
          lines.push(path)
          if (lines.length >= limit) break
        } catch {
          continue
        }
      }
    }

    if (lines.length === 0) {
      return {
        ok: true,
        output: `未找到${mode === 'name' ? '文件名' : '内容'}包含「${keyword}」的文件。`,
      }
    }

    const output = [
      `找到 ${lines.length} 个文件（mode=${mode}，keyword=${keyword}）：\n`,
      ...lines.map((p) => `  @${p}`),
      '\n提示：用 @路径 直接引用文件内容',
    ].join('\n')

    return { ok: true, output }
  },
}
