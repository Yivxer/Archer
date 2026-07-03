/**
 * L3.8 — threadStore（ConversationThread 连续性契约）
 *
 * 真值来源：loadLocalArcher 注入 items + createLocalThread / updateLocalThread /
 *           addLocalSessionToThread 3 个 API 动作 + 前端局部更新（upsertThreadFromSave）
 * 订阅者：main.tsx（侧边栏 thread 渲染 + active thread 管理）、ChatPage（thread summary 注入）
 *
 * 契约（Archer 稳定性框架.md §ConversationThread 连续性契约）：
 * 1. 首页第一次发送成功后，后端创建 thread，前端立即把它设为当前 active thread
 * 2. 用户不点"新建对话"时，连续追问都 append 到同一 session/thread
 * 3. 侧边栏任务列表渲染 thread，而不是平铺 session
 * 4. 项目归属优先按 `threadIds`，旧 `sessionIds` 只做兼容
 * 5. 发消息前注入当前 thread summary；该 summary 不写入 session 正文，避免污染历史记录
 * 6. 旧 session 无 threadId 时允许 fallback 聚合，但不能把 fallback 当成正式迁移
 *
 * 本批只创建 store 文件不接 main.tsx（接入留 L3.9 跨页面验证时做）。
 */

import {
  addLocalSessionToThread,
  createLocalThread,
  updateLocalThread,
} from '../adapters/localArcher'
import type { ChatRequestMessage, ConversationThread } from '../types'
import { createExternalStore, useExternalStore, type LoadState } from './externalStore'

// ───────────────────────── State ─────────────────────────

export type ThreadStoreState = {
  items: ConversationThread[]
  currentThreadId: string | null
  loadState: LoadState
  error: string
}

const initialState: ThreadStoreState = {
  items: [],
  currentThreadId: null,
  loadState: 'idle',
  error: '',
}

// ───────────────────────── Store 单例 ─────────────────────────

const store = createExternalStore<ThreadStoreState>(initialState)

export function getThreadStoreState(): ThreadStoreState {
  return store.getState()
}

export function subscribeThreadStore(listener: () => void): () => void {
  return store.subscribe(listener)
}

// ───────────────────────── 内部辅助 ─────────────────────────

/** 按 id 替换或追加 thread */
function upsertThread(state: ThreadStoreState, thread: ConversationThread): ConversationThread[] {
  const idx = state.items.findIndex((t) => t.id === thread.id)
  if (idx === -1) return [thread, ...state.items]
  return state.items.map((t) => (t.id === thread.id ? thread : t))
}

// ───────────────────────── Actions ─────────────────────────

/**
 * 由 loadLocalArcher 注入 items（不触发 API）。
 * 保留 currentThreadId（如果新 items 中仍存在）。
 */
export function mergeThreadItems(items: ConversationThread[]): void {
  store.setState((s) => {
    const currentThreadId =
      s.currentThreadId && items.some((t) => t.id === s.currentThreadId)
        ? s.currentThreadId
        : null
    return { ...s, items, currentThreadId, loadState: 'ready', error: '' }
  })
}

/**
 * 设置当前活跃 thread（用户点击侧边栏 thread 或新建对话后）。
 * 传 null 清空（新建对话时）。
 */
export function setCurrentThread(threadId: string | null): void {
  store.setState((s) => ({ ...s, currentThreadId: threadId }))
}

/**
 * 创建新 thread（调 API）。
 * 成功后加入 items 并设为 current。
 *
 * 契约 1：首页第一次发送成功后，后端创建 thread，前端立即把它设为当前 active thread。
 */
export async function createThread(
  messages: ChatRequestMessage[],
  title?: string,
): Promise<ConversationThread | null> {
  try {
    const thread = await createLocalThread(messages, title)
    store.setState((s) => ({
      ...s,
      items: upsertThread(s, thread),
      currentThreadId: thread.id,
      error: '',
    }))
    return thread
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    return null
  }
}

/**
 * 更新 thread（调 API，持久化 summary/title/projectId/archived）。
 * 成功后局部更新 items。
 *
 * 契约 5：发消息前注入当前 thread summary；该 summary 不写入 session 正文。
 * summary 由前端 summarizeThreadMessages 生成，通过此 action 持久化。
 */
export async function updateThread(
  threadId: string,
  patch: Partial<Pick<ConversationThread, 'title' | 'summary' | 'projectId' | 'archived'>>,
): Promise<void> {
  try {
    const updated = await updateLocalThread(threadId, patch)
    store.setState((s) => ({
      ...s,
      items: upsertThread(s, updated),
      error: '',
    }))
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

/**
 * 关联 session 到 thread（调 API）。
 * 成功后局部更新 items（thread.sessionIds 追加 sessionId）。
 *
 * 契约 2：用户不点"新建对话"时，连续追问都 append 到同一 session/thread。
 */
export async function linkSessionToThread(
  threadId: string,
  sessionId: string,
): Promise<void> {
  try {
    const updated = await addLocalSessionToThread(threadId, sessionId)
    store.setState((s) => ({
      ...s,
      items: upsertThread(s, updated),
      error: '',
    }))
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

/**
 * 前端局部更新 thread（不调 API，用于保存会话后立即更新 UI）。
 *
 * 与 main.tsx 原 upsertSavedSessionSnapshot 的 thread 更新逻辑等价：
 * - 已存在 thread → 替换（更新 summary/updatedAt/sessionIds）
 * - 不存在 thread → 追加到列表头部
 *
 * 注意：此 action 不持久化到后端，需配合 updateThread / linkSessionToThread 使用。
 */
export function upsertThreadFromSave(thread: ConversationThread): void {
  store.setState((s) => ({
    ...s,
    items: upsertThread(s, thread),
  }))
}

/**
 * 获取当前活跃 thread（只读 selector 辅助）。
 */
export function getCurrentThread(): ConversationThread | null {
  const { items, currentThreadId } = store.getState()
  if (!currentThreadId) return null
  return items.find((t) => t.id === currentThreadId) || null
}

/**
 * 重置 store。
 */
export function resetThreadStore(): void {
  store.setState(() => initialState)
}

// ───────────────────────── React hook ─────────────────────────

export function useThreadStore<U>(selector: (state: ThreadStoreState) => U): U {
  return useExternalStore(store, selector)
}
