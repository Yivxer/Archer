import React from 'react'
import { Check, Database, Edit3, Heart, Settings, TrendingUp, Waves, Compass, X, Search } from 'lucide-react'
import { batchResolvePendingMemory, resolvePendingMemory, fetchMemoryStats, fetchMemoryGroups, updateMemory } from '../adapters/localArcher'
import type { ArcherAdapter, MemoryItem, MemoryStats, MemoryGroup } from '../types'
import { ConfirmDialog } from '../components/common'

type ViewMode = 'pending' | 'groups'

const groupIcons: Record<string, React.ElementType> = {
  heart: Heart, settings: Settings, waves: Waves, compass: Compass, trending_up: TrendingUp,
}

export function MemoryPage({ data, onRefresh }: { data: ArcherAdapter; onRefresh: () => Promise<void> }) {
  const [viewMode, setViewMode] = React.useState<ViewMode>('pending')
  const [items, setItems] = React.useState(data.memory)
  const [busyId, setBusyId] = React.useState<number | null>(null)
  const [batchBusy, setBatchBusy] = React.useState(false)
  const [memoryMessage, setMemoryMessage] = React.useState('')
  const [query, setQuery] = React.useState('')
  const [stats, setStats] = React.useState<MemoryStats | null>(null)
  const [groups, setGroups] = React.useState<Record<string, MemoryGroup> | null>(null)
  const [editingId, setEditingId] = React.useState<number | null>(null)
  const [editText, setEditText] = React.useState('')
  const [confirmState, setConfirmState] = React.useState<{
    title: string; message: string; confirmLabel: string; tone?: 'default' | 'danger'; onConfirm: () => void
  } | null>(null)

  React.useEffect(() => {
    setItems(data.memory)
    setBusyId(null)
  }, [data])

  React.useEffect(() => {
    if (data.status.adapter === 'local') {
      fetchMemoryStats().then(setStats).catch(() => setStats(null))
      if (viewMode === 'groups') {
        fetchMemoryGroups().then(setGroups).catch(() => setGroups(null))
      }
    }
  }, [data.status.adapter, data.memory.length, viewMode])

  async function performResolveMemory(id: number, accepted: boolean) {
    setMemoryMessage('')
    setBusyId(id)
    try {
      const result = await resolvePendingMemory(id, accepted)
      if (!result.ok) { setMemoryMessage('无待处理记忆被更新'); return }
      setMemoryMessage(accepted ? '已确认，写入长期记忆' : '已放弃')
      await onRefresh()
    } catch (error) {
      setMemoryMessage(error instanceof Error ? error.message : '记忆更新失败')
    } finally { setBusyId(null) }
  }

  function resolveMemory(id: number, accepted: boolean) {
    if (accepted) { setConfirmState({
      title: '确认这条记忆？', message: '写入长期记忆。',
      confirmLabel: '确认', tone: 'default',
      onConfirm: () => { setConfirmState(null); void performResolveMemory(id, true) }
    }); return }
    setConfirmState({
      title: '放弃这条记忆？', message: '不会进入长期记忆。',
      confirmLabel: '放弃', tone: 'danger',
      onConfirm: () => { setConfirmState(null); void performResolveMemory(id, false) }
    })
  }

  async function performBatchResolve(accepted: boolean) {
    setMemoryMessage('')
    setBatchBusy(true)
    try {
      const result = await batchResolvePendingMemory(accepted)
      setMemoryMessage(accepted ? `已全部确认，写入 ${result.count ?? 0} 条` : `已全部放弃，共 ${result.deleted ?? 0} 条`)
      await onRefresh()
    } catch (error) {
      setMemoryMessage(error instanceof Error ? error.message : '批量操作失败')
    } finally { setBatchBusy(false) }
  }

  function batchResolve(accepted: boolean) {
    const toResolve = items.filter((item) => item.status === 'pending')
    if (!toResolve.length) return
    setConfirmState({
      title: accepted ? '确认全部待处理记忆？' : '放弃全部待处理记忆？',
      message: accepted ? `${toResolve.length} 条写入长期记忆。` : `${toResolve.length} 条全部放弃。`,
      confirmLabel: accepted ? '全部确认' : '全部放弃',
      tone: accepted ? 'default' : 'danger',
      onConfirm: () => { setConfirmState(null); void performBatchResolve(accepted) }
    })
  }

  async function handleSaveEdit(id: number) {
    if (!editText.trim() || editText.trim().length < 10) return
    try {
      const result = await updateMemory(id, editText.trim())
      if (result.ok) {
        setMemoryMessage('记忆已更新')
        setEditingId(null)
        await onRefresh()
      } else {
        setMemoryMessage('更新失败')
      }
    } catch (error) {
      setMemoryMessage(error instanceof Error ? error.message : '更新失败')
    }
  }

  function startEdit(item: MemoryItem) {
    setEditingId(item.id)
    setEditText(item.content)
  }

  const pending = items.filter((item) => item.status === 'pending')
  const canResolveMemory = data.status.adapter === 'local'
  const cleanQuery = query.trim().toLowerCase()

  return (
    <div className="memory-page">
      <ConfirmDialog open={Boolean(confirmState)} title={confirmState?.title ?? ''}
        message={confirmState?.message ?? ''} confirmLabel={confirmState?.confirmLabel ?? '确认'}
        tone={confirmState?.tone ?? 'default'} onConfirm={() => confirmState?.onConfirm()} onCancel={() => setConfirmState(null)} />

      {/* ── 记忆库信息栏 ── */}
      {stats && (
        <div className="memory-stats-bar">
          <div className="memory-stats-row">
            <div className="memory-stats-icon"><Database size={15} /></div>
            <div className="memory-stats-info">
              <span>记忆库</span>
              <strong>{stats.activeCount} 条</strong>
              {stats.pendingCount > 0 && <em>· {stats.pendingCount} 待确认</em>}
              {stats.contradictions > 0 && <em>· {stats.contradictions} 矛盾</em>}
              {stats.stale > 0 && <em>· {stats.stale} 过期</em>}
            </div>
          </div>
          <div className="memory-stats-path" title={stats.dbPath}>
            {stats.dbPath.split('/').slice(-3).join('/')}
          </div>
        </div>
      )}

      {/* ── 视图切换 ── */}
      <div className="memory-toolbar">
        <div className="segmented compact-segmented">
          <button className={viewMode === 'pending' ? 'active' : ''} type="button" onClick={() => setViewMode('pending')}>
            待确认 {pending.length}
          </button>
          <button className={viewMode === 'groups' ? 'active' : ''} type="button" onClick={() => setViewMode('groups')}>
            分类浏览
          </button>
        </div>
        <div className="memory-search-wrap">
          <Search size={14} className="memory-search-icon" />
          <input className="search-input" type="search" placeholder="搜索记忆…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>

      {/* ── 待确认视图 ── */}
      {viewMode === 'pending' && (
        <>
          {canResolveMemory && pending.length > 0 && (
            <div className="memory-batch-bar">
              <span>{pending.length} 条待处理</span>
              <div className="memory-batch-actions">
                <button className="quiet-button" type="button" disabled={batchBusy} onClick={() => batchResolve(false)}>全部拒绝</button>
                <button className="quiet-button strong" type="button" disabled={batchBusy} onClick={() => batchResolve(true)}>全部确认</button>
              </div>
            </div>
          )}

          {memoryMessage && <div className="memory-state">{memoryMessage}</div>}

          <section className="surface memory-list-surface">
            <div className="stack">
              {pending.filter((item) => !cleanQuery || item.content.toLowerCase().includes(cleanQuery)).length ? (
                pending.filter((item) => !cleanQuery || item.content.toLowerCase().includes(cleanQuery)).map((item) => (
                  <MemoryCard key={`pending-${item.id}`} item={item} busy={busyId === item.id || batchBusy}
                    onResolve={canResolveMemory ? resolveMemory : undefined} compact />
                ))
              ) : (
                <div className="empty-inline">{cleanQuery ? '无匹配记忆' : '暂无待确认记忆，继续对话后会自动提炼'}</div>
              )}
            </div>
          </section>
        </>
      )}

      {/* ── 分类浏览视图 ── */}
      {viewMode === 'groups' && (
        <section className="memory-groups-view">
          {memoryMessage && <div className="memory-state">{memoryMessage}</div>}
          {groups ? (
            Object.entries(groups).map(([key, group]) => {
              const Icon = groupIcons[group.icon] || Database
              const filtered = cleanQuery
                ? group.memories.filter((m) => m.content.toLowerCase().includes(cleanQuery))
                : group.memories
              if (!filtered.length && cleanQuery) return null
              return (
                <div key={key} className="memory-group-block">
                  <div className="memory-group-head">
                    <Icon size={16} />
                    <h3>{group.label}</h3>
                    <span className="memory-group-count">{group.count} 条</span>
                    <em className="memory-group-question">{group.question}</em>
                  </div>
                  {filtered.length ? (
                    <div className="stack">
                      {filtered.map((item) => (
                        <MemoryCard key={`group-${item.id}`} item={{ ...item, status: 'confirmed', confidence: String(item.confidence || 0.8), source: '' }}
                          busy={false}
                          onResolve={undefined}
                          compact
                          editing={editingId === item.id}
                          editText={editingId === item.id ? editText : ''}
                          onEditStart={() => startEdit(item)}
                          onEditChange={setEditText}
                          onEditSave={() => handleSaveEdit(item.id)}
                          onEditCancel={() => setEditingId(null)}
                        />
                      ))}
                    </div>
                  ) : !cleanQuery ? (
                    <div className="empty-inline">此分类暂无记忆</div>
                  ) : null}
                </div>
              )
            })
          ) : (
            <div className="empty-inline">加载中…</div>
          )}
        </section>
      )}
    </div>
  )
}

