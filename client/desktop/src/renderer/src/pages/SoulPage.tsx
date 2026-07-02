import React from 'react'
import { BarChart3, BookOpenText, CheckCircle2, Clock3, Compass, FileText, Heart, PenLine, RotateCcw, Sparkles, TrendingUp, Upload, Waves, XCircle } from 'lucide-react'
import type { ArcherAdapter, HypothesisItem, ReviewPeriod, SoulFileName, SoulProfileSection, VaultReflection } from '../types'
import { ConfirmDialog, MarkdownMessage } from '../components/common'
import { importSoul, fetchVaultReflections } from '../adapters/localArcher'

export function SoulPage({ data, onRefresh }: { data: ArcherAdapter; onRefresh: () => Promise<void> }) {
  const [file, setFile] = React.useState<SoulFileName>('SOUL.md')
  const [refreshing, setRefreshing] = React.useState(false)
  const [importing, setImporting] = React.useState(false)
  const [importMessage, setImportMessage] = React.useState('')
  const [confirmImportOpen, setConfirmImportOpen] = React.useState(false)
  const [reviewView, setReviewView] = React.useState<ReviewView | null>(null)
  const sortedHypotheses = React.useMemo(() => {
    return [...data.hypotheses].sort((a, b) => {
      if (isDueHypothesis(a) !== isDueHypothesis(b)) return isDueHypothesis(a) ? -1 : 1
      return dateMs(b.updatedAt || b.createdAt) - dateMs(a.updatedAt || a.createdAt)
    })
  }, [data.hypotheses])
  const activeReviewText = reviewView
    ? reviewView === 'journal'
      ? data.journalReview.markdown
      : data.periodReviews[reviewView].markdown
    : ''

  async function handleRefresh() {
    setRefreshing(true)
    try {
      await onRefresh()
    } finally {
      setRefreshing(false)
    }
  }

  async function startImportSoul() {
    setConfirmImportOpen(false)
    setImporting(true)
    setImportMessage('')
    try {
      const input = document.createElement('input')
      input.type = 'file'
      input.accept = '.json'
      input.onchange = async () => {
        const file = input.files?.[0]
        if (!file) { setImporting(false); return }
        try {
          const text = await file.text()
          const soulData = JSON.parse(text)
          if (!soulData.soulAnswers && !soulData.initialAnswers && !soulData.deepAnswers) {
            setImportMessage('文件格式不正确：缺少 soulAnswers/initialAnswers/deepAnswers')
            return
          }
          const result = await importSoul(soulData)
          if (result.ok) {
            setImportMessage(`已导入 ${result.imported} 条待确认记忆`)
            await onRefresh()
          } else {
            setImportMessage('导入失败')
          }
        } catch (err) {
          setImportMessage(err instanceof Error ? err.message : '文件解析失败')
        } finally {
          setImporting(false)
        }
      }
      input.click()
    } catch (err) {
      setImportMessage(err instanceof Error ? err.message : '导入失败')
      setImporting(false)
    }
  }

  return (
    <div className="soul-page">
      <ConfirmDialog
        open={confirmImportOpen}
        title="导入 Soul 数据？"
        message="导入后不会直接写死人格，而是生成待确认记忆。你可以在记忆审阅里逐条确认或放弃。"
        confirmLabel="选择文件"
        onConfirm={startImportSoul}
        onCancel={() => setConfirmImportOpen(false)}
      />
      <div className="soul-toolbar">
        <div className="soul-title-block">
          <span>SOUL</span>
          <h1>灵魂档案</h1>
        </div>
        <div className="soul-file-tabs">
          {(Object.keys(data.soulFiles) as SoulFileName[]).map((name) => (
            <button
              key={name}
              className={`tab ${file === name ? 'active' : ''}`}
              type="button"
              onClick={() => { setFile(name); setReviewView(null) }}
            >
              <FileText size={15} />
              {name}
            </button>
          ))}
        </div>
        <div className="soul-review-tabs" aria-label="复盘周期">
          {reviewTabs.map((tab) => (
            <button
              key={tab.view}
              className={`tab ${reviewView === tab.view ? 'active' : ''}`}
              type="button"
              onClick={() => setReviewView(tab.view)}
            >
              <BarChart3 size={15} />
              {tab.label}
            </button>
          ))}
        </div>
        <button
          className="quiet-button"
          type="button"
          disabled={refreshing}
          onClick={handleRefresh}
          title="刷新 Soul 文件"
        >
          <RotateCcw size={14} />
          {refreshing ? '刷新中' : '刷新'}
        </button>
        <button
          className="quiet-button"
          type="button"
          disabled={importing || data.status.adapter !== 'local'}
          onClick={() => setConfirmImportOpen(true)}
          title="从 JSON 文件导入 Soul 数据"
        >
          <Upload size={14} />
          {importing ? '导入中' : '导入 Soul'}
        </button>
      </div>
      {importMessage && <div className="memory-state">{importMessage}</div>}
      <div className="soul-layout">
        <section className="soul-profile-overview">
          {data.soulProfile.empty ? (
            <div className="empty-inline">暂无结构化 Soul Profile</div>
          ) : (
            data.soulProfile.sections.map((section) => (
              <SoulProfileBlock section={section} key={section.id} />
            ))
          )}
          <VaultReflectionsPanel adapterStatus={data.status.adapter} />
          <HypothesisPanel hypotheses={sortedHypotheses} />
        </section>
        <div className="markdown-preview soul-markdown-reader">
          {activeReviewText ? (
            <MarkdownMessage text={activeReviewText} />
          ) : data.soulFiles[file]?.trim() ? (
            <MarkdownMessage text={data.soulFiles[file]} />
          ) : (
            <div className="empty-inline">此文件未配置路径或为空。</div>
          )}
        </div>
      </div>
    </div>
  )
}

