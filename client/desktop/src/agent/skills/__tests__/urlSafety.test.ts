import { afterEach, describe, expect, it, vi } from 'vitest'
import { validatePublicHttpUrl, fetchPublicHttpUrl } from '../urlSafety'

const PUBLIC_IP = '93.184.216.34'

describe('urlSafety', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('rejects private and local urls', async () => {
    for (const url of [
      'http://127.0.0.1:8000',
      'http://10.0.0.1',
      'file:///etc/passwd',
    ]) {
      await expect(validatePublicHttpUrl(url)).rejects.toThrow()
    }
  })

  it('allows public http for literal public ip', async () => {
    await expect(validatePublicHttpUrl(`https://${PUBLIC_IP}/page`)).resolves.toBe(
      `https://${PUBLIC_IP}/page`,
    )
  })

  it('rejects redirect to localhost', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response('', {
          status: 302,
          headers: { Location: 'http://127.0.0.1:8000/private' },
        }),
      ),
    )

    await expect(fetchPublicHttpUrl(`https://${PUBLIC_IP}/redirect`)).rejects.toThrow(
      'URL 指向本地或私有网络地址',
    )
  })
})
