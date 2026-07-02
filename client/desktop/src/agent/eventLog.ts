import type { AgentEvent } from './contracts'
import { agentEventSchema } from './contractSchemas'

export type EventLog = {
  append: (event: AgentEvent) => void
  appendMany: (events: AgentEvent[]) => void
  all: () => AgentEvent[]
  forSession: (sessionId: string) => AgentEvent[]
  get: (eventId: string) => AgentEvent | undefined
  clearSession: (sessionId: string) => void
  clear: () => void
}

export type EventLogStorage = {
  getItem: (key: string) => string | null
  setItem: (key: string, value: string) => void
  removeItem: (key: string) => void
}

const DEFAULT_PERSISTED_EVENT_LIMIT = 200
const PERSISTED_EVENT_TYPES = new Set<AgentEvent['type']>([
  'tool.request',
  'tool.result',
  'approval.result',
  'job.event',
  'plan.event',
  'orchestration.event',
  'status.event',
  'runtime.context',
  'failure.hint',
])

export function createEventLog(initial: AgentEvent[] = []): EventLog {
  const events: AgentEvent[] = []
  const seen = new Set<string>()

  function append(event: AgentEvent): void {
    if (seen.has(event.id)) return
    seen.add(event.id)
    events.push(event)
  }

  for (const event of initial) append(event)

  return {
    append,
    appendMany(nextEvents) {
      for (const event of nextEvents) append(event)
    },
    all() {
      return [...events]
    },
    forSession(sessionId) {
      return events.filter((event) => event.sessionId === sessionId)
    },
    get(eventId) {
      return events.find((event) => event.id === eventId)
    },
    clearSession(sessionId) {
      const kept = events.filter((event) => event.sessionId !== sessionId)
      events.length = 0
      seen.clear()
      for (const event of kept) append(event)
    },
    clear() {
      events.length = 0
      seen.clear()
    },
  }
}

export function createPersistentEventLog(
  storage: EventLogStorage,
  key = 'archer-runtime-events',
  limit = DEFAULT_PERSISTED_EVENT_LIMIT,
): EventLog {
  const log = createEventLog(readStoredEvents(storage, key, limit))

  function persist(): void {
    const cached = limitStoredEvents(log.all(), limit)
    if (cached.length) {
      storage.setItem(key, JSON.stringify(cached))
    } else {
      storage.removeItem(key)
    }
  }

  return {
    append(event) {
      const before = log.all().length
      log.append(event)
      if (log.all().length !== before) persist()
    },
    appendMany(events) {
      const before = log.all().length
      log.appendMany(events)
      if (log.all().length !== before) persist()
    },
    all: log.all,
    forSession: log.forSession,
    get: log.get,
    clearSession(sessionId) {
      log.clearSession(sessionId)
      persist()
    },
    clear() {
      log.clear()
      storage.removeItem(key)
    },
  }
}

function shouldPersistEvent(event: AgentEvent): boolean {
  return PERSISTED_EVENT_TYPES.has(event.type)
}

function limitStoredEvents(events: AgentEvent[], limit: number): AgentEvent[] {
  const cleanLimit = Math.max(0, Math.floor(Number.isFinite(limit) ? limit : DEFAULT_PERSISTED_EVENT_LIMIT))
  if (cleanLimit === 0) return []
  const persisted = events.filter(shouldPersistEvent)
  if (persisted.length <= cleanLimit) return persisted

  // 保护 pending approval：requiresApproval=true 且尚无对应 approval.result 的事件不参与截断
  // 避免长时间使用后 pending approval 被截断，用户无法批准/拒绝工具
  const approvedEventIds = new Set(
    persisted
      .filter((e) => e.type === 'approval.result')
      .map((e) => (e as { toolEventId?: string }).toolEventId)
      .filter(Boolean) as string[]
  )
  const protectedEvents = persisted.filter((e) => {
    if (e.type !== 'tool.request') return false
    const req = e as { requiresApproval?: boolean; id?: string }
    return req.requiresApproval && !approvedEventIds.has(req.id || '')
  })
  const protectedIds = new Set(protectedEvents.map((e) => e.id))
  const remaining = persisted.filter((e) => !protectedIds.has(e.id))
  // 普通事件截断到 cleanLimit - protectedEvents.length，保护事件始终保留
  const remainingLimit = Math.max(0, cleanLimit - protectedEvents.length)
  return [...remaining.slice(-remainingLimit), ...protectedEvents]
}

function readStoredEvents(storage: EventLogStorage, key: string, limit: number): AgentEvent[] {
  const raw = storage.getItem(key)
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return limitStoredEvents(parsed.flatMap((item) => {
      const result = agentEventSchema.safeParse(item)
      return result.success ? [result.data] : []
    }), limit)
  } catch {
    return []
  }
}
