import { readFileSync } from 'node:fs'
import { resolve, relative, isAbsolute, join } from 'node:path'
import { homedir } from 'node:os'

const ARCHER_TOML_PATH = '/Users/Yivxer/Projects/Archer/archer.toml'

function expandHome(p: string): string {
  if (p.startsWith('~/')) return join(homedir(), p.slice(2))
  return p
}

/** Parse [obsidian] vault_path from archer.toml. Returns null if not found. */
export function resolveVaultPath(): string | null {
  try {
    const raw = readFileSync(ARCHER_TOML_PATH, 'utf8')
    let inObsidian = false
    for (const line of raw.split('\n')) {
      const trimmed = line.trim()
      if (trimmed === '[obsidian]') { inObsidian = true; continue }
      if (trimmed.startsWith('[')) { inObsidian = false; continue }
      if (inObsidian && trimmed.startsWith('vault_path')) {
        const match = trimmed.match(/vault_path\s*=\s*"(.+)"/)
        if (match) return expandHome(match[1])
        const match2 = trimmed.match(/vault_path\s*=\s*'(.+)'/)
        if (match2) return expandHome(match2[1])
      }
    }
  } catch {
    // Config file not accessible
  }
  return null
}

/** Resolve a note path relative to the vault. Returns null if outside vault. */
export function resolveNotePath(rawPath: string): string | null {
  const vaultPath = resolveVaultPath()
  if (!vaultPath) return null

  const resolvedVault = resolve(vaultPath)
  let resolved = isAbsolute(rawPath) ? rawPath : join(resolvedVault, rawPath)
  resolved = resolve(resolved)

  const rel = relative(resolvedVault, resolved)
  if (rel.startsWith('..') || rel === '') return null
  return resolved
}
