export type FetchLike = (
  url: string,
  init?: { signal?: AbortSignal; headers?: Record<string, string> }
) => Promise<{ ok: boolean }>

export async function probeExistingApi(
  fetchImpl: FetchLike = fetch,
  baseUrl = 'http://127.0.0.1:8765',
  timeoutMs = 600
): Promise<boolean> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetchImpl(`${baseUrl}/health`, { signal: controller.signal })
    return response.ok
  } catch {
    return false
  } finally {
    clearTimeout(timeout)
  }
}

export async function verifyApiToken(
  fetchImpl: FetchLike = fetch,
  token: string,
  baseUrl = 'http://127.0.0.1:8765',
  timeoutMs = 800
): Promise<boolean> {
  const clean = token.trim()
  if (!clean) return false
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetchImpl(`${baseUrl}/status`, {
      signal: controller.signal,
      headers: { Authorization: `Bearer ${clean}` },
    })
    return response.ok
  } catch {
    return false
  } finally {
    clearTimeout(timeout)
  }
}

export async function waitForHealthyApi(
  fetchImpl: FetchLike = fetch,
  baseUrl = 'http://127.0.0.1:8765',
  timeoutMs = 8000,
  intervalMs = 250
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await probeExistingApi(fetchImpl, baseUrl, Math.min(600, intervalMs))) {
      return true
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
  return false
}
