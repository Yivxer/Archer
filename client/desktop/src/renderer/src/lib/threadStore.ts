/** Conversation threads are server projections; pages subscribe directly. */

import {
  listLocalThreads,
  addLocalSessionToThread,
  createLocalThread,
  updateLocalThread,
} from '../adapters/conversationAdapter'
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
let loadGeneration = 0
let resetGeneration = 0
let pendingLoad: Promise<void> | null = null

export function loadThreadList(options: { force?: boolean } = {}): Promise<void> {
  if (pendingLoad && !options.force) return pendingLoad
  const generation = ++loadGeneration
  store.setState((state) => ({ ...state, loadState: 'loading', error: '' }))
  pendingLoad = readThreads(generation)
  return pendingLoad
}

async function readThreads(generation: number): Promise<void> {
  try {
    const items = await listLocalThreads()
    if (generation !== loadGeneration) return
    mergeThreadItems(items)
  } catch (error) {
    if (generation !== loadGeneration) return
    store.setState((state) => ({ ...state, loadState: 'error', error: error instanceof Error ? error.message : String(error) }))
  } finally {
    if (generation === loadGeneration) pendingLoad = null
  }
}

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
 * 提交服务端已确认的列表（不触发 API）。
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
  const epoch = resetGeneration
  try {
    const thread = await createLocalThread(messages, title)
    if (epoch !== resetGeneration) return null
    loadGeneration += 1
    pendingLoad = null
    store.setState((s) => ({
      ...s,
      items: upsertThread(s, thread),
      currentThreadId: thread.id,
      error: '',
    }))
    await loadThreadList({ force: true })
    return thread
  } catch (err) {
    if (epoch !== resetGeneration) throw err
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
 * 返回的摘要与上下文始终来自服务端，不从助手回复推导已确认结论。
 */
export async function updateThread(
  threadId: string,
  patch: Partial<Pick<ConversationThread, 'title' | 'summary' | 'projectId' | 'archived'>>,
): Promise<void> {
  const epoch = resetGeneration
  try {
    const updated = await updateLocalThread(threadId, patch)
    if (epoch !== resetGeneration) return
    loadGeneration += 1
    pendingLoad = null
    store.setState((s) => ({
      ...s,
      items: upsertThread(s, updated),
      error: '',
    }))
    await loadThreadList({ force: true })
  } catch (err) {
    if (epoch !== resetGeneration) throw err
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
  const epoch = resetGeneration
  try {
    const updated = await addLocalSessionToThread(threadId, sessionId)
    if (epoch !== resetGeneration) return
    loadGeneration += 1
    pendingLoad = null
    store.setState((s) => ({
      ...s,
      items: upsertThread(s, updated),
      error: '',
    }))
    await loadThreadList({ force: true })
  } catch (err) {
    if (epoch !== resetGeneration) throw err
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

export function getCurrentThread(): ConversationThread | null {
  const { items, currentThreadId } = store.getState()
  if (!currentThreadId) return null
  return items.find((t) => t.id === currentThreadId) || null
}

/**
 * 重置 store。
 */
export function resetThreadStore(): void {
  loadGeneration += 1
  resetGeneration += 1
  pendingLoad = null
  store.setState(() => initialState)
}

// ───────────────────────── React hook ─────────────────────────

export function useThreadStore<U>(selector: (state: ThreadStoreState) => U): U {
  return useExternalStore(store, selector)
}
