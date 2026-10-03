/** Retired compatibility hook: domain stores load only their own HTTP projections. */
import type { ArcherAdapter } from '../types'

/** Regression seam for legacy snapshots; no production callers remain. */
export function syncStoresFromAdapter(_adapter: ArcherAdapter): void {}
