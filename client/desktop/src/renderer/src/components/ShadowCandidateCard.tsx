import React from 'react'
import { BellOff, Check, LoaderCircle, VolumeX } from 'lucide-react'
import type { InitiativeShadowItem } from '../types'
import { ThreadClueActions } from './ThreadClueActions'

export function ShadowCandidateCard({
  item,
  busy,
  notice,
  onAcknowledge,
  onTooFrequent,
  onMute,
  onViewAll,
  onRefresh,
  canControl = false,
}: {
  item: InitiativeShadowItem
  busy: string
  notice: string
  onAcknowledge: () => void
  onTooFrequent: () => void
  onMute: () => void
  onViewAll: () => void
  onRefresh?: () => Promise<void>
  canControl?: boolean
}) {
  return (
    <section className="workspace-shadow-card" aria-label="Archer 观察候选">
      <div className="workspace-panel-head">
        <span>Archer 注意到…</span>
        <button type="button" onClick={onViewAll}>查看全部</button>
      </div>
      <strong>{item.title || '还有一个话题没有结束'}</strong>
      <p>{item.message}</p>
      <small>这是 Archer 的观察候选，不代表已经理解正确。</small>
      <div className="workspace-shadow-actions">
        <button type="button" disabled={Boolean(busy)} onClick={onAcknowledge}>
          {busy === `${item.id}:acknowledged` ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />}
          认可
        </button>
        <button type="button" disabled={Boolean(busy)} onClick={onTooFrequent}>
          {busy === `${item.id}:too_frequent` ? <LoaderCircle size={13} className="spin" /> : <VolumeX size={13} />}
          太频繁
        </button>
        <button type="button" disabled={Boolean(busy)} onClick={onMute}>
          {busy === 'presence' ? <LoaderCircle size={13} className="spin" /> : <BellOff size={13} />}
          静音
        </button>
      </div>
      <ThreadClueActions item={item} disabled={!canControl || Boolean(busy)} onRefresh={onRefresh} />
      {notice && <em role="status">{notice}</em>}
    </section>
  )
}
