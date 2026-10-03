/** Compatibility initialization for the remaining initiative snapshot. */
import type { ArcherAdapter } from '../types'
import { mergeInitiativeReview } from './initiativeStore'

export function syncStoresFromAdapter(adapter: ArcherAdapter): void {
  mergeInitiativeReview(adapter.initiativeShadow)
}
