import type { Skill } from './types'
import { fetchPublicHttpUrl } from './urlSafety'

export type WebSearchResult = {
  title: string
  url: string
  snippet: string
}

const USER_AGENT =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

export function stripTags(raw: string): string {
  return raw
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export function normalizeDdgHref(href: string): string {
  if (href.startsWith('//duckduckgo.com/l/')) {
    const match = href.match(/uddg=([^&]+)/)
    if (match) return decodeURIComponent(match[1])
  }
  if (href.startsWith('/')) return `https://duckduckgo.com${href}`
  return href
}

/** Parse DuckDuckGo HTML search results (mirrors skills/web_search.py). */
export function parseDdgHtml(html: string, maxResults: number): WebSearchResult[] {
  const titlePattern = /class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g
  const snippetPattern = /class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g

  const titleMatches: Array<[string, string]> = []
  let titleMatch: RegExpExecArray | null
  while ((titleMatch = titlePattern.exec(html)) !== null) {
    titleMatches.push([titleMatch[1], titleMatch[2]])
  }

  const snippetMatches: string[] = []
  let snippetMatch: RegExpExecArray | null
  while ((snippetMatch = snippetPattern.exec(html)) !== null) {
    snippetMatches.push(snippetMatch[1])
  }

  const results: WebSearchResult[] = []
  for (let i = 0; i < Math.min(titleMatches.length, maxResults); i += 1) {
    const [href, titleHtml] = titleMatches[i]
    const title = stripTags(titleHtml)
    const snippet = i < snippetMatches.length ? stripTags(snippetMatches[i]) : ''
    const url = normalizeDdgHref(href)
    if (title && url) {
      results.push({ title, url, snippet })
    }
  }

  return results
}

export async function ddgSearch(query: string, maxResults: number): Promise<WebSearchResult[]> {
  const encoded = encodeURIComponent(query).replace(/%20/g, '+')
  const url = `https://html.duckduckgo.com/html/?q=${encoded}`
  const response = await fetchPublicHttpUrl(url, {
    headers: {
      'User-Agent': USER_AGENT,
      'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    },
    timeoutMs: 15_000,
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  const html = (await response.text()).slice(0, 2_000_000)
  return parseDdgHtml(html, maxResults)
}

function formatResults(query: string, results: WebSearchResult[]): string {
  const lines = [`搜索「${query}」，共 ${results.length} 条结果：\n`]
  results.forEach((result, index) => {
    lines.push(`${index + 1}. **${result.title}**`)
    if (result.snippet) lines.push(`   ${result.snippet}`)
    lines.push(`   ${result.url}`)
    lines.push('')
  })
  lines.push('提示：用 web_fetch url=<链接> 阅读完整内容')
  return lines.join('\n')
}

export const webSearchSkill: Skill = {
  def: {
    name: 'web_search',
    description: '用 DuckDuckGo 搜索互联网（TS 实现）',
    version: '1.0.0-ts',
    author: 'archer-builtin',
    risk: 'low',
  },

  async run(args) {
    const query = String(args.query || '').trim()
    let maxResults = Number(args.max_results || args.maxResults || 6)
    if (!Number.isFinite(maxResults)) maxResults = 6
    maxResults = Math.max(1, Math.min(maxResults, 10))

    if (!query) {
      return { ok: false, output: '', error: '错误：query 不能为空' }
    }

    try {
      const results = await ddgSearch(query, maxResults)
      if (results.length === 0) {
        return {
          ok: true,
          output: `未找到「${query}」的相关结果\n提示：尝试换用英文关键词或更具体的搜索词`,
        }
      }
      return { ok: true, output: formatResults(query, results) }
    } catch (err) {
      return {
        ok: false,
        output: '',
        error: `搜索失败：${err instanceof Error ? err.message : String(err)}\n提示：检查网络连接，或直接用 web_fetch 访问已知 URL`,
      }
    }
  },
}
