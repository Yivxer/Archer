import { describe, expect, it, vi, afterEach } from 'vitest'
import { parseDdgHtml, stripTags, normalizeDdgHref, webSearchSkill } from '../webSearch'

const SAMPLE_HTML = `
<div class="result__body">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdoc">TypeScript Guide</a>
  <a class="result__snippet">Learn TypeScript basics and advanced patterns.</a>
</div>
<div class="result__body">
  <a class="result__a" href="https://developer.mozilla.org/en-US/docs/Web/JavaScript">MDN JavaScript</a>
  <a class="result__snippet">JavaScript reference on MDN.</a>
</div>
`

describe('webSearch helpers', () => {
  it('stripTags decodes basic entities', () => {
    expect(stripTags('Hello&nbsp;<b>World</b>')).toBe('Hello World')
  })

  it('normalizeDdgHref unwraps duckduckgo redirect', () => {
    expect(normalizeDdgHref('//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com')).toBe(
      'https://example.com',
    )
  })

  it('parseDdgHtml extracts title url snippet', () => {
    const results = parseDdgHtml(SAMPLE_HTML, 6)
    expect(results).toHaveLength(2)
    expect(results[0].title).toBe('TypeScript Guide')
    expect(results[0].url).toBe('https://example.com/doc')
    expect(results[0].snippet).toContain('TypeScript basics')
  })
})

describe('webSearchSkill', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('declares web_search with low risk', () => {
    expect(webSearchSkill.def.name).toBe('web_search')
    expect(webSearchSkill.def.risk).toBe('low')
  })

  it('formats parsed search results', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(SAMPLE_HTML, {
          status: 200,
          headers: { 'content-type': 'text/html' },
        }),
      ),
    )

    const result = await webSearchSkill.run({ query: 'typescript guide', max_results: 2 })
    expect(result.ok).toBe(true)
    expect(result.output).toContain('TypeScript Guide')
    expect(result.output).toContain('https://example.com/doc')
    expect(result.output).toContain('web_fetch')
  })
})
