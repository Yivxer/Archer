/** Server-owned session summaries, details, search and persistence. */
import {
  appendLocalSession,
  deleteLocalSession,
  listLocalSessions,
  loadLocalSession,
  saveLocalSession,
  searchLocalSessions,
  type SessionSaveMeta,
} from '../adapters/conversationAdapter'
import type { ChatMessage, ChatRequestMessage, SavedSession, SessionDetail, SessionItem, SessionSearchResult } from '../types'
import { createExternalStore, useExternalStore, type LoadState } from './externalStore'
import { loadThreadList } from './threadStore'

export type SessionStoreState = {
  items: SessionItem[]
  currentDetail: SessionDetail | null
  searchResults: SessionSearchResult[]
  searchQuery: string
  loadState: LoadState
  detailState: LoadState
  searchState: 'idle' | 'searching' | 'ready' | 'error'
  error: string
  listError: string
  detailError: string
  searchError: string
}

const initialState: SessionStoreState = {
  items: [], currentDetail: null, searchResults: [], searchQuery: '',
  loadState: 'idle', detailState: 'idle', searchState: 'idle',
  error: '', listError: '', detailError: '', searchError: '',
}
const store = createExternalStore<SessionStoreState>(initialState)
let listRequestId = 0
let detailRequestId = 0
let searchRequestId = 0
let resetGeneration = 0
let pendingList: Promise<void> | null = null
const errorText = (error: unknown): string => error instanceof Error ? error.message : String(error)

export function getSessionStoreState(): SessionStoreState { return store.getState() }
export function subscribeSessionStore(listener: () => void): () => void { return store.subscribe(listener) }

export function loadSessionList(options: { force?: boolean } = {}): Promise<void> {
  if (pendingList && !options.force) return pendingList
  const requestId = ++listRequestId
  store.setState((state) => ({ ...state, loadState: 'loading', listError: '' }))
  pendingList = readSessions(requestId)
  return pendingList
}

async function readSessions(requestId: number): Promise<void> {
  try {
    const items = await listLocalSessions()
    if (requestId !== listRequestId) return
    mergeSessionItems(items)
  } catch (error) {
    if (requestId !== listRequestId) return
    store.setState((state) => ({ ...state, loadState: 'error', listError: errorText(error), error: errorText(error) }))
  } finally {
    if (requestId === listRequestId) pendingList = null
  }
}

export async function loadSessionDetail(id: string): Promise<SessionDetail | null> {
  const requestId = ++detailRequestId
  store.setState((state) => ({ ...state, currentDetail: null, detailState: 'loading', detailError: '' }))
  try {
    const detail = await loadLocalSession(id)
    if (requestId !== detailRequestId) return null
    store.setState((state) => ({ ...state, currentDetail: detail, detailState: 'ready', detailError: '', error: '' }))
    return detail
  } catch (error) {
    if (requestId !== detailRequestId) return null
    store.setState((state) => ({ ...state, currentDetail: null, detailState: 'error', detailError: errorText(error), error: errorText(error) }))
    return null
  }
}

export async function searchSessions(query: string): Promise<void> {
  const requestId = ++searchRequestId
  const trimmed = query.trim()
  if (!trimmed) {
    store.setState((state) => ({ ...state, searchResults: [], searchQuery: '', searchState: 'idle', searchError: '' }))
    return
  }
  store.setState((state) => ({ ...state, searchResults: [], searchState: 'searching', searchQuery: trimmed, searchError: '' }))
  try {
    const results = await searchLocalSessions(trimmed)
    if (requestId !== searchRequestId) return
    store.setState((state) => ({ ...state, searchResults: results, searchState: 'ready', searchError: '' }))
  } catch (error) {
    if (requestId !== searchRequestId) return
    store.setState((state) => ({ ...state, searchState: 'error', searchError: errorText(error), error: errorText(error) }))
  }
}

/** Save success remains success if the subsequent read fails; do not repeat the POST. */
export async function saveSessionMessages(messages: ChatRequestMessage[], meta: SessionSaveMeta = {}): Promise<SavedSession> {
  const epoch = resetGeneration
  const saved = await saveLocalSession(messages, meta)
  if (epoch === resetGeneration) await refreshConversations()
  return saved
}

export async function appendSessionMessages(id: string, messages: ChatRequestMessage[]): Promise<SavedSession> {
  const epoch = resetGeneration
  const saved = await appendLocalSession(id, messages)
  if (epoch === resetGeneration) {
    if (store.getState().currentDetail?.id === id) clearSessionDetail()
    await refreshConversations()
  }
  return saved
}

export async function refreshConversations(): Promise<void> {
  await Promise.all([loadSessionList({ force: true }), loadThreadList({ force: true })])
}

export async function saveSession(messages: ChatMessage[], meta?: SessionSaveMeta): Promise<SavedSession | null> {
  try {
    return await saveSessionMessages(messages.map((message) => ({ role: message.role, content: message.text })), meta)
  } catch (error) {
    store.setState((state) => ({ ...state, error: errorText(error) }))
    return null
  }
}

export async function appendSession(id: string, messages: ChatRequestMessage[]): Promise<SavedSession | null> {
  try {
    return await appendSessionMessages(id, messages)
  } catch (error) {
    store.setState((state) => ({ ...state, error: errorText(error) }))
    return null
  }
}

/** Commit a confirmed server list, never an ArcherAdapter compatibility snapshot. */
export function mergeSessionItems(items: SessionItem[]): void {
  store.setState((state) => ({ ...state, items, loadState: 'ready', listError: '', error: '' }))
}

export async function deleteSession(sessionId: string): Promise<{ ok: boolean; threadRemoved?: string | null }> {
  const epoch = resetGeneration
  try {
    const result = await deleteLocalSession(sessionId)
    if (!result.ok) throw new Error('会话未删除，请刷新后重试')
    if (epoch !== resetGeneration) return { ok: true, threadRemoved: result.threadRemoved }
    // Invalidate in-flight detail/search so a late response cannot resurrect deleted content.
    detailRequestId += 1
    searchRequestId += 1
    store.setState((state) => ({
      ...state, items: state.items.filter((item) => item.id !== sessionId),
      currentDetail: state.currentDetail?.id === sessionId ? null : state.currentDetail,
      detailState: state.currentDetail?.id === sessionId || state.detailState === 'loading' ? 'idle' : state.detailState,
      searchResults: state.searchResults.filter((item) => item.id !== sessionId),
      searchState: 'idle', detailError: '', searchError: '', error: '',
    }))
    await refreshConversations()
    return { ok: true, threadRemoved: result.threadRemoved }
  } catch (error) {
    if (epoch === resetGeneration) store.setState((state) => ({ ...state, error: errorText(error) }))
    return { ok: false }
  }
}

export function clearSessionDetail(): void {
  detailRequestId += 1
  store.setState((state) => ({ ...state, currentDetail: null, detailState: 'idle', detailError: '' }))
}

export function resetSessionStore(): void {
  listRequestId += 1
  detailRequestId += 1
  searchRequestId += 1
  resetGeneration += 1
  pendingList = null
  store.setState(() => initialState)
}

export function useSessionStore<U>(selector: (state: SessionStoreState) => U): U {
  return useExternalStore(store, selector)
}
