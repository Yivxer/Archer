import React from 'react'
import { Check, ChevronDown, FileText, Github, Loader2, RotateCcw, Send, Terminal, X } from 'lucide-react'
import { WorkReceipt as WorkReceiptComponent } from '../../components/WorkReceipt'
import type { JobEvent, PlanEvent, PlanStep } from '../../../../agent'
import type { ToolEvent } from '../../types'
import { statusLabel, toolCompactText, toolKind, ToolEventBody, jobStatusLabel } from './toolEventHelpers'

export function JobEventCard({
  job,
  onCancel,
  onRetry,
  onApprove
}: {
  job: JobEvent
  onCancel: () => void
  onRetry: () => void
  onApprove?: (decision: 'approved' | 'denied') => void
}) {
  const isActive = job.status === 'queued' || job.status === 'running' || job.status === 'waiting_approval'
  const canRetry = job.status === 'failed' || job.status === 'cancelled'
  const needsApproval = job.status === 'waiting_approval'

  return (
    <article className={`job-event-card ${job.status}`}>
      <div className="job-event-summary">
        {isActive && !needsApproval ? <Loader2 size={14} /> : needsApproval ? <Loader2 size={14} /> : <Check size={14} />}
        <span>{job.title || '后台任务'}</span>
        <em>{jobStatusLabel(job.status, job.stale)}</em>
        {isActive && !needsApproval && (
          <button type="button" onClick={onCancel} title="取消后台任务" aria-label="取消后台任务">
            <X size={13} />
          </button>
        )}
        {needsApproval && onApprove && (
          <>
            <button type="button" className="button-primary-compact" onClick={() => onApprove('approved')} title="批准并执行" aria-label="批准">
              <Check size={13} />
            </button>
            <button type="button" className="button-danger-compact" onClick={() => onApprove('denied')} title="拒绝" aria-label="拒绝">
              <X size={13} />
            </button>
          </>
        )}
        {canRetry && (
          <button type="button" onClick={onRetry} title="重试后台任务" aria-label="重试后台任务">
            <RotateCcw size={13} />
          </button>
        )}
      </div>
      {job.detail && (
        <div className="job-event-detail">
          {job.detail.length > 180 ? `${job.detail.slice(0, 180).trim()}...` : job.detail}
        </div>
      )}
      {needsApproval && job.detail && (
        <div className="approval-actions compact">
          <span className="approval-hint">此任务需要您确认后才能继续</span>
        </div>
      )}
    </article>
  )
}

export function PlanEventCard({
  plan,
  busy = false,
  onAccept,
  onSplit,
  onDismiss,
}: {
  plan: PlanEvent
  busy?: boolean
  onAccept?: () => void
  onSplit?: () => void
  onDismiss?: () => void
}) {
  const isProposed = plan.status === 'proposed'
  return (
    <article className={`plan-event-card ${plan.status}`}>
      <div className="plan-event-summary">
        <FileText size={14} />
        <span>{plan.title || '任务计划'}</span>
        <em>{plan.status === 'proposed' ? '待确认' : plan.status === 'accepted' ? '已确认' : '已忽略'}</em>
      </div>
      {plan.detail && <div className="plan-event-detail">{plan.detail}</div>}
      <ol className="plan-event-steps">
        {plan.steps.map((step: PlanStep) => (
          <li key={step.id}>
            <span>{step.action}</span>
            <em>{step.tool}{step.requiresApproval ? ' · 需确认' : ''}</em>
          </li>
        ))}
      </ol>
      {isProposed && onAccept && onDismiss && (
        <div className="plan-event-actions">
          <button className="quiet-button" type="button" disabled={busy} onClick={onDismiss}>
            忽略
          </button>
          {onSplit && (
            <button className="quiet-button" type="button" disabled={busy} onClick={onSplit}>
              拆分子任务
            </button>
          )}
          <button className="quiet-button strong" type="button" disabled={busy} onClick={onAccept}>
            {onSplit ? '整包执行' : '按计划执行'}
          </button>
        </div>
      )}
    </article>
  )
}

export function ToolEventCard({
  event,
  decision,
  onDecide,
  defaultExpanded = false
}: {
  event: ToolEvent
  decision?: 'approved' | 'denied'
  onDecide: (decision: 'approved' | 'denied') => void
  defaultExpanded?: boolean
}) {
  const needsApproval = Boolean(event.requiresApproval && !decision)
  const kind = toolKind(event)
  let Icon = FileText
  if (kind === 'shell') Icon = Terminal
  else if (kind === 'github') Icon = Github
  else if (kind === 'publish') Icon = Send
  const [expanded, setExpanded] = React.useState(defaultExpanded || needsApproval)

  return (
    <article className={`tool-event-card ${event.status} ${kind} risk-${event.risk} ${expanded ? 'expanded' : 'collapsed'}`}>
      <button className="tool-event-summary" type="button" onClick={() => setExpanded((value) => !value)}>
        <Icon size={14} />
        <span>{toolCompactText(event, kind)}</span>
        <em>{statusLabel(event.status, needsApproval)}</em>
        <ChevronDown size={13} />
      </button>

      {needsApproval && !event.draft?.workIntent && (
        <div className="approval-actions compact">
          <button className="button-primary" type="button" onClick={() => onDecide('approved')} title={(() => { if (kind === 'shell' || kind === 'github') return '执行'; if (kind === 'publish') return '发布'; return '写入'; })()}>
            <Check size={13} />
          </button>
          <button className="button-danger" type="button" onClick={() => onDecide('denied')} title="放弃">
            <X size={13} />
          </button>
        </div>
      )}

      {expanded && (
        <div className="tool-event-detail">
          <p>{event.summary}</p>
          {event.receipt ? (
            <WorkReceiptComponent receipt={event.receipt} />
          ) : null}
          <ToolEventBody
            event={event}
            kind={kind}
            needsApproval={needsApproval}
            onDecide={onDecide}
          />
        </div>
      )}
    </article>
  )
}
