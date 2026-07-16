/**
 * L3.9a — storeSync
 *
 * 把 ArcherAdapter（loadLocalArcher 返回的全量数据）同步注入到 6 个领域 store。
 * 渐进式接入：连接时用 adapter 初始化 store；已迁移领域随后由 store action
 * 与事件投影维护，不再依赖整份 adapter refresh。
 *
 * 调用时机：
 * - main.tsx connectLocalApi 成功后（setData 之后立即调）
 * - main.tsx connectLocalApi 成功后的初始/重连快照
 *
 * 契约：docs/api-contract.md §「L3 领域 store 契约」
 */

import type { ArcherAdapter, MemoryItem, SoulFiles, SoulProfileSummary } from '../types'
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

/**
 * 把 memoryStore 已确认的领域状态投影回仍由 App 持有的兼容 adapter。
 *
 * 这是 storeSync 从“全量快照注入”迁往“领域事件投影”的第一步：只更新
 * memory 及其派生计数，其他领域保持引用不变，避免一次 memory action
 * 重新拉取并覆盖整份 loadLocalArcher 快照。
 */
export function projectMemoryStoreToAdapter(
  adapter: ArcherAdapter,
  memory: MemoryItem[],
): ArcherAdapter {
  return {
    ...adapter,
    memory,
    status: {
      ...adapter.status,
      memoryCount: memory.filter((item) => item.status === 'confirmed').length,
      pendingMemoryCount: memory.filter((item) => item.status === 'pending').length,
    },
  }
}

/** 把 soulStore 已确认的领域状态投影回兼容 adapter，不触碰其他领域。 */
export function projectSoulStoreToAdapter(
  adapter: ArcherAdapter,
  soul: { profile: SoulProfileSummary | null; files: SoulFiles },
): ArcherAdapter {
  return {
    ...adapter,
    soulProfile: soul.profile ?? adapter.soulProfile,
    soulFiles: soul.files,
  }
}
