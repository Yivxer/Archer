import React from 'react'
import { BarChart3, BookOpenText, Compass, FileText, Heart, PenLine, RotateCcw, Sparkles, TrendingUp, Upload, Waves } from 'lucide-react'
import type { ArcherAdapter, ReviewPeriod, SoulFileName, SoulProfileSection } from '../types'
import { ConfirmDialog, MarkdownMessage } from '../components/common'
import { importSoul } from '../adapters/localArcher'

export function SoulPage({ data, onRefresh }: { data: ArcherAdapter; onRefresh: () => Promise<void> }) {
  const [file, setFile] = React.useState<SoulFileName>('SOUL.md')
  const [refreshing, setRefreshing] = React.useState(false)
  const [importing, setImporting] = React.useState(false)
  const [importMessage, setImportMessage] = React.useState('')
  const [confirmImportOpen, setConfirmImportOpen] = React.useState(false)
  const [reviewView, setReviewView] = React.useState<ReviewView | null>(null)
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

function soulSectionIcon(sectionId: string) {
  if (sectionId === 'core_values') return Heart
  if (sectionId === 'emotional_patterns') return Waves
  if (sectionId === 'life_themes') return Compass
  if (sectionId === 'creative_identity') return PenLine
  if (sectionId === 'growth_markers') return TrendingUp
  if (sectionId === 'current_life_stage') return Sparkles
  return BookOpenText
}
