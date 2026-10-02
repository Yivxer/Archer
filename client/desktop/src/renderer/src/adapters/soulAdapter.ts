import type { SoulFiles, SoulImportResult, SoulProfileSummary, VaultReflection, VaultReflectionResult } from '../types'
import { getJson, postJson } from './localArcher'

export interface PortableExportResult {
  ok: boolean
  jsonPath: string
  markdownPath: string
}

export async function fetchSoulProfile(): Promise<SoulProfileSummary> {
  return getJson<SoulProfileSummary>('/soul-profile')
}

export async function fetchSoulFiles(): Promise<SoulFiles> {
  return getJson<SoulFiles>('/soul-files')
}

export async function exportPortableData(): Promise<PortableExportResult> {
  return postJson<PortableExportResult>('/exports/portable', {})
}

export async function importSoul(soulData: Record<string, unknown>): Promise<SoulImportResult> {
  return postJson<SoulImportResult>('/soul/import', { soulData })
}

export async function fetchVaultReflections(limit: number = 20): Promise<{ ok: boolean; reflections: VaultReflection[] }> {
  return getJson<{ ok: boolean; reflections: VaultReflection[] }>(`/vault/reflection/recent?limit=${limit}`)
}

export async function triggerVaultReflection(payload: { path?: string; days?: number; maxNotes?: number; force?: boolean }): Promise<VaultReflectionResult> {
  return postJson<VaultReflectionResult>('/vault/reflection', payload)
}
