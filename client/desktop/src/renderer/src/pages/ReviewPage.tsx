import { useThreadStore } from '../lib/threadStore'
import React from 'react'
import { Brain, ChevronRight, History, Layers, Search } from 'lucide-react'
import { EmptyDetail, SearchBox } from '../components/common'
import { EmptyState } from '../components/EmptyState'
import { LoadingState } from '../components/LoadingState'
import {
  ReviewMemoryGroupsPanel,
  ReviewInitiativeShadowPanel,
  ReviewPendingMemoryPanel,
  ReviewRelatedMemoryPanel,
  ReviewSignalsPanel,
  ReviewSoulProfilePanel,
  type ReviewMemoryGroup,
} from '../components/ReviewPanels'
import type { ArcherAdapter, SessionItem, MemoryItem, Route } from '../types'
import { clearSessionDetail, loadSessionDetail, searchSessions, useSessionStore } from '../lib/sessionStore'
import { resolvePendingMemoryAction, useMemoryStore } from '../lib/memoryStore'
import { useSoulStore } from '../lib/soulStore'

export function ReviewPage({
  data,
  connected,
  onRefresh,
  onOpenSession,
  onContinueThread,
  onNavigate,
}: {
  data: ArcherAdapter
  connected: boolean
  onRefresh: () => Promise<void>
  onOpenSession: (session: SessionItem) => void
  onContinueThread?: (threadId: string) => void
  onNavigate: (route: Route) => void
}) {
  const threads = useThreadStore((state) => state.items)
  const threadLoadState = useThreadStore((state) => state.loadState)
  const [selectedId, setSelectedId] = React.useState('')
  const sessions = useSessionStore((state) => state.items)
  const listLoadState = useSessionStore((state) => state.loadState)
  const listError = useSessionStore((state) => state.listError)
  const searchError = useSessionStore((state) => state.searchError)
  const detailError = useSessionStore((state) => state.detailError)
  const detail = useSessionStore((state) => state.currentDetail)
  const detailState = useSessionStore((state) => state.detailState)
  const contentResults = useSessionStore((state) => state.searchResults)
  const searchState = useSessionStore((state) => state.searchState)
  const [query, setQuery] = React.useState('')
  const [expertFilter, setExpertFilter] = React.useState('all')
  const memoryItems = useMemoryStore((state) => state.items)
  const memoryLoadState = useMemoryStore((state) => state.loadState)
  const memoryError = useMemoryStore((state) => state.error)
  const memoryBusyIds = useMemoryStore((state) => state.busyIds)
  const [memoryNotice, setMemoryNotice] = React.useState('')
  const contentSearching = searchState === 'searching'
  const expertOptions = data.experts?.experts ?? []
  const pendingMemoryCount = memoryItems.filter((item) => item.status === 'pending').length
  const pendingReviewMemories = memoryItems.filter((item) => item.status === 'pending').slice(0, 3)
  const memoryGroups = React.useMemo(() => buildReviewMemoryGroups(memoryItems), [memoryItems])
  const canResolveMemory = connected && memoryLoadState === 'ready'

  React.useEffect(() => {
    if (!sessions.length) {
      setSelectedId('')
      clearSessionDetail()
      return
    }
    if (!sessions.some((session) => session.id === selectedId)) {
      setSelectedId(sessions[0].id)
    }
  }, [sessions, selectedId])

  React.useEffect(() => {
    if (!selectedId || !connected) {
      clearSessionDetail()
      return
    }
    void loadSessionDetail(selectedId)
  }, [selectedId, connected])

  const now = new Date()
  const todayStr = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
  const yd = new Date(now); yd.setDate(yd.getDate() - 1)
  const yesterdayStr = `${yd.getFullYear()}${String(yd.getMonth() + 1).padStart(2, '0')}${String(yd.getDate()).padStart(2, '0')}`

  function groupLabel(date: string): string {
    if (date === todayStr || date === '今天') return '今天'
    if (date === yesterdayStr || date === '昨天') return '昨天'
    return '更早'
  }

  const cleanQuery = query.trim().toLowerCase()
  const visibleSessions = React.useMemo(() => {
    const filtered = expertFilter === 'all'
      ? sessions
      : sessions.filter((session) => session.expertId === expertFilter)
    return cleanQuery
      ? filtered.filter((session) => {
        const haystack = [
          session.title,
          session.preview,
          session.date,
          session.tone,
          session.expertLabel,
          session.expertId,
        ].filter(Boolean).join(' ').toLowerCase()
        return haystack.includes(cleanQuery)
      })
      : filtered
  }, [cleanQuery, sessions, expertFilter])
  const selected = visibleSessions.find((session) => session.id === selectedId)
    ?? contentResults?.find((r) => r.id === selectedId)
    ?? visibleSessions[0]

  React.useEffect(() => {
    if (visibleSessions.length && !visibleSessions.some((session) => session.id === selectedId)) {
      setSelectedId(visibleSessions[0].id)
    }
  }, [selectedId, visibleSessions])

  const contentSearchEnabled = connected
  React.useEffect(() => {
    if (!contentSearchEnabled) {
      void searchSessions('')
      return
    }
    const trimmed = query.trim()
    if (!trimmed || trimmed.length < 2) {
      void searchSessions('')
      return
    }
    void searchSessions('')
    const timer = setTimeout(() => {
      void searchSessions(trimmed)
    }, 300)
    return () => {
      clearTimeout(timer)
    }
  }, [query, contentSearchEnabled])

  async function resolveReviewMemory(id: number, accepted: boolean) {
    if (!canResolveMemory) return
    setMemoryNotice('')
    try {
      await resolvePendingMemoryAction(id, accepted)
      setMemoryNotice(accepted ? '已确认，写入长期记忆' : '已放弃')
    } catch (error) {
      setMemoryNotice(error instanceof Error ? error.message : '记忆更新失败')
    }
  }

  const relatedMemories = React.useMemo(() => {
    if (!selected) return []
    return memoryItems
      .map((item) => ({ item, score: scoreMemoryForSession(item, selected) }))
      .filter(({ score }) => score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 4)
      .map(({ item }) => item)
  }, [memoryItems, selected])

  const reviewSignals = [
    data.periodReviews.weekly,
    data.periodReviews.monthly,
    data.periodReviews.life_stage,
  ].filter((review) => review.highlights.length || review.growth_markers.length || review.suggested_questions.length)
  const soulProfile = useSoulStore((state) => state.profile)
  const soulSections = soulProfile?.sections.filter((section) => section.items.length).slice(0, 4) ?? []

  const grouped: { label: string; sessions: typeof sessions }[] = []
  for (const session of visibleSessions) {
    const label = groupLabel(session.date)
    const existing = grouped.find((group) => group.label === label)
    if (existing) existing.sessions.push(session)
    else grouped.push({ label, sessions: [session] })
  }

  return (
    <div className="split-page">
      <div className="list-column">
        <div className="sessions-head">
          <div>
            <h1>Review</h1>
            <p>{data.status.adapter === 'local' ? '本地会话与复盘入口' : '示例会话'}</p>
          </div>
          <span>{visibleSessions.length}</span>
        </div>
        <div className="list-toolbar">
          <SearchBox placeholder="搜索会话" value={query} onChange={setQuery} />
          {expertOptions.length > 0 && (
            <select
              className="session-expert-filter"
              value={expertFilter}
              onChange={(event) => setExpertFilter(event.target.value)}
              aria-label="按专家筛选"
            >
              <option value="all">全部专家</option>
              {expertOptions.map((expert) => (
                <option key={expert.id} value={expert.id}>{expert.label}</option>
              ))}
            </select>
          )}
          <button className="quiet-button" type="button" disabled={!connected || listLoadState === 'loading'} onClick={onRefresh}>
            刷新
          </button>
        </div>
        {(listError || searchError || detailError) && <p role="alert">{listError || searchError || detailError}</p>}
        {query.trim().length >= 2 && searchState !== 'idle' ? (
          contentResults.length ? (
            <React.Fragment>
              <div className="session-group-label">
                内容匹配 {contentResults.length} 条{contentSearching ? ' · 搜索中…' : ''}
              </div>
              {contentResults.map((result) => (
                <button
                  className={`list-row ${selected?.id === result.id ? 'active' : ''}`}
                  key={result.id}
                  type="button"
                  onClick={() => setSelectedId(result.id)}
                >
                  <div>
                    <strong>{result.title}</strong>
                    <span>
                      {result.turns} 轮
                      {result.expertLabel ? ` · ${result.expertLabel}` : ''}
                    </span>
                    {result.snippet && (
                      <span className="session-preview">"{result.snippet}"</span>
                    )}
                  </div>
                  <ChevronRight size={16} />
                </button>
              ))}
            </React.Fragment>
          ) : contentSearching ? (
            <LoadingState stage="fetching" hint="搜索中…" compact />
          ) : (
            <EmptyState compact title="无内容匹配" />
          )
        ) : grouped.length ? grouped.map((group) => (
          <React.Fragment key={group.label}>
            <div className="session-group-label">{group.label}</div>
            {group.sessions.map((session) => (
              <button
                className={`list-row ${selected?.id === session.id ? 'active' : ''}`}
                key={session.id}
                type="button"
                onClick={() => setSelectedId(session.id)}
              >
                <div>
                  <strong>{session.title}</strong>
                  <span>
                    {session.turns} 轮
                    {session.expertLabel ? ` · ${session.expertLabel}` : session.tone ? ` · ${session.tone}` : ''}
                  </span>
                  {session.preview && (
                    <span className="session-preview">"{session.preview}"</span>
                  )}
                </div>
                <ChevronRight size={16} />
              </button>
            ))}
          </React.Fragment>
        )) : (
          <EmptyState compact title={listLoadState === 'loading' ? '正在读取会话…' : listLoadState === 'ready' ? '无匹配会话' : '会话尚未读取成功'} />
        )}
      </div>
      {selected ? (
        <div className="session-detail">
          <div className="session-detail-head">
            <div className="session-detail-icon"><History size={18} /></div>
            <div>
              <h2>{selected.title}</h2>
              <p>{data.status.adapter === 'local' ? '只读预览，恢复后可续写。' : '连接本地服务后读取完整消息。'}</p>
            </div>
            <button className="quiet-button strong session-open-button" type="button" onClick={() => onOpenSession(selected)}>
              恢复
            </button>
          </div>
          <div className="review-shortcuts" aria-label="复盘相关入口">
            {onContinueThread && selected.threadId && threads.some((thread) => thread.id === selected.threadId) && (
              <button type="button" className="quiet-button" disabled={!connected || threadLoadState !== 'ready'} onClick={() => onContinueThread(selected.threadId!)}>
                在新会话继续这个话题
              </button>
            )}
            <button type="button" className="quiet-button" onClick={() => onNavigate('Memory')}>
              <Brain size={15} />
              记忆审阅{pendingMemoryCount ? ` · ${pendingMemoryCount} 待确认` : ''}
            </button>
            <button type="button" className="quiet-button" onClick={() => onNavigate('Soul')}>
              <Layers size={15} />
              Soul 复盘
            </button>
          </div>
          <dl>
            <div>
              <dt>日期</dt>
              <dd>{selected.date}</dd>
            </div>
            <div>
              <dt>轮次</dt>
              <dd>{selected.turns}</dd>
            </div>
            <div>
              <dt>专家</dt>
              <dd>{selected.expertLabel || '未标记'}</dd>
            </div>
            <div>
              <dt>模式</dt>
              <dd>{selected.tone}</dd>
            </div>
          </dl>
          <ReviewRelatedMemoryPanel relatedMemories={relatedMemories} selectedId={selected.id} onNavigate={onNavigate} />
          <ReviewPendingMemoryPanel
            pendingMemoryCount={pendingMemoryCount}
            pendingReviewMemories={pendingReviewMemories}
            memoryNotice={memoryNotice || memoryError}
            canResolveMemory={canResolveMemory}
            memoryBusyId={memoryBusyIds.size ? Array.from(memoryBusyIds)[0] : null}
            onResolve={(id, accepted) => void resolveReviewMemory(id, accepted)}
            onNavigate={onNavigate}
          />
          <ReviewInitiativeShadowPanel canControl={connected} />
          <ReviewMemoryGroupsPanel memoryGroups={memoryGroups} onNavigate={onNavigate} />
          <ReviewSoulProfilePanel soulSections={soulSections} onNavigate={onNavigate} />
          <ReviewSignalsPanel reviewSignals={reviewSignals} journalReview={data.journalReview} onNavigate={onNavigate} />
          {detailState === 'loading' && <LoadingState stage="fetching" hint="读取中…" compact />}
          {detailState === 'error' && <p className="detail-error">会话读取失败</p>}
          {detail?.messages.length ? (
            <div className="session-message-list">
              {detail.messages.map((message) => (
                <article className={`session-message ${message.role}`} key={message.id}>
                  <span>{message.role}</span>
                  <p>{message.text}</p>
                </article>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <EmptyDetail icon={History} title="暂无会话" text="本地 sessions 目录为空。" />
      )}
    </div>
  )
}

function scoreMemoryForSession(memory: MemoryItem, session: SessionItem): number {
  let score = 0
  if (memory.sessionId && memory.sessionId === session.id) score += 100
  const haystack = [
    memory.content,
    memory.sessionSummary,
    memory.label,
    memory.type,
    memory.suggestReason,
  ].filter(Boolean).join(' ').toLowerCase()
  const needles = [
    session.title,
    session.preview,
    session.expertLabel,
    session.expertId,
    session.tone,
  ]
    .filter(Boolean)
    .flatMap((value) => tokenize(String(value)))
  for (const needle of needles) {
    if (haystack.includes(needle)) score += needle.length > 4 ? 8 : 3
  }
  if (memory.status === 'pending') score += 1
  return score
}

function buildReviewMemoryGroups(items: MemoryItem[]): ReviewMemoryGroup[] {
  const grouped = new Map<string, MemoryItem[]>()
  for (const item of items) {
    if (item.status !== 'confirmed') continue
    const key = item.blockType || 'insight'
    const group = grouped.get(key) ?? []
    group.push(item)
    grouped.set(key, group)
  }
  return Array.from(grouped.entries())
    .map(([key, group]) => ({
      key,
      label: memoryBlockLabel(key),
      count: group.length,
      items: group.slice(0, 2),
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 4)
}

function memoryBlockLabel(blockType: string): string {
  const map: Record<string, string> = {
    human: '档案',
    persona: 'Persona',
    preference: '偏好',
    decision: '决策',
    event: '事件',
    insight: '洞察',
  }
  return map[blockType] || blockType
}

function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[\s,.;:!?，。；：！？、'"“”‘’（）()【】\[\]<>《》/\\|-]+/)
    .map((part) => part.trim())
    .filter((part) => part.length >= 2)
}
