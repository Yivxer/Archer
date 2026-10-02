import React from 'react'
import type { ThreadClueStatus } from '../adapters/threadClues'
import { transitionThreadClueAction } from '../lib/initiativeStore'
import type { InitiativeShadowItem } from '../types'

const actions: ReadonlyArray<{ status: ThreadClueStatus; label: string }> = [
  { status: 'resolved', label: '已完成' },
  { status: 'closed', label: '关闭' },
  { status: 'dismissed', label: '忽略' },
  { status: 'expired', label: '已过期' },
]

export function ThreadClueActions({ item, disabled = false, onRefresh }: {
  item: InitiativeShadowItem
  disabled?: boolean
  onRefresh?: () => Promise<void>
}) {
  const [busy, setBusy] = React.useState(false)
  const [notice, setNotice] = React.useState('')
  const [finished, setFinished] = React.useState(false)
  const sourceId = item.decisionTrace.threadId
  const validSource = typeof sourceId === 'number' || (typeof sourceId === 'string' && /^[0-9]+$/.test(sourceId))
  const id = Number(sourceId)
  if (!validSource || item.kind !== 'thread_resume' || !Number.isSafeInteger(id) || id <= 0 || item.archivedAt) return null

  async function update(status: ThreadClueStatus, label: string): Promise<void> {
    if (disabled || busy || finished) return
    setBusy(true)
    setNotice('')
    try {
      await transitionThreadClueAction(id, status)
      setFinished(true)
      setNotice(`已记录：${label}`)
      await onRefresh?.()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '线索状态保存失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div aria-label="话题线索状态">
      {!finished && <div className="workspace-shadow-actions">
        {actions.map(({ status, label }) => (
          <button className="quiet-button" key={status} type="button" disabled={disabled || busy}
            onClick={() => void update(status, label)}>{label}</button>
        ))}
      </div>}
      {notice && <small role="status">{notice}</small>}
    </div>
  )
}
