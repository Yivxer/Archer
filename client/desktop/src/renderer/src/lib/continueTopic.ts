const THREAD_ID_PATTERN = /^[A-Za-z0-9_-]{1,96}$/

export function canContinueTopic(threadId: string | undefined | null): threadId is string {
  return typeof threadId === 'string' && THREAD_ID_PATTERN.test(threadId)
}

/**
 * Existing continue path, with one prelude: a well-formed id missing from the
 * live index is upserted first. Known ids skip that call. Invalid ids fail
 * before either step. This does not save a session.
 */
export async function continueTopicFromReview(input: {
  threadId: string
  title: string
  sessionId: string
  indexed: boolean
  ensure: (threadId: string, meta: { title: string; sessionId: string }) => Promise<{ id: string } | null>
  continueThread: (threadId: string) => void
}): Promise<void> {
  if (!canContinueTopic(input.threadId)) {
    throw new Error('invalid threadId')
  }
  if (!input.indexed) {
    const ensured = await input.ensure(input.threadId, {
      title: input.title,
      sessionId: input.sessionId,
    })
    if (!ensured) return
    if (ensured.id !== input.threadId) throw new Error('invalid threadId')
  }
  input.continueThread(input.threadId)
}