function MemoryCard({
  item, busy = false, onResolve, compact = false, editing = false, editText = '',
  onEditStart, onEditChange, onEditSave, onEditCancel,
}: {
  item: MemoryItem; busy?: boolean; onResolve?: (id: number, accepted: boolean) => void; compact?: boolean
  editing?: boolean; editText?: string
  onEditStart?: () => void; onEditChange?: (v: string) => void; onEditSave?: () => void; onEditCancel?: () => void
}) {
  const typeLabel = memoryTypeLabel(item.type)
  if (editing) {
    return (
      <article className="memory-card editing">
        <div className="memory-card-edit-body">
          <span className={`memory-type-tag ${item.type}`}>{typeLabel}</span>
          <textarea className="memory-edit-textarea" value={editText}
            onChange={(e) => onEditChange?.(e.target.value)} rows={3} autoFocus />
          <div className="memory-edit-actions">
            <button className="quiet-button" type="button" onClick={onEditCancel}>取消</button>
            <button className="quiet-button strong" type="button" onClick={onEditSave} disabled={!editText.trim() || editText.trim().length < 10}>保存</button>
          </div>
        </div>
      </article>
    )
  }
  return (
    <article className={`memory-card ${compact ? 'compact' : ''}`}>
      <div className="memory-card-body">
        <div className="memory-card-top">
          <span className={`memory-type-tag ${item.type}`}>{typeLabel}</span>
          <span className="memory-card-meta">
            {item.source === 'soul-import' ? 'Soul 导入' : item.source === 'auto' ? '自动提取' : item.source || ''}
          </span>
          {item.status === 'confirmed' && onEditStart && (
            <button className="memory-edit-btn" type="button" onClick={onEditStart} title="编辑此记忆">
              <Edit3 size={12} />
            </button>
          )}
        </div>
        <p className="memory-card-content">{item.content}</p>
      </div>
      {item.status === 'pending' && onResolve && (
        <div className="memory-card-actions">
          <button className="quiet-button" type="button" disabled={busy} onClick={() => onResolve(item.id, false)}><X size={15} />拒绝</button>
          <button className="quiet-button strong" type="button" disabled={busy} onClick={() => onResolve(item.id, true)}><Check size={15} />确认</button>
        </div>
      )}
    </article>
  )
}

function memoryTypeLabel(mtype: string): string {
  const map: Record<string, string> = {
    identity: '身份', preference: '偏好', decision: '决策',
    insight: '洞察', project: '项目', todo: '待办',
    risk: '风险', context: '上下文', reflection: '复盘',
    fact: '事实', emotion_pattern: '情绪模式', value: '价值观',
    value_conflict: '价值冲突', life_theme: '人生主题',
    self_narrative: '自我叙事', project_mythology: '项目神话',
    relationship_pattern: '关系模式', creative_identity: '创作身份',
    growth_marker: '成长标记', reflection_anchor: '反思锚点',
  }
  return map[mtype] || mtype
}
