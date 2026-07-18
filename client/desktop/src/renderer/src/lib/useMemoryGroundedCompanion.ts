import React from 'react'
import { fetchPendingCompanionMessage, respondToCompanionMessage } from '../adapters/companion'
import type { ChatMessage, CompanionMessage } from '../types'

function directResponse(text: string): 'continue' | 'correct' | 'suppress' | null {
  const normalized = text.trim().replace(/[。！!？?]+$/g, '')
  if (normalized === '继续') return 'continue'
  if (normalized === '不是这个') return 'correct'
  if (normalized === '别再提醒') return 'suppress'
  return null
}

export function useMemoryGroundedCompanion({
  enabled,
  scopeId,
  setMessages,
  onControlFailure,
}: {
  enabled: boolean
  scopeId: string
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>
  onControlFailure: () => void
}) {
  const [message, setMessage] = React.useState<CompanionMessage | null>(null)
  const seenRef = React.useRef<Set<number>>(new Set())

  React.useEffect(() => {
    if (!enabled) return
    let cancelled = false
    void fetchPendingCompanionMessage().then(async (item) => {
      if (!item || cancelled || seenRef.current.has(item.id)) return
      await respondToCompanionMessage(item.id, 'displayed')
      if (cancelled) return
      seenRef.current.add(item.id)
      setMessage(item)
      setMessages((current) => [...current, {
        id: Math.max(0, ...current.map((entry) => entry.id)) + 1,
        role: 'assistant',
        text: item.message,
        detail: '来自已确认的未完成事项',
      }])
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [enabled, scopeId, setMessages])

  async function recordDirectReply(text: string) {
    const response = message ? directResponse(text) : null
    if (!message || !response) return
    try {
      await respondToCompanionMessage(message.id, response, text)
    } catch {
      onControlFailure()
    }
  }

  return { companionMessage: message, recordDirectReply }
}
