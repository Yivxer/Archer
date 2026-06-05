export type FetchLike = (url: string, init?: { signal?: AbortSignal }) => Promise<{ ok: boolean }>

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
