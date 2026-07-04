/**
 * L3.4 — sessionStore
 *
 * 真值来源：/sessions + /sessions/{id} + /sessions/search + 保存/续写动作
 * 订阅者：ReviewPage、侧边栏、main.tsx、ProjectsPage
 *
 * 契约：docs/api-contract.md §「sessionStore（L3.4）」
 */

import {
  appendLocalSession,
  deleteLocalSession,
  loadLocalSession,
  saveLocalSession,
  searchLocalSessions,
} from '../adapters/localArcher'
import type {
  ChatMessage,
  ChatRequestMessage,
  SessionDetail,
  SessionItem,
  SessionSearchResult,
} from '../types'
import { createExternalStore, useExternalStore, type LoadState } from './externalStore'

// ───────────────────────── State ─────────────────────────

export type SessionStoreState = {
  items: SessionItem[]
  currentDetail: SessionDetail | null
  searchResults: SessionSearchResult[]
  searchQuery: string
  loadState: LoadState
  detailState: LoadState
  searchState: 'idle' | 'searching' | 'ready' | 'error'
  error: string
}

const initialState: SessionStoreState = {
  items: [],
  currentDetail: null,
  searchResults: [],
  searchQuery: '',
  loadState: 'idle',
  detailState: 'idle',
  searchState: 'idle',
  error: '',
}

// ───────────────────────── Store 单例 ─────────────────────────

const store = createExternalStore<SessionStoreState>(initialState)

export function getSessionStoreState(): SessionStoreState {
  return store.getState()
}

export function subscribeSessionStore(listener: () => void): () => void {
  return store.subscribe(listener)
}

// ───────────────────────── Actions ─────────────────────────

/**
 * 加载会话列表摘要。
 */
export async function loadSessionList(): Promise<void> {
  store.setState((s) => ({ ...s, loadState: 'loading', error: '' }))
  try {
    // items 由 loadLocalArcher 注入，loadList 不主动 fetch /sessions
    // 这里只标记 ready，实际数据由 mergeSessionItems 注入
    store.setState((s) => ({ ...s, loadState: 'ready', error: '' }))
  } catch (err) {
    store.setState((s) => ({
      ...s,
      loadState: 'error',
      error: err instanceof Error ? err.message : String(err),
    }))
  }
}

/**
 * 加载会话详情。
 */
export async function loadSessionDetail(id: string): Promise<void> {
  store.setState((s) => ({ ...s, detailState: 'loading', error: '' }))
  try {
    const detail = await loadLocalSession(id)
    store.setState((s) => ({
      ...s,
      currentDetail: detail,
      detailState: 'ready',
      error: '',
    }))
  } catch (err) {
    store.setState((s) => ({
      ...s,
      detailState: 'error',
      error: err instanceof Error ? err.message : String(err),
    }))
  }
}

/**
 * 搜索会话（debounce 由调用方处理）。
 */
export async function searchSessions(query: string): Promise<void> {
  const trimmed = query.trim()
  if (!trimmed) {
    store.setState((s) => ({
      ...s,
      searchResults: [],
      searchQuery: '',
      searchState: 'idle',
    }))
    return
  }
  store.setState((s) => ({ ...s, searchState: 'searching', searchQuery: trimmed }))
  try {
    const results = await searchLocalSessions(trimmed)
    store.setState((s) => ({
      ...s,
      searchResults: results,
      searchState: 'ready',
    }))
  } catch (err) {
    store.setState((s) => ({
      ...s,
      searchState: 'error',
      error: err instanceof Error ? err.message : String(err),
    }))
  }
}

/**
 * 保存新会话。
 */
export async function saveSession(
  messages: ChatMessage[],
  meta?: { expertId?: string; expertLabel?: string },
): Promise<{ id: string; path: string; threadId?: string } | null> {
  try {
    const saved = await saveLocalSession(
      messages.map((m) => ({ role: m.role, content: m.text })),
      meta,
    )
    // 保存成功后需要 refresh items（由 mergeSessionItems 注入新列表）
    return { id: saved.id, path: saved.path, threadId: saved.threadId }
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    return null
  }
}

/**
 * 续写现有会话。
 */
export async function appendSession(
  id: string,
  messages: ChatRequestMessage[],
): Promise<{ id: string; path: string; threadId?: string } | null> {
  try {
    const saved = await appendLocalSession(id, messages)
    return { id: saved.id, path: saved.path, threadId: saved.threadId }
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    return null
  }
}

/**
 * 由 loadLocalArcher 注入 items（不触发 API）。
 */
export function mergeSessionItems(items: SessionItem[]): void {
  store.setState((s) => ({ ...s, items, loadState: 'ready' }))
}

/**
 * 删除一个会话（硬删除：后端会同时清理 session 文件和 thread 引用）。
 * 删除成功后从 items 中移除；若删除的是当前详情会话，则一并清空 currentDetail。
 */
export async function deleteSession(sessionId: string): Promise<{ ok: boolean; threadRemoved?: string | null }> {
  try {
    const result = await deleteLocalSession(sessionId)
    store.setState((s) => ({
      ...s,
      items: s.items.filter((item) => item.id !== sessionId),
      currentDetail: s.currentDetail?.id === sessionId ? null : s.currentDetail,
      detailState: s.currentDetail?.id === sessionId ? 'idle' : s.detailState,
      error: '',
    }))
    return { ok: true, threadRemoved: result.threadRemoved }
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    return { ok: false }
  }
}

/**
 * 清空 currentDetail（用于关闭会话详情）。
 */
export function clearSessionDetail(): void {
  store.setState((s) => ({ ...s, currentDetail: null, detailState: 'idle' }))
}

/**
 * 重置 store。
 */
export function resetSessionStore(): void {
  store.setState(() => initialState)
}

// ───────────────────────── React hook ─────────────────────────

export function useSessionStore<U>(selector: (state: SessionStoreState) => U): U {
  return useExternalStore(store, selector)
}
