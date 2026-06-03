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
  key = 'archer-runtime-events'
): EventLog {
  const log = createEventLog(readStoredEvents(storage, key))

  function persist(): void {
    storage.setItem(key, JSON.stringify(log.all()))
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

function readStoredEvents(storage: EventLogStorage, key: string): AgentEvent[] {
  const raw = storage.getItem(key)
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.flatMap((item) => {
      const result = agentEventSchema.safeParse(item)
      return result.success ? [result.data] : []
    })
  } catch {
    return []
  }
}
