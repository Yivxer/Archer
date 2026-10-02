/** Memory HTTP projection. Transport and authorization remain shared. */
import { getJson, postJson } from './localArcher'
import type { MemoryGroup, MemoryItem, MemoryStats, MemoryResolveResult } from '../types'

export async function resolvePendingMemory(id: number, accepted: boolean): Promise<MemoryResolveResult> {
  return postJson<MemoryResolveResult>(`/memory/pending/${id}/${accepted ? 'accept' : 'reject'}`, {})
}

export async function batchResolvePendingMemory(accepted: boolean): Promise<{ ok: boolean; count?: number; deleted?: number }> {
  return postJson(`/memory/pending/batch/${accepted ? 'accept' : 'reject'}`, {})
}

export async function fetchMemoryItems(): Promise<MemoryItem[]> {
  return getJson<MemoryItem[]>('/memory?include_rejected=true')
}

export async function fetchMemoryStats(): Promise<MemoryStats> {
  return getJson<MemoryStats>('/memory/stats')
}

export async function fetchMemoryGroups(): Promise<Record<string, MemoryGroup>> {
  return getJson<Record<string, MemoryGroup>>('/memory/groups')
}

export async function updateMemory(id: number, content: string): Promise<{ ok: boolean; id: number }> {
  return postJson('/memory/update', { id, content })
}

export async function evolveMemory(id: number, content: string, type?: string, importance?: number, depth?: number): Promise<{ ok: boolean; id: number }> {
  return postJson('/memory/evolve', { id, content, type, importance, depth })
}
