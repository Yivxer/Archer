import type { ArcherAdapter } from '../types'

export function defaultInitiativeShadowOptIn(): ArcherAdapter['initiativeShadow']['optIn'] {
  return {
    enabled: false,
    updatedAt: null,
    reason: 'not_set',
  }
}

export function normalizeInitiativeShadowOptIn(raw?: unknown): ArcherAdapter['initiativeShadow']['optIn'] {
  const fallback = defaultInitiativeShadowOptIn()
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return fallback
  const item = raw as Record<string, unknown>
  return {
    enabled: Boolean(item.enabled),
    updatedAt: item.updated_at || item.updatedAt ? String(item.updated_at ?? item.updatedAt) : fallback.updatedAt,
    reason: String(item.reason || fallback.reason),
  }
}

export function normalizeInitiativeShadowItem(
  item: Record<string, unknown>,
): ArcherAdapter['initiativeShadow']['items'][number] {
  const trace = item.decision_trace ?? item.decisionTrace
  return {
    id: Number(item.id || 0),
    eventType: String(item.event_type || item.eventType || ''),
    kind: String(item.kind || ''),
    title: String(item.title || ''),
    message: String(item.message || ''),
    delivered: Boolean(item.delivered),
    decisionTrace: trace && typeof trace === 'object' && !Array.isArray(trace)
      ? trace as Record<string, unknown>
      : {},
    createdAt: String(item.created_at || item.createdAt || ''),
    feedback: String(item.feedback || ''),
    archivedAt: item.archived_at || item.archivedAt ? String(item.archived_at || item.archivedAt) : null,
  }
}
