/** Conversation HTTP projection; shared authentication and REST contracts. */
import { getJson, postJson } from './localArcher'
import type { ChatRequestMessage, ConversationThread, SavedSession, SessionDetail, SessionItem, SessionSearchResult } from '../types'

export function listLocalSessions(): Promise<SessionItem[]> {
  return getJson<SessionItem[]>('/sessions')
}

export function listLocalThreads(): Promise<ConversationThread[]> {
  return getJson<ConversationThread[]>('/threads')
}

export async function loadLocalSession(sessionId: string): Promise<SessionDetail> {
  return getJson<SessionDetail>(`/sessions/${encodeURIComponent(sessionId)}`)
}

export async function searchLocalSessions(query: string): Promise<SessionSearchResult[]> {
  if (!query.trim()) return []
  return getJson<SessionSearchResult[]>(`/sessions/search?q=${encodeURIComponent(query)}`)
}

export type SessionSaveMeta = {
  threadId?: string
  expertId?: string
  expertLabel?: string
  modeId?: string
  modeLabel?: string
}

export async function saveLocalSession(
  messages: ChatRequestMessage[],
  meta: SessionSaveMeta = {},
): Promise<SavedSession> {
  return postJson<SavedSession>('/sessions', { messages, ...meta })
}

export async function appendLocalSession(sessionId: string, messages: ChatRequestMessage[]): Promise<SavedSession> {
  return postJson<SavedSession>(`/sessions/${encodeURIComponent(sessionId)}/append`, { messages })
}
export type SessionDeleteResult = {
  ok: boolean
  id: string
  fileDeleted: boolean
  threadRemoved?: string | null
}

export async function deleteLocalSession(sessionId: string): Promise<SessionDeleteResult> {
  return postJson<SessionDeleteResult>(`/sessions/${encodeURIComponent(sessionId)}/delete`, {})
}

export async function loadLocalThread(threadId: string): Promise<ConversationThread> {
  return getJson<ConversationThread>(`/threads/${encodeURIComponent(threadId)}`)
}

export async function createLocalThread(messages: ChatRequestMessage[], title?: string): Promise<ConversationThread> {
  return postJson<ConversationThread>('/threads', { messages, title })
}

export async function ensureLocalThread(
  threadId: string,
  meta: { title?: string; sessionId?: string } = {},
): Promise<ConversationThread> {
  return postJson<ConversationThread>(`/threads/${encodeURIComponent(threadId)}/ensure`, {
    ...(meta.title ? { title: meta.title } : {}),
    ...(meta.sessionId ? { sessionId: meta.sessionId } : {}),
  })
}

export async function updateLocalThread(
  threadId: string,
  patch: Partial<Pick<ConversationThread, 'title' | 'summary' | 'projectId' | 'archived'>>,
): Promise<ConversationThread> {
  return postJson<ConversationThread>(`/threads/${encodeURIComponent(threadId)}`, patch)
}

export async function addLocalSessionToThread(threadId: string, sessionId: string): Promise<ConversationThread> {
  return postJson<ConversationThread>(`/threads/${encodeURIComponent(threadId)}/sessions`, { sessionId })
}

