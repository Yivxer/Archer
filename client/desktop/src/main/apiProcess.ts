import { execFile } from 'node:child_process'
import { join } from 'node:path'

export type ApiLaunchPaths = {
  archerRoot: string
  pythonBin: string
  apiScript: string
}

export type BrainStatusReason =
  | 'missing_python'
  | 'missing_script'
  | 'port_down'
  | 'not_ready'
  | 'token_mismatch'
  | 'owned'
  | 'reused'

export type BrainStatusSnapshot = {
  pythonOk: boolean
  scriptOk: boolean
  portOk: boolean
  readyOk: boolean
  tokenOk: boolean
  owned: boolean
}

const DEFAULT_ARCHER_ROOT = '/Users/Yivxer/Projects/Archer'

function cleanEnvValue(value: string | undefined): string {
  return String(value || '').trim()
}

export function resolveApiLaunchPaths(env: NodeJS.ProcessEnv = process.env): ApiLaunchPaths {
  const archerRoot = cleanEnvValue(env.ARCHER_ROOT) || DEFAULT_ARCHER_ROOT
  const pythonBin = cleanEnvValue(env.ARCHER_PYTHON_BIN) || join(archerRoot, '.venv', 'bin', 'python3')
  const apiScript = cleanEnvValue(env.ARCHER_API_SCRIPT) || join(archerRoot, 'terminal', 'api', 'fastapi_app.py')
  return { archerRoot, pythonBin, apiScript }
}

export function brainStatusReason(snapshot: BrainStatusSnapshot): BrainStatusReason {
  if (!snapshot.pythonOk) return 'missing_python'
  if (!snapshot.scriptOk) return 'missing_script'
  if (!snapshot.portOk) return 'port_down'
  if (!snapshot.readyOk) return 'not_ready'
  if (!snapshot.tokenOk) return 'token_mismatch'
  if (snapshot.owned) return 'owned'
  return 'reused'
}

export function apiRetryDelayMs(attempt: number, baseMs = 1000, maxMs = 5000): number {
  const cleanAttempt = Math.max(0, Math.floor(Number.isFinite(attempt) ? attempt : 0))
  const delay = baseMs * (2 ** cleanAttempt)
  return Math.min(maxMs, delay)
}

export type FetchLike = (
  url: string,
  init?: { signal?: AbortSignal; headers?: Record<string, string> }
) => Promise<{ ok: boolean; status?: number }>

function isOkOrRateLimited(response: { ok: boolean; status?: number }): boolean {
  return response.ok || response.status === 429
}

function execFileText(command: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(command, args, (error, stdout) => {
      if (error) {
        reject(error)
        return
      }
      resolve(stdout)
    })
  })
}

/** Stop whatever is listening on the desktop API port so we can spawn our own process. */
export async function reclaimApiPort(port = 8765): Promise<void> {
  try {
    const stdout = await execFileText('lsof', ['-ti', `tcp:${port}`])
    const pids = stdout
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((value) => Number(value))
      .filter((pid) => Number.isFinite(pid) && pid > 0)
    for (const pid of pids) {
      try {
        process.kill(pid, 'SIGTERM')
      } catch {
        // Process may already be gone.
      }
    }
    if (pids.length) {
      await new Promise((resolve) => setTimeout(resolve, 450))
    }
  } catch {
    // Nothing listening — fine.
  }
}

export async function probeExistingApi(
  fetchImpl: FetchLike = fetch,
  baseUrl = 'http://127.0.0.1:8765',
  timeoutMs = 600
): Promise<boolean> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetchImpl(`${baseUrl}/health`, { signal: controller.signal })
    return isOkOrRateLimited(response)
  } catch {
    return false
  } finally {
    clearTimeout(timeout)
  }
}

export async function probeReadyApi(
  fetchImpl: FetchLike = fetch,
  baseUrl = 'http://127.0.0.1:8765',
  timeoutMs = 600
): Promise<boolean> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetchImpl(`${baseUrl}/ready`, { signal: controller.signal })
    return isOkOrRateLimited(response)
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
    return isOkOrRateLimited(response)
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

export async function waitForReadyApi(
  fetchImpl: FetchLike = fetch,
  baseUrl = 'http://127.0.0.1:8765',
  timeoutMs = 8000,
  intervalMs = 250
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await probeReadyApi(fetchImpl, baseUrl, Math.min(600, intervalMs))) {
      return true
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
  return false
}
