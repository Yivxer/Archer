import React from 'react'
import {
  claimInitiativeReviewCandidateAction,
  setInitiativePresenceAction,
  submitInitiativeFeedbackAction,
  useInitiativeStore,
} from './initiativeStore'

export type ShadowFeedbackSurface = 'chat_workspace' | 'today'

export function useShadowFeedback({
  canControl,
  claimDailyCandidate = false,
  surface,
  onRefresh,
}: {
  canControl: boolean
  claimDailyCandidate?: boolean
  surface: ShadowFeedbackSurface
  onRefresh?: () => Promise<void>
}) {
  const review = useInitiativeStore((state) => state.review)
  const reviewCandidate = useInitiativeStore((state) => state.reviewCandidate)
  const candidateState = useInitiativeStore((state) => state.candidateState)
  const storeError = useInitiativeStore((state) => state.error)
  const [busy, setBusy] = React.useState('')
  const [notice, setNotice] = React.useState('')

  React.useEffect(() => {
    if (!canControl || !claimDailyCandidate || candidateState !== 'idle') return
    void claimInitiativeReviewCandidateAction()
  }, [canControl, claimDailyCandidate, candidateState])

  async function sendFeedback(id: number, feedback: 'acknowledged' | 'too_frequent') {
    if (!canControl || busy) return
    setBusy(`${id}:${feedback}`)
    setNotice('')
    try {
      await submitInitiativeFeedbackAction(id, feedback, surface)
      await onRefresh?.()
      setNotice(feedback === 'acknowledged' ? '已记录认可' : '已降低主动频率')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '反馈保存失败')
    } finally {
      setBusy('')
    }
  }

  async function togglePresence() {
    if (!canControl || busy || !review) return
    const state = review.presenceState === 'muted' ? 'idle' : 'muted'
    setBusy('presence')
    setNotice('')
    try {
      await setInitiativePresenceAction(state, surface)
      await onRefresh?.()
      setNotice(state === 'muted' ? '已静音主动候选' : '已恢复主动候选')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '在场状态更新失败')
    } finally {
      setBusy('')
    }
  }

  return {
    review,
    reviewCandidate,
    candidateState,
    busy,
    notice: notice || (candidateState === 'error' ? storeError : ''),
    sendFeedback,
    togglePresence,
  }
}
