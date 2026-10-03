import type { ArcherAdapter, ApiConnectionState } from '../types'
import { mockArcher } from '../adapters/mockArcher'
import { loadLocalArcher, resolveDesktopApiToken } from '../adapters/localArcher'

export const BRAIN_LINKED_KEY = 'archer-brain-linked'

export type BrainSyncResult = {
  state: ApiConnectionState
  adapter: ArcherAdapter | null
  reason?: string
}

export function wasBrainEverLinked(): boolean {
  return localStorage.getItem(BRAIN_LINKED_KEY) === '1'
}

export function markBrainLinked(): void {
  localStorage.setItem(BRAIN_LINKED_KEY, '1')
}

export function createOfflineLocalShell(previous?: ArcherAdapter): ArcherAdapter {
  if (previous?.status.adapter === 'local') {
    return previous
  }

  return {
    ...mockArcher,
    status: {
      ...mockArcher.status,
      adapter: 'local',
      memoryCount: 0,
      skillCount: 0,
      tokenUsage: undefined,
    },
    chat: {
      initialMessages: [],
      toolProgress: [
        { name: 'GET /status', state: 'ready', active: true },
        { name: 'GET /memory', state: 'ready' },
        { name: 'POST /chat/stream', state: 'ready' },
      ],
      toolEvents: [],
      mockReply: '大脑暂时离线，恢复连接后会继续走本地 API。',
    },
    hypotheses: [],
    skills: [],
    proactive: { enabled: false, items: [] },
    experts: { current: 'default', experts: [] },
  }
}

export async function syncBrainData(options: {
  previous?: ArcherAdapter
  silent?: boolean
} = {}): Promise<BrainSyncResult> {
  const previous = options.previous
  const wasLocal = previous?.status.adapter === 'local' || wasBrainEverLinked()

  try {
    await resolveDesktopApiToken()
    let ensured = await window.archerDesktop?.ensureApi?.()
    if (ensured && !ensured.ok) {
      ensured = await window.archerDesktop?.ensureApi?.()
    }
    if (ensured && !ensured.ok) {
      if (ensured.reason === 'missing_python' || ensured.reason === 'missing_script') {
        return {
          state: 'error',
          adapter: wasLocal ? createOfflineLocalShell(previous) : null,
          reason: ensured.reason,
        }
      }
      return {
        state: 'api_offline',
        adapter: wasLocal ? createOfflineLocalShell(previous) : null,
        reason: ensured.reason,
      }
    }

    const adapter = await loadLocalArcher()
    markBrainLinked()
    return { state: 'connected', adapter }
  } catch (error) {
    return {
      state: 'api_offline',
      adapter: wasLocal ? createOfflineLocalShell(previous) : null,
      reason: error instanceof Error ? error.message : 'sync_failed',
    }
  }
}
