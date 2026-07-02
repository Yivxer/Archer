import type { InitiativeEvent } from '../../../agent/contracts'
import type { InitiativeShadowReview } from '../types'

export function mergeInitiativeShadowEvent(
  current: InitiativeShadowReview,
  event: InitiativeEvent,
): InitiativeShadowReview {
  if (!event.shadow || event.delivered) return current
  const id = shadowLogId(event.id)
  if (!id || current.items.some((item) => item.id === id)) return current
  return {
    ...current,
    ok: true,
    shadow: true,
    delivered: false,
    items: [
      {
        id,
        eventType: 'initiative_event',
        kind: event.kind,
        title: event.title,
        message: event.message,
        delivered: false,
        decisionTrace: event.decisionTrace,
        createdAt: event.createdAt,
        feedback: '',
        archivedAt: null,
      },
      ...current.items,
    ].slice(0, Math.max(1, current.limit || 5)),
  }
}

function shadowLogId(value: string): number {
  const id = Number.parseInt(value.replace(/^initiative-/, ''), 10)
  return Number.isFinite(id) && id > 0 ? id : 0
}
