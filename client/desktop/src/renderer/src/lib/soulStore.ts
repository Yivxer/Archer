/**
 * L3.3 — soulStore
 *
 * 真值来源：/soul-profile + /soul-files + /vault/reflection/recent + 导入动作
 * 订阅者：SoulPage、ReviewPage、VaultReflectionsPanel
 *
 * 契约：docs/api-contract.md §「soulStore（L3.3）」
 */

import {
  fetchSoulFiles,
  fetchSoulProfile,
  fetchVaultReflections,
  exportPortableData,
  importSoul,
  triggerVaultReflection,
  type PortableExportResult,
} from '../adapters/soulAdapter'
import type { SoulFiles, SoulProfileSummary, VaultReflection } from '../types'
import { createExternalStore, useExternalStore, type LoadState } from './externalStore'
import { emitStoreEvent } from './storeEventBus'

// ───────────────────────── State ─────────────────────────

export type SoulStoreState = {
  profile: SoulProfileSummary | null
  files: SoulFiles
  reflections: VaultReflection[]
  loadState: LoadState
  error: string
  importing: boolean
  importMessage: string
}

const initialState: SoulStoreState = {
  profile: null,
  files: {} as SoulFiles,
  reflections: [],
  loadState: 'idle',
  error: '',
  importing: false,
  importMessage: '',
}

// ───────────────────────── Store 单例 ─────────────────────────

const store = createExternalStore<SoulStoreState>(initialState)
let loadGeneration = 0
let pendingLoad: Promise<void> | null = null

export function getSoulStoreState(): SoulStoreState {
  return store.getState()
}

export function subscribeSoulStore(listener: () => void): () => void {
  return store.subscribe(listener)
}

// ───────────────────────── Actions ─────────────────────────

/**
 * 全量加载 soul 数据（profile + files + reflections 并发）。
 */
export function loadAllSoul(options: { force?: boolean } = {}): Promise<void> {
  if (pendingLoad && !options.force) return pendingLoad
  const generation = ++loadGeneration
  store.setState((s) => ({ ...s, loadState: 'loading', error: '' }))
  pendingLoad = readSoul(generation)
  return pendingLoad
}

async function readSoul(generation: number): Promise<void> {
  try {
    const [profile, files, reflectionResult] = await Promise.all([
      fetchSoulProfile(),
      fetchSoulFiles(),
      fetchVaultReflections(10),
    ])
    if (generation !== loadGeneration) return
    if (!reflectionResult.ok) throw new Error('笔记结晶读取失败')
    store.setState((s) => ({
      ...s,
      profile,
      files,
      reflections: reflectionResult.reflections,
      loadState: 'ready',
      error: '',
    }))
  } catch (err) {
    if (generation !== loadGeneration) return
    store.setState((s) => ({
      ...s,
      loadState: 'error',
      error: err instanceof Error ? err.message : String(err),
    }))
  } finally {
    if (generation === loadGeneration) pendingLoad = null
  }
}

/**
 * 导入 soul 数据。
 */
export async function importSoulAction(soulData: Record<string, unknown>): Promise<void> {
  store.setState((s) => ({ ...s, importing: true, importMessage: '' }))
  try {
    const result = await importSoul(soulData)
    if (!result.ok) throw new Error(result.message || 'Soul 导入失败')
    await loadAllSoul({ force: true })
    store.setState((s) => ({
      ...s,
      importing: false,
      importMessage: result.message || `已导入 ${result.imported} 条`,
    }))
    // 跨域副作用只通过事件通知；main.tsx 定向重载 memoryStore。
    emitStoreEvent({ type: 'soul:imported', imported: result.imported })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      importing: false,
      importMessage: err instanceof Error ? err.message : String(err),
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

export async function exportPortableDataAction(): Promise<PortableExportResult> {
  return exportPortableData()
}

/**
 * 触发 vault reflection。
 */
export async function triggerReflectionAction(
  payload: { path?: string; days?: number; maxNotes?: number; force?: boolean },
): Promise<void> {
  try {
    const result = await triggerVaultReflection(payload)
    if (!result.ok) throw new Error('笔记结晶触发失败')
    // 写入后强制刷新，防止写入之前的读取结果覆盖新状态。
    await loadAllSoul({ force: true })
    // 跨域副作用只通过事件通知；main.tsx 定向重载 memoryStore。
    emitStoreEvent({ type: 'soul:reflection-triggered' })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

/**
 * 重置 store。
 */
export function resetSoulStore(): void {
  loadGeneration += 1
  pendingLoad = null
  store.setState(() => initialState)
}

// ───────────────────────── React hook ─────────────────────────

export function useSoulStore<U>(selector: (state: SoulStoreState) => U): U {
  return useExternalStore(store, selector)
}
