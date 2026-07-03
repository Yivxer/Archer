/**
 * L3.9a — storeSync
 *
 * 把 ArcherAdapter（loadLocalArcher 返回的全量数据）同步注入到 6 个领域 store。
 * 渐进式接入：store 作为影子真值，不破坏现有 data 流。
 *
 * 调用时机：
 * - main.tsx connectLocalApi 成功后（setData 之后立即调）
 * - main.tsx patchMemoryItems / patchExpertWorkbench 等局部更新后
 *
 * 契约：docs/api-contract.md §「L3 领域 store 契约」
 */

import type { ArcherAdapter } from '../types'
import { mergeMemoryItems } from './memoryStore'
import { mergeSoulFiles, mergeSoulProfile } from './soulStore'
import { mergeSessionItems } from './sessionStore'
import { mergeInitiativeReview } from './initiativeStore'
import { mergeThreadItems } from './threadStore'

/**
 * 把 ArcherAdapter 的全量数据同步注入到 6 个领域 store。
 *
 * 注意：jobStore 的 jobs 不在此同步（jobs 由 loadJobList 独立 fetch，
 * 因为 /jobs 是独立端点，不在 loadLocalArcher 的全量响应中）。
 */
export function syncStoresFromAdapter(adapter: ArcherAdapter): void {
  // L3.2 memoryStore
  mergeMemoryItems(adapter.memory)

  // L3.3 soulStore
  mergeSoulProfile(adapter.soulProfile)
  mergeSoulFiles(adapter.soulFiles)

  // L3.4 sessionStore
  mergeSessionItems(adapter.sessions)

  // L3.6 initiativeStore
  mergeInitiativeReview(adapter.initiativeShadow)

  // L3.8 threadStore
  mergeThreadItems(adapter.threads)
}
