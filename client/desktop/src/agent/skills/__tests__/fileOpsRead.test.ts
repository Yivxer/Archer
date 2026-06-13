import { describe, expect, it } from 'vitest'
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { fileOpsReadSkill } from '../fileOpsRead'

describe('fileOpsReadSkill', () => {
  it('declares file_ops with low risk', () => {
    expect(fileOpsReadSkill.def.name).toBe('file_ops')
    expect(fileOpsReadSkill.def.risk).toBe('low')
  })

  it('falls back to python for write actions', async () => {
    const result = await fileOpsReadSkill.run({ action: 'write', path: '/tmp/x.txt', content: 'hi' })
    expect(result.error).toBe('__fallback_python__')
  })

  it('reads a text file with truncation', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'archer-file-read-'))
    const filePath = join(dir, 'sample.txt')
    writeFileSync(filePath, 'hello world')

    const result = await fileOpsReadSkill.run({ action: 'read', path: filePath, max_chars: 5 })
    expect(result.ok).toBe(true)
    expect(result.output).toContain('hello')
    expect(result.output).toContain('已截断')
  })

  it('lists a directory', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'archer-file-list-'))
    writeFileSync(join(dir, 'a.txt'), 'a')
    mkdirSync(join(dir, 'nested'))

    const result = await fileOpsReadSkill.run({ action: 'list', path: dir })
    expect(result.ok).toBe(true)
    expect(result.output).toContain('a.txt')
    expect(result.output).toContain('nested')
  })
})
