import { describe, expect, it } from 'vitest'
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { fileSearchSkill } from '../fileSearch'

describe('fileSearchSkill', () => {
  it('declares file_search with low risk', () => {
    expect(fileSearchSkill.def.name).toBe('file_search')
    expect(fileSearchSkill.def.risk).toBe('low')
  })

  it('falls back to python for unknown mode', async () => {
    const result = await fileSearchSkill.run({ keyword: 'hello', mode: 'regex' })
    expect(result.error).toBe('__fallback_python__')
  })

  it('finds files by content', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'archer-file-search-content-'))
    writeFileSync(join(dir, 'alpha.txt'), 'needle in haystack')
    writeFileSync(join(dir, 'beta.txt'), 'nothing here')

    const result = await fileSearchSkill.run({
      keyword: 'needle',
      mode: 'content',
      directory: dir,
      limit: 10,
    })

    expect(result.ok).toBe(true)
    expect(result.output).toContain('alpha.txt')
    expect(result.output).not.toContain('beta.txt')
  })

  it('finds files by name', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'archer-file-search-'))
    writeFileSync(join(dir, 'notes-demo.txt'), 'x')
    mkdirSync(join(dir, 'nested'))
    writeFileSync(join(dir, 'nested', 'other.md'), 'y')

    const result = await fileSearchSkill.run({
      keyword: 'demo',
      mode: 'name',
      directory: dir,
      limit: 10,
    })

    expect(result.ok).toBe(true)
    expect(result.output).toContain('notes-demo.txt')
    expect(result.output).not.toContain('other.md')
  })

  it('filters by extension in name mode', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'archer-file-search-ext-'))
    writeFileSync(join(dir, 'report-demo.md'), 'a')
    writeFileSync(join(dir, 'report-demo.txt'), 'b')

    const result = await fileSearchSkill.run({
      keyword: 'demo',
      mode: 'name',
      directory: dir,
      ext: 'md',
    })

    expect(result.ok).toBe(true)
    expect(result.output).toContain('report-demo.md')
    expect(result.output).not.toContain('report-demo.txt')
  })
})
