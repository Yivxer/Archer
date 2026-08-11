import { describe, expect, it } from 'vitest'
import type { AgentEvent } from '../contracts'
import { createEventLog, createPersistentEventLog, type EventLogStorage } from '../eventLog'

function event(id: string, type: AgentEvent['type']): AgentEvent {
  if (type === 'text.delta') {
    return { type, id, sessionId: 's1', createdAt: id, text: id }
  }
  if (type === 'tool.request') {
    return {
      type,
      id,
      sessionId: 's1',
      createdAt: id,
      toolName: 'obsidian_read',
      displayName: 'Obsidian Read',
      risk: 'low',
      status: 'complete',
      args: {},
      summary: id,
      detail: id,
      requiresApproval: false,
      blocked: false,
    }
  }
  return {
    type: 'runtime.error',
    id,
    sessionId: 's1',
    createdAt: id,
    scope: 'adapter',
    message: id,
    recoverable: true,
  }
}

describe('event log', () => {
  it('appends events in order', () => {
    const log = createEventLog()
    log.append(event('1', 'text.delta'))
    log.append(event('2', 'text.delta'))
    expect(log.all().map((item) => item.id)).toEqual(['1', '2'])
  })

  it('deduplicates repeated event ids', () => {
    const log = createEventLog()
    log.append(event('1', 'text.delta'))
    log.append(event('1', 'text.delta'))
    expect(log.all()).toHaveLength(1)
  })

  it('filters events by session', () => {
    const log = createEventLog()
    log.append(event('1', 'text.delta'))
    log.append({ ...event('2', 'text.delta'), sessionId: 's2' })
    expect(log.forSession('s1')).toHaveLength(1)
  })

  it('persists events to storage and reloads them', () => {
    const storage = memoryStorage()
    const log = createPersistentEventLog(storage, 'events')
    log.append(event('1', 'tool.request'))

    const reloaded = createPersistentEventLog(storage, 'events')

    expect(reloaded.all().map((item) => item.id)).toEqual(['1'])
  })

  it('does not persist text stream events', () => {
    const storage = memoryStorage()
    const log = createPersistentEventLog(storage, 'events')

    log.append(event('1', 'text.delta'))
    log.append(event('2', 'tool.request'))

    expect(JSON.parse(storage.getItem('events') || '[]').map((item: AgentEvent) => item.id)).toEqual(['2'])
    expect(createPersistentEventLog(storage, 'events').all().map((item) => item.id)).toEqual(['2'])
  })

  it('ignores malformed persisted events', () => {
    const storage = memoryStorage()
    storage.setItem('events', JSON.stringify([
      event('1', 'tool.request'),
      event('text', 'text.delta'),
      { type: 'unknown', id: 'bad' },
    ]))

    const log = createPersistentEventLog(storage, 'events')

    expect(log.all().map((item) => item.id)).toEqual(['1'])
  })

  it('keeps only the latest 200 persisted events', () => {
    const storage = memoryStorage()
    const log = createPersistentEventLog(storage, 'events')

    for (let index = 0; index < 205; index += 1) {
      log.append(event(String(index), 'tool.request'))
    }

    const persisted = JSON.parse(storage.getItem('events') || '[]') as AgentEvent[]
    expect(persisted).toHaveLength(200)
    expect(persisted[0].id).toBe('5')
    expect(persisted[199].id).toBe('204')
  })

  it('clears persisted events', () => {
    const storage = memoryStorage()
    const log = createPersistentEventLog(storage, 'events')
    log.append(event('1', 'tool.request'))
    log.clear()

    expect(storage.getItem('events')).toBeNull()
    expect(log.all()).toHaveLength(0)
  })

  it('clears one session without removing other sessions', () => {
    const log = createEventLog()
    log.append(event('1', 'text.delta'))
    log.append({ ...event('2', 'text.delta'), sessionId: 's2' })

    log.clearSession('s1')

    expect(log.all().map((item) => item.id)).toEqual(['2'])
  })

  it('rebinds pending events when a new chat receives its persisted session id', () => {
    const storage = memoryStorage()
    const log = createPersistentEventLog(storage, 'events')
    log.append({ ...event('plan-1', 'tool.request'), sessionId: 'desktop-session' })
    log.append({ ...event('other-1', 'tool.request'), sessionId: 'existing-session' })

    log.moveSession('desktop-session', 'saved-session')

    expect(log.forSession('saved-session').map((item) => item.id)).toEqual(['plan-1'])
    expect(log.forSession('desktop-session')).toEqual([])
    expect(log.forSession('existing-session').map((item) => item.id)).toEqual(['other-1'])
    expect(createPersistentEventLog(storage, 'events').forSession('saved-session').map((item) => item.id)).toEqual(['plan-1'])
  })
})

function memoryStorage(): EventLogStorage {
  const values = new Map<string, string>()
  return {
    getItem(key) {
      return values.get(key) ?? null
    },
    setItem(key, value) {
      values.set(key, value)
    },
    removeItem(key) {
      values.delete(key)
    },
  }
}