type ReviewView = ReviewPeriod | 'journal'

const reviewTabs: { view: ReviewView; label: string }[] = [
  { view: 'weekly', label: '周复盘' },
  { view: 'monthly', label: '月复盘' },
  { view: 'life_stage', label: '阶段复盘' },
  { view: 'journal', label: '日记回顾' },
]

function SoulProfileBlock({ section }: { section: SoulProfileSection }) {
  const Icon = soulSectionIcon(section.id)
  return (
    <article className={`soul-profile-block ${section.id}`}>
      <header>
        <Icon size={15} />
        <span>{section.label}</span>
      </header>
      {section.items.length ? (
        <ul>
          {section.items.map((item, index) => (
            <li key={`${section.id}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p>尚未记录</p>
      )}
    </article>
  )
}

function VaultReflectionsPanel({ adapterStatus }: { adapterStatus: string }) {
  const [reflections, setReflections] = React.useState<VaultReflection[]>([])
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')

  const load = React.useCallback(async () => {
    if (adapterStatus !== 'local') return
    setLoading(true)
    setError('')
    try {
      const result = await fetchVaultReflections(10)
      setReflections(result.reflections || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [adapterStatus])

  React.useEffect(() => {
    void load()
  }, [load])

  if (adapterStatus !== 'local') return null

  return (
    <section className="soul-vault-reflections-panel" aria-labelledby="vault-reflections-title">
      <header className="soul-vault-reflections-head">
        <div>
          <span>Vault Bridge</span>
          <h2 id="vault-reflections-title">近期笔记结晶</h2>
        </div>
        <button className="quiet-button" type="button" disabled={loading} onClick={load} title="刷新">
          <RotateCcw size={12} />
          {loading ? '加载中' : '刷新'}
        </button>
      </header>
      {error && <p className="vault-reflections-error">{error}</p>}
      {reflections.length === 0 ? (
        <p className="vault-reflections-empty">
          {loading ? '加载中…' : '暂无结晶记录。对 Obsidian 笔记触发后会出现在这里。'}
        </p>
      ) : (
        <div className="vault-reflections-list">
          {reflections.slice(0, 6).map((r) => (
            <article key={r.id} className="vault-reflection-card">
              <header>
                <BookOpenText size={13} />
                <span className="vault-reflection-title">{r.note_title || r.note_path}</span>
                {r.confidence >= 0.7 && <em className="vault-confidence">★{(r.confidence * 100).toFixed(0)}%</em>}
              </header>
              <p className="vault-reflection-summary">{r.summary}</p>
              <div className="vault-reflection-meta">
                <span>{r.insights_count} 条洞察</span>
                {r.soul_proposal_id && <span className="vault-soul-badge">Soul 候选</span>}
                <span className="vault-reflection-time">{formatReflectionTime(r.reflected_at)}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

function formatReflectionTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 10)
  const now = Date.now()
  const diff = now - date.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function HypothesisPanel({ hypotheses }: { hypotheses: HypothesisItem[] }) {
  const active = hypotheses.filter((item) => item.status === 'active')
  const due = active.filter(isDueHypothesis)
  const verified = hypotheses.filter((item) => item.status === 'verified')
  const rejected = hypotheses.filter((item) => item.status === 'rejected')

  return (
    <section className="soul-hypothesis-panel" aria-labelledby="hypothesis-panel-title">
      <header className="soul-hypothesis-head">
        <div>
          <span>Hypotheses</span>
          <h2 id="hypothesis-panel-title">假设验证</h2>
        </div>
        <strong>{hypotheses.length}</strong>
      </header>
      <div className="hypothesis-stats" aria-label="假设状态统计">
        <span>{active.length} active</span>
        <span>{due.length} due</span>
        <span>{verified.length} verified</span>
        <span>{rejected.length} rejected</span>
      </div>
      {hypotheses.length ? (
        <div className="hypothesis-list">
          {hypotheses.slice(0, 8).map((item) => (
            <HypothesisCard hypothesis={item} key={item.id} />
          ))}
        </div>
      ) : (
        <p className="hypothesis-empty">暂无 hypothesis。手动录入或日记中的“假设：”会出现在这里。</p>
      )}
    </section>
  )
}

function HypothesisCard({ hypothesis }: { hypothesis: HypothesisItem }) {
  const due = isDueHypothesis(hypothesis)
  const StatusIcon = hypothesis.status === 'verified'
    ? CheckCircle2
    : hypothesis.status === 'rejected'
      ? XCircle
      : Clock3
  return (
    <article className={`hypothesis-card ${hypothesis.status} ${due ? 'due' : ''}`}>
      <header>
        <StatusIcon size={14} />
        <span>{hypothesisStatusText(hypothesis, due)}</span>
        {hypothesis.confidence ? <em>{Math.round(hypothesis.confidence * 100)}%</em> : null}
      </header>
      <strong>{hypothesis.title || `Hypothesis #${hypothesis.id}`}</strong>
      <p>{hypothesis.statement}</p>
      <div className="hypothesis-meta">
        <span>{sourceText(hypothesis.source)}</span>
        {hypothesis.validateAfter && <span>验证：{formatDate(hypothesis.validateAfter)}</span>}
      </div>
      {hypothesis.evidence.length > 0 && (
        <div className="hypothesis-evidence">
          <small>证据</small>
          <p>{hypothesis.evidence[0].content}</p>
        </div>
      )}
      {hypothesis.verificationNote && (
        <div className="hypothesis-evidence">
          <small>验证报告</small>
          <p>{hypothesis.verificationNote}</p>
        </div>
      )}
    </article>
  )
}

function isDueHypothesis(hypothesis: HypothesisItem): boolean {
  if (hypothesis.status !== 'active' || !hypothesis.validateAfter) return false
  return dateMs(hypothesis.validateAfter) <= Date.now()
}

function dateMs(value: string | undefined): number {
  if (!value) return 0
  const ms = new Date(value).getTime()
  return Number.isFinite(ms) ? ms : 0
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 10)
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function hypothesisStatusText(hypothesis: HypothesisItem, due: boolean): string {
  if (hypothesis.status === 'verified') return '已验证'
  if (hypothesis.status === 'rejected') return '已驳回'
  if (hypothesis.status === 'dismissed') return '已静默'
  return due ? '待验证' : '观察中'
}

function sourceText(source: string): string {
  if (source === 'obsidian_journal') return '日记'
  if (source === 'manual') return '手动'
  return source || '未知来源'
}

function soulSectionIcon(sectionId: string) {
  if (sectionId === 'core_values') return Heart
  if (sectionId === 'emotional_patterns') return Waves
  if (sectionId === 'life_themes') return Compass
  if (sectionId === 'creative_identity') return PenLine
  if (sectionId === 'growth_markers') return TrendingUp
  if (sectionId === 'current_life_stage') return Sparkles
  return BookOpenText
}
