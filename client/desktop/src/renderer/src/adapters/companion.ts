import type { CompanionMessage } from '../types'
import { getJson, postJson } from './localArcher'

export async function fetchPendingCompanionMessage(): Promise<CompanionMessage | null> {
  const result = await getJson<{ ok: boolean; item: CompanionMessage | null }>('/companion/pending')
  return result.item
}

export async function respondToCompanionMessage(
  id: number,
  response: 'displayed' | 'continue' | 'correct' | 'suppress',
  detail = '',
): Promise<{ ok: boolean; id: number; status: string; memoryResult: string }> {
  return postJson(`/companion/${id}/respond`, { response, detail })
}
