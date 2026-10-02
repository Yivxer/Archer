/**
 * L3.9a — storeSync
 *
 * 把 ArcherAdapter（loadLocalArcher 返回的全量数据）同步注入到 3 个兼容领域 store。
 * 渐进式接入：连接时用 adapter 初始化 store；已迁移领域随后由 store action
 * 与事件投影维护，不再依赖整份 adapter refresh。
 *
 * 调用时机：
 * - main.tsx connectLocalApi 成功后（setData 之后立即调）
 * - main.tsx connectLocalApi 成功后的初始/重连快照
 *
 * 契约：docs/api-contract.md §「L3 领域 store 契约」
 */

import type { ArcherAdapter } from '../types'
import { mergeSessionItems } from './sessionStore'
import { mergeInitiativeReview } from './initiativeStore'
import { mergeThreadItems } from './threadStore'

/**
 * 把 ArcherAdapter 的全量数据同步注入到 3 个兼容领域 store。
 *
 * Soul、Memory 由独立 HTTP/store 加载，不参与旧快照注入。
 * 注意：jobStore 的 jobs 不在此同步（jobs 由 loadJobList 独立 fetch，
 * 因为 /jobs 是独立端点，不在 loadLocalArcher 的全量响应中）。
 */
export function syncStoresFromAdapter(adapter: ArcherAdapter): void {
  // L3.4 sessionStore
  mergeSessionItems(adapter.sessions)

  // L3.6 initiativeStore
  mergeInitiativeReview(adapter.initiativeShadow)

  // L3.8 threadStore
  mergeThreadItems(adapter.threads)
}
