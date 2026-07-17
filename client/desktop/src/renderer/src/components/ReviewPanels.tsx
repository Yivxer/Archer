import React from 'react'
import { Check, LoaderCircle, ShieldCheck, X } from 'lucide-react'
import { setInitiativeDeliveryOptIn } from '../adapters/localArcher'
import type { InitiativeShadowReview, JournalReview, MemoryItem, PeriodReview, Route, SoulProfileSection } from '../types'

export type ReviewMemoryGroup = {
  key: string
  label: string
  count: number
  items: MemoryItem[]
}

export function ReviewRelatedMemoryPanel({
  relatedMemories,
  selectedId,
  onNavigate,
}: {
  relatedMemories: MemoryItem[]
  selectedId: string
  onNavigate: (route: Route) => void
}) {
  return (
    <section className="review-memory-panel" aria-label="相关记忆">
      <div className="review-section-head">
        <div>
          <h3>相关记忆</h3>
          <p>{relatedMemories.length ? '按会话 ID、标题和摘要自动关联。' : '还没有找到直接关联的记忆。'}</p>
        </div>
        <button className="quiet-button" type="button" onClick={() => onNavigate('Memory')}>
          查看记忆
        </button>
      </div>
      {relatedMemories.length ? (
        <div className="review-memory-list">
          {relatedMemories.map((memory) => (
            <article className="review-memory-card" key={memory.id}>
              <div className="review-memory-meta">
                <span>{memory.type}</span>
                <span>{memory.status === 'pending' ? '待确认' : '已保存'}</span>
                {memory.sessionId === selectedId && <span>本会话</span>}
              </div>
              <p>{memory.content}</p>
              {memory.sessionSummary && <small>对话：{memory.sessionSummary}</small>}
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-inline review-empty">
          暂无直接关联。可以去记忆页审阅 pending 记忆，或恢复该会话继续沉淀。
        </div>
      )}
    </section>
  )
}

export function ReviewPendingMemoryPanel({
  pendingMemoryCount,
  pendingReviewMemories,
  memoryNotice,
  canResolveMemory,
  memoryBusyId,
  onResolve,
  onNavigate,
}: {
  pendingMemoryCount: number
  pendingReviewMemories: MemoryItem[]
  memoryNotice: string
  canResolveMemory: boolean
  memoryBusyId: number | null
  onResolve: (id: number, accepted: boolean) => void
  onNavigate: (route: Route) => void
}) {
  return (
    <section className="review-pending-panel" aria-label="待确认记忆">
      <div className="review-section-head">
        <div>
          <h3>待确认记忆</h3>
          <p>{pendingMemoryCount ? `还有 ${pendingMemoryCount} 条 pending，先处理最近 ${pendingReviewMemories.length} 条。` : '当前没有待确认记忆。'}</p>
        </div>
        <button className="quiet-button" type="button" onClick={() => onNavigate('Memory')}>
          全部审阅
        </button>
      </div>
      {memoryNotice && <div className="memory-state compact">{memoryNotice}</div>}
      {pendingReviewMemories.length ? (
        <div className="review-pending-list">
          {pendingReviewMemories.map((memory) => (
            <article className="review-pending-card" key={memory.id}>
              <div>
                <span>{memory.type}</span>
                <p>{memory.content}</p>
                {memory.sessionSummary && <small>对话：{memory.sessionSummary}</small>}
              </div>
              {canResolveMemory && (
                <div className="review-pending-actions">
                  <button className="quiet-button" type="button" disabled={memoryBusyId === memory.id} onClick={() => onResolve(memory.id, false)}>
                    <X size={14} />
                  </button>
                  <button className="quiet-button strong" type="button" disabled={memoryBusyId === memory.id} onClick={() => onResolve(memory.id, true)}>
                    <Check size={14} />
                  </button>
                </div>
              )}
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-inline review-empty">暂无 pending 记忆。</div>
      )}
    </section>
  )
}

export function ReviewMemoryGroupsPanel({
  memoryGroups,
  onNavigate,
}: {
  memoryGroups: ReviewMemoryGroup[]
  onNavigate: (route: Route) => void
}) {
  return (
    <section className="review-groups-panel" aria-label="记忆分类">
      <div className="review-section-head">
        <div>
          <h3>记忆分类</h3>
          <p>{memoryGroups.length ? '从已保存记忆中抽取主要分类，帮助复盘时快速定位长期线索。' : '还没有可浏览的已保存记忆。'}</p>
        </div>
        <button className="quiet-button" type="button" onClick={() => onNavigate('Memory')}>
          打开分类
        </button>
      </div>
      {memoryGroups.length ? (
        <div className="review-group-grid">
          {memoryGroups.map((group) => (
            <article className="review-group-card" key={group.key}>
              <div className="review-group-card-head">
                <strong>{group.label}</strong>
                <span>{group.count} 条</span>
              </div>
              {group.items.map((memory) => (
                <p key={memory.id}>{memory.content}</p>
              ))}
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-inline review-empty">暂无已保存记忆分类。</div>
      )}
    </section>
  )
}

export function ReviewInitiativeShadowPanel({
  initiativeShadow,
  canControl,
  onRefresh,
}: {
  initiativeShadow: InitiativeShadowReview
  canControl: boolean
  onRefresh: () => Promise<void>
}) {
  const latest = initiativeShadow.items
    .filter((item) => item.kind === 'thread_resume')
    .slice(0, 3)
  const [busy, setBusy] = React.useState(false)
  const [notice, setNotice] = React.useState('')

  async function toggleOptIn() {
    if (!canControl || busy) return
    const enabled = !initiativeShadow.optIn.enabled
    setBusy(true)
    setNotice('')
    try {
      await setInitiativeDeliveryOptIn(enabled)
      await onRefresh()
      setNotice(enabled ? '已授权话题拾起' : '已关闭，未发送项已取消')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '授权状态更新失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="review-signal-panel" aria-label="话题拾起记录">
      <div className="review-section-head">
        <div>
          <h3>话题拾起</h3>
          <p>{latest.length ? '应用内回看；每日最多一次，不进入聊天，也不触发系统通知。' : '暂无 thread_resume 候选。'}</p>
        </div>
        <span className="review-status-pill">
          {initiativeShadow.optIn.enabled ? '已授权' : initiativeShadow.globalThrottleActive ? '降频中' : 'shadow'}
        </span>
      </div>
      {canControl && (
        <button className="quiet-button" type="button" onClick={() => void toggleOptIn()} disabled={busy}>
          {busy ? <LoaderCircle size={15} className="spin" /> : <ShieldCheck size={15} />}
          {initiativeShadow.optIn.enabled ? '关闭话题拾起' : '授权话题拾起'}
        </button>
      )}
      {notice && <p className="review-action-note">{notice}</p>}
      {latest.length ? (
        <div className="review-signal-grid">
          {latest.map((item) => (
            <article className="review-signal-card" key={item.id}>
              <strong>{item.title || item.kind}</strong>
              <p>{item.message}</p>
              <small>{item.delivered ? '已发送' : '未发送'} · {item.feedback || '无反馈'}</small>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-inline review-empty">暂无可回看的话题拾起记录。</div>
      )}
    </section>
  )
}

export function ReviewSoulProfilePanel({
  soulSections,
  onNavigate,
}: {
  soulSections: SoulProfileSection[]
  onNavigate: (route: Route) => void
}) {
  return (
    <section className="review-soul-panel" aria-label="Soul Profile 摘要">
      <div className="review-section-head">
        <div>
          <h3>Soul Profile</h3>
          <p>{soulSections.length ? '把当前人格档案的关键条目放进复盘上下文。' : '还没有结构化 Soul Profile。'}</p>
        </div>
        <button className="quiet-button" type="button" onClick={() => onNavigate('Soul')}>
          打开 Soul
        </button>
      </div>
      {soulSections.length ? (
        <div className="review-soul-grid">
          {soulSections.map((section) => (
            <article className={`review-soul-card ${section.id}`} key={section.id}>
              <strong>{section.label}</strong>
              <ul>
                {section.items.slice(0, 2).map((item, index) => (
                  <li key={`${section.id}-${index}`}>{item}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-inline review-empty">暂无 Soul Profile 摘要。</div>
      )}
    </section>
  )
}

export function ReviewSignalsPanel({
  reviewSignals,
  journalReview,
  onNavigate,
}: {
  reviewSignals: PeriodReview[]
  journalReview: JournalReview
  onNavigate: (route: Route) => void
}) {
  return (
    <section className="review-signal-panel" aria-label="复盘信号">
      <div className="review-section-head">
        <div>
          <h3>复盘信号</h3>
          <p>从周期复盘中拿最短的回看线索。</p>
        </div>
        <button className="quiet-button" type="button" onClick={() => onNavigate('Soul')}>
          打开 Soul
        </button>
      </div>
      <div className="review-signal-grid">
        {reviewSignals.map((review) => (
          <article className="review-signal-card" key={review.period}>
            <strong>{review.title}</strong>
            {review.highlights[0] && <p>{review.highlights[0]}</p>}
            {review.growth_markers[0] && <small>{review.growth_markers[0]}</small>}
            {review.suggested_questions[0] && <em>{review.suggested_questions[0]}</em>}
          </article>
        ))}
        {journalReview.configured && journalReview.entries[0] && (
          <article className="review-signal-card">
            <strong>日记回看</strong>
            <p>{journalReview.entries[0].preview}</p>
            <small>{journalReview.metrics.entries} 篇 · {journalReview.metrics.characters} 字</small>
          </article>
        )}
      </div>
    </section>
  )
}
