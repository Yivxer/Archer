import { lstatSync, readFileSync, readdirSync, existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import { realpathSync } from 'node:fs'
import type { Skill } from './types'

const SENSITIVE_DIRS = new Set(['.ssh', '.gnupg', '.aws', '.kube'])
const SENSITIVE_FILES = new Set([
  '.env',
  '.netrc',
  'archer.toml',
  'credentials',
  'id_rsa',
  'id_ed25519',
])
const SENSITIVE_SUFFIXES = ['.pem', '.key', '.p12', '.pfx']

function expandHome(rawPath: string): string {
  if (rawPath.startsWith('~/')) return join(homedir(), rawPath.slice(2))
  return rawPath
}

function safeRealpath(path: string): string | null {
  try {
    return realpathSync(expandHome(path))
  } catch {
    return null
  }
}

function isSensitivePath(rawPath: string): boolean {
  const resolved = safeRealpath(rawPath)
  if (!resolved) return false
  const parts = resolved.split(/[/\\]/).map((p) => p.toLowerCase())
  const name = parts[parts.length - 1] || ''
  if (parts.some((part) => SENSITIVE_DIRS.has(part))) return true
  if (SENSITIVE_FILES.has(name)) return true
  return SENSITIVE_SUFFIXES.some((suffix) => name.endsWith(suffix))
}

function resolvePath(rawPath: string): string {
  return resolve(expandHome(rawPath.trim()))
}

export const fileOpsReadSkill: Skill = {
  def: {
    name: 'file_ops',
    description: '读取或列出本地文件（TS 只读子集：read/list）',
    version: '1.0.0-ts-read',
    author: 'archer-builtin',
    risk: 'low',
  },

  async run(args) {
    const action = String(args.action || 'read').trim()
    if (action !== 'read' && action !== 'list') {
      return { ok: false, output: '', error: '__fallback_python__' }
    }

    const rawPath = String(args.path || '').trim()
    if (!rawPath) {
      return { ok: false, output: '', error: 'path is required' }
    }

    if (isSensitivePath(rawPath)) {
      return { ok: false, output: '', error: `敏感路径访问被拒绝：${rawPath}` }
    }

    const path = resolvePath(rawPath)

    if (action === 'read') {
      if (!existsSync(path)) {
        return {
          ok: false,
          output: '',
          error: `文件不存在：${path}\n提示：如果路径包含空格，请用引号包裹，或使用 @\"路径\" 语法。`,
        }
      }

      let stat
      try {
        stat = lstatSync(path)
      } catch (err) {
        return { ok: false, output: '', error: `读取失败：${err instanceof Error ? err.message : String(err)}` }
      }

      if (stat.isDirectory()) {
        return { ok: false, output: '', error: `${path} 是目录，请改用 action=list 列出内容。` }
      }

      const maxChars = Number(args.max_chars || 6000)
      const startLine = Math.max(0, Number(args.start_line || 0))

      try {
        let text = readFileSync(path, 'utf8')
        const totalChars = text.length
        let prefix = ''

        if (startLine > 1) {
          const lines = text.split('\n')
          text = lines.slice(startLine - 1).join('\n')
          prefix = `（从第 ${startLine} 行开始，原文共 ${lines.length} 行）\n`
        }

        if (text.length > maxChars) {
          return {
            ok: true,
            output:
              prefix +
              text.slice(0, maxChars) +
              `\n\n…（已截断，原文共 ${totalChars} 字符。提示：用 shell grep -n 定位行号后，再用 start_line 参数跳到目标位置）`,
          }
        }

        return { ok: true, output: prefix + text }
      } catch (err) {
        return { ok: false, output: '', error: `读取失败：${err instanceof Error ? err.message : String(err)}` }
      }
    }

    if (!existsSync(path)) {
      return { ok: false, output: '', error: `路径不存在：${path}` }
    }

    let stat
    try {
      stat = lstatSync(path)
    } catch (err) {
      return { ok: false, output: '', error: `列出失败：${err instanceof Error ? err.message : String(err)}` }
    }

    if (!stat.isDirectory()) {
      return { ok: false, output: '', error: `${path} 不是目录` }
    }

    try {
      const items = readdirSync(path, { withFileTypes: true })
        .sort((a, b) => {
          const aDir = a.isDirectory() ? 0 : 1
          const bDir = b.isDirectory() ? 0 : 1
          if (aDir !== bDir) return aDir - bDir
          return a.name.localeCompare(b.name)
        })
        .slice(0, 50)

      const lines = items.map((item) => `${item.isDirectory() ? '📁 ' : '📄 '}${item.name}`)
      const total = readdirSync(path).length
      if (total > 50) lines.push('…（仅显示前 50 项）')
      return { ok: true, output: lines.join('\n') }
    } catch (err) {
      return { ok: false, output: '', error: `列出失败：${err instanceof Error ? err.message : String(err)}` }
    }
  },
}
