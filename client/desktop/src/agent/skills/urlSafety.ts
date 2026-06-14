import { lookup } from 'node:dns/promises'
import { isIP } from 'node:net'

function isBlockedIp(ip: string): boolean {
  const version = isIP(ip)
  if (version === 4) {
    const [a, b] = ip.split('.').map(Number)
    if (a === 10) return true
    if (a === 127) return true
    if (a === 0) return true
    if (a === 169 && b === 254) return true
    if (a === 172 && b >= 16 && b <= 31) return true
    if (a === 192 && b === 168) return true
    if (a >= 224) return true
    return false
  }
  if (version === 6) {
    const lower = ip.toLowerCase()
    if (lower === '::' || lower === '::1') return true
    if (lower.startsWith('fe80:')) return true
    if (lower.startsWith('fc') || lower.startsWith('fd')) return true
    if (lower.startsWith('ff')) return true
    return false
  }
  return true
}

async function resolvedAddresses(hostname: string): Promise<string[]> {
  const literal = isIP(hostname)
  if (literal) return [hostname]
  try {
    const records = await lookup(hostname, { all: true, verbatim: true })
    return records.map((record) => record.address)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    throw new Error(`无法解析 hostname：${message}`)
  }
}

/** Return a normalized URL if it is a public http(s) URL, otherwise throw. */
export async function validatePublicHttpUrl(url: string): Promise<string> {
  let parsed: URL
  try {
    parsed = new URL(url.trim())
  } catch {
    throw new Error('只允许 http/https URL')
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('只允许 http/https URL')
  }
  if (!parsed.hostname) {
    throw new Error('URL 缺少 hostname')
  }

  const addresses = await resolvedAddresses(parsed.hostname)
  for (const address of addresses) {
    if (isBlockedIp(address)) {
      throw new Error('URL 指向本地或私有网络地址')
    }
  }

  return parsed.href
}

export async function fetchPublicHttpUrl(
  url: string,
  options: {
    headers?: Record<string, string>
    timeoutMs?: number
    maxRedirects?: number
  } = {},
): Promise<Response> {
  const timeoutMs = options.timeoutMs ?? 15_000
  const maxRedirects = options.maxRedirects ?? 5
  const headers = options.headers ?? {}
  let current = await validatePublicHttpUrl(url)

  for (let attempt = 0; attempt <= maxRedirects; attempt += 1) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    let response: Response
    try {
      response = await fetch(current, {
        headers,
        redirect: 'manual',
        signal: controller.signal,
      })
    } finally {
      clearTimeout(timer)
    }

    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get('location')
      if (!location) {
        throw new Error('missing redirect location')
      }
      current = await validatePublicHttpUrl(new URL(location, current).href)
      continue
    }

    return response
  }

  throw new Error('重定向次数过多')
}
