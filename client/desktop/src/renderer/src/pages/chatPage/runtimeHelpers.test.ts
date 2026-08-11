import { describe, expect, it } from 'vitest'

import { createEventLog } from '../../../../agent'
import type { PlanEvent } from '../../../../agent'
import { rebindNewRuntimeSession, restoreRuntimeState } from './runtimeHelpers'

function proposedPlan(sessionId: string): PlanEvent {
  return {
    type: 'plan.event',
    id: 'plan-1',
    sessionId,
    createdAt: '2026-08-11T20:55:00.000Z',
    traceId: 'trace-1',
    status: 'proposed',
    title: '结晶笔记',
    detail: '等待用户确认',
    steps: [{ id: 1, action: 'reflect_on_note', tool: 'vault_reflection', requiresApproval: true }],
  }
}

describe('runtime session rebinding', () => {
  it('keeps a proposed plan visible after the first chat is persisted', () => {
    const log = createEventLog([proposedPlan('desktop-session')])

    rebindNewRuntimeSession(log, 'desktop-session', 'saved-session')

    expect(restoreRuntimeState('saved-session', log).plans['plan-1']?.status).toBe('proposed')
  })

  it('does not move events when switching between existing sessions', () => {
    const log = createEventLog([proposedPlan('existing-session')])

    rebindNewRuntimeSession(log, 'existing-session', 'other-session')

    expect(restoreRuntimeState('existing-session', log).plans['plan-1']).toBeDefined()
    expect(restoreRuntimeState('other-session', log).plans['plan-1']).toBeUndefined()
  })
})
