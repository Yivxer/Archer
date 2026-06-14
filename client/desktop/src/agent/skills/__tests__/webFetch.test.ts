import { afterEach, describe, expect, it, vi } from 'vitest'
import { webFetchSkill } from '../webFetch'

const PUBLIC_IP = '93.184.216.34'

describe('webFetchSkill', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('declares web_fetch with low risk', () => {
    expect(webFetchSkill.def.name).toBe('web_fetch')
    expect(webFetchSkill.def.risk).toBe('low')
  })

  it('rejects localhost before network', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const result = await webFetchSkill.run({ url: 'http://127.0.0.1:8000' })
    expect(result.ok).toBe(false)
    expect(result.error).toContain('无效 URL')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('strips html from fetched content', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response('<html><body><p>Hello</p><script>bad()</script></body></html>', {
          status: 200,
          headers: { 'content-type': 'text/html' },
        }),
      ),
    )

    const result = await webFetchSkill.run({
      url: `https://${PUBLIC_IP}`,
      max_chars: 1000,
    })
    expect(result.ok).toBe(true)
    expect(result.output).toContain('Hello')
    expect(result.output).not.toContain('bad()')
  })
})
