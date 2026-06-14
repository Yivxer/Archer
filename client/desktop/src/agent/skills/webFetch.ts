import type { Skill } from './types'
import { fetchPublicHttpUrl, validatePublicHttpUrl } from './urlSafety'

function stripHtml(html: string): string {
  let text = html.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '')
  text = text.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
  text = text.replace(/<[^>]+>/g, ' ')
  text = text.replace(/&nbsp;/g, ' ')
  text = text.replace(/&[a-z]+;/gi, '')
  text = text.replace(/\s{3,}/g, '\n\n')
  return text.trim()
}

export const webFetchSkill: Skill = {
  def: {
    name: 'web_fetch',
    description: '抓取网页内容并返回纯文本（TS 实现，含 SSRF 防护）',
    version: '1.0.0-ts',
    author: 'archer-builtin',
    risk: 'low',
  },

  async run(args) {
    const rawUrl = String(args.url || '').trim()
    let maxChars = Number(args.max_chars || 4000)
    if (!Number.isFinite(maxChars)) maxChars = 4000
    maxChars = Math.max(200, Math.min(maxChars, 12_000))

    if (!rawUrl) {
      return { ok: false, output: '', error: 'url is required' }
    }

    let url: string
    try {
      url = await validatePublicHttpUrl(rawUrl)
    } catch (err) {
      return {
        ok: false,
        output: '',
        error: `无效 URL：${err instanceof Error ? err.message : String(err)}`,
      }
    }

    const headers = {
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    }

    try {
      const response = await fetchPublicHttpUrl(url, { headers, timeoutMs: 15_000 })
      if (!response.ok) {
        return { ok: false, output: '', error: `HTTP 错误 ${response.status}：${url}` }
      }

      const raw = (await response.text()).slice(0, 1_000_000)
      const text = stripHtml(raw)
      if (text.length > maxChars) {
        return {
          ok: true,
          output: `${text.slice(0, maxChars)}\n\n…（已截断，共 ${text.length} 字符）`,
        }
      }
      return { ok: true, output: text }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      if (message.includes('URL 指向') || message.includes('只允许') || message.includes('重定向')) {
        return { ok: false, output: '', error: `抓取被拒绝：${message}` }
      }
      if (message.includes('abort')) {
        return { ok: false, output: '', error: `网络错误：请求超时` }
      }
      return { ok: false, output: '', error: `抓取失败：${message}` }
    }
  },
}
