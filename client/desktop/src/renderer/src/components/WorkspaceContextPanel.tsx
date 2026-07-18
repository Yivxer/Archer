import React from 'react'
import { useShadowFeedback } from '../lib/useShadowFeedback'
import type { BackgroundJob, ExpertStarter, MemoryContextMode, ObsidianContextMode, Route } from '../types'
import { ShadowCandidateCard } from './ShadowCandidateCard'

export type WorkspaceJobSummary = {
  id: string
  title: string
  status: BackgroundJob['status']
  kind: string
  preview: string
  createdAt: string
}

export function WorkspaceContextPanel({
  activeExpertTitle,
  isHistorySession,
  modelButtonLabel,
  memoryMode,
  obsidianMode,
  sidebarJobs,
  workspaceJobsState,
  activeSidebarJobCount,
  homeStarters,
  onUseStarter,
  onNavigate,
  canControlInitiative,
  onRefresh,
  onClose,
}: {
  activeExpertTitle: string
  isHistorySession: boolean
  modelButtonLabel: string
  memoryMode: MemoryContextMode
  obsidianMode: ObsidianContextMode
  sidebarJobs: WorkspaceJobSummary[]
  workspaceJobsState: 'idle' | 'loading' | 'error'
  activeSidebarJobCount: number
  homeStarters: ExpertStarter[]
  onUseStarter: (starter: ExpertStarter) => void
  onNavigate?: (route: Route) => void
  canControlInitiative: boolean
  onRefresh?: () => Promise<void>
  onClose?: () => void
}) {
  const shadowFeedback = useShadowFeedback({
    canControl: canControlInitiative,
    claimDailyCandidate: true,
    surface: 'chat_workspace',
    onRefresh,
  })
  const candidate = shadowFeedback.reviewCandidate?.reason === 'candidate'
    ? shadowFeedback.reviewCandidate.item
    : null
  return (
    <aside className="workspace-context-panel" aria-label="工作台上下文">
      <div className="workspace-context-head">
        <span>上下文</span>
        {onClose && <button type="button" onClick={onClose}>收起</button>}
        <strong>{activeExpertTitle}</strong>
        <em>{isHistorySession ? '历史会话续写' : '当前工作台'}</em>
      </div>
      <div className="workspace-context-grid">
        <div>
          <span>模型</span>
          <strong>{modelButtonLabel}</strong>
        </div>
        <div>
          <span>记忆</span>
          <strong>{memoryMode}</strong>
        </div>
        <div>
          <span>笔记</span>
          <strong>{obsidianMode}</strong>
        </div>
        <div>
          <span>任务</span>
          <strong>{sidebarJobs.length}</strong>
        </div>
      </div>
      {candidate && (
        <ShadowCandidateCard
          item={candidate}
          busy={shadowFeedback.busy}
          notice={shadowFeedback.notice}
          onAcknowledge={() => void shadowFeedback.sendFeedback(candidate.id, 'acknowledged')}
          onTooFrequent={() => void shadowFeedback.sendFeedback(candidate.id, 'too_frequent')}
          onMute={() => void shadowFeedback.togglePresence()}
          onViewAll={() => onNavigate?.('Today')}
        />
      )}
      <div className="workspace-jobs-panel">
        <div className="workspace-panel-head">
          <span>后台任务</span>
          <button type="button" onClick={() => onNavigate?.('Tasks')}>查看全部</button>
        </div>
        {sidebarJobs.length ? (
          <div className="workspace-job-list">
            {sidebarJobs.map((job) => (
              <button
                className={`workspace-job-card job-${job.status}`}
                key={job.id}
                type="button"
                onClick={() => onNavigate?.('Tasks')}
              >
                <strong>{job.title || job.id}</strong>
                <span>{workspaceJobStatusLabel(job.status)} · {job.kind}</span>
                {job.preview && <em>{job.preview}</em>}
              </button>
            ))}
          </div>
        ) : (
          <div className="workspace-empty-note">
            {workspaceJobsState === 'loading' ? '同步后台任务…' : workspaceJobsState === 'error' ? '任务同步失败，可打开任务页刷新。' : '暂无后台任务'}
          </div>
        )}
        {activeSidebarJobCount > 0 && <small>{activeSidebarJobCount} 个任务仍在进行或等待确认</small>}
      </div>
      <div className="workspace-shortcuts">
        <span>快捷开始</span>
        {homeStarters.map((starter) => (
          <button key={starter.label} type="button" onClick={() => onUseStarter(starter)}>
            {starter.label}
          </button>
        ))}
      </div>
      <div className="workspace-links">
        <button type="button" onClick={() => onNavigate?.('Tasks')}>后台任务</button>
        <button type="button" onClick={() => onNavigate?.('Memory')}>记忆审阅</button>
        <button type="button" onClick={() => onNavigate?.('Settings')}>工作台设置</button>
      </div>
    </aside>
  )
}

function workspaceJobStatusLabel(status: BackgroundJob['status']): string {
  if (status === 'queued') return '等待中'
  if (status === 'running') return '执行中'
  if (status === 'waiting_approval') return '等待确认'
  if (status === 'complete') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'cancelled') return '已取消'
  return status
}
