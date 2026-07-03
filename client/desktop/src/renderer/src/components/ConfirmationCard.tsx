/**
 * L4.2 — <ConfirmationCard />
 *
 * 工具执行前的确认卡。展示工作意图（workIntent）、风险等级、回滚计划，
 * 让用户决定 approve / reject。是 Archer 最有辨识度的元素之一。
 *
 * 契约：docs/ui-primitives.md §1
 * 旧实现：pages/ChatPage.tsx WorkIntentBlock（行 2216，无按钮 + 无 risk badge）
 *
 * 与旧实现的差异：
 * - 新增左边色条（按 risk 等级）
 * - 新增 risk badge
 * - 内嵌 approve/reject 按钮（旧实现按钮在 approval-actions 区，与卡片分离）
 * - busy 状态禁用按钮 + 显示 ThinkingDots
 */

import React from 'react'
import { Check, ChevronDown, X } from 'lucide-react'
import type { RiskLevel, WorkIntent } from '../types'
import { ThinkingDots } from './common'

export type ConfirmationCardProps = {
  /** 工作意图（必填，来自 tool_event.draft.workIntent） */
  workIntent: WorkIntent
  /** 工具事件 id（用于回调追踪） */
  toolEventId: string
  /** 风险等级，决定卡片左边色条颜色（默认 'medium'） */
  risk?: RiskLevel
  /** 工具显示名（如 "Obsidian 写入" / "Shell 执行"），来自 tool_event.draft.displayName */
  toolDisplayName?: string
  /** 操作目标预览（path / url / command 任一） */
  targetPreview?: {
    path?: string
    url?: string
    command?: string
  }
  /** 是否禁用按钮（异步 approve/reject 进行中） */
  busy?: boolean
  /** 用户批准 */
  onApprove: (toolEventId: string) => void
  /** 用户拒绝 */
  onReject: (toolEventId: string) => void
  /** 可选：展开/收起 diff 预览（obsidian_write 专属） */
  onShowDiff?: () => void
}

const RISK_LABEL: Record<RiskLevel, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  critical: '极高风险',
}

export function ConfirmationCard({
  workIntent,
  toolEventId,
  risk = 'medium',
  toolDisplayName,
  targetPreview,
  busy = false,
  onApprove,
  onReject,
  onShowDiff,
}: ConfirmationCardProps): React.ReactElement {
  const targets = Array.isArray(workIntent.targets) ? workIntent.targets : []
  const steps = Array.isArray(workIntent.steps) ? workIntent.steps : []
  const [expanded, setExpanded] = React.useState(true)

  const handleApprove = () => {
    if (busy) return
    onApprove(toolEventId)
  }
  const handleReject = () => {
    if (busy) return
    onReject(toolEventId)
  }

  return (
    <article
      className={`confirmation-card risk-${risk}${busy ? ' busy' : ''}`}
      data-tool-event-id={toolEventId}
      aria-busy={busy}
    >
      <span className="confirmation-card-stripe" aria-hidden="true" />

      <header className="confirmation-card-header">
        <div className="confirmation-card-title">
          {toolDisplayName && <strong className="confirmation-card-name">{toolDisplayName}</strong>}
          <span className={`confirmation-card-risk-badge risk-${risk}`}>{RISK_LABEL[risk]}</span>
        </div>
        {steps.length > 0 && (
          <button
            type="button"
            className="confirmation-card-expand"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            title={expanded ? '收起步骤' : '展开步骤'}
          >
            <ChevronDown size={13} />
          </button>
        )}
      </header>

      <div className="confirmation-card-body">
        <p className="confirmation-card-workflow">
          {[workIntent.workflowName, workIntent.action].filter(Boolean).join(' · ') || '工作确认'}
        </p>

        {targets.length > 0 && (
          <ul className="confirmation-card-targets">
            {targets.map((target, index) => (
              <li key={`${target.label || 'target'}-${index}`}>
                {[target.label, target.path || target.url].filter(Boolean).join('：')}
              </li>
            ))}
          </ul>
        )}

        {targetPreview && (targetPreview.path || targetPreview.url || targetPreview.command) && (
          <div className="confirmation-card-target-preview">
            {targetPreview.path && <code>path: {targetPreview.path}</code>}
            {targetPreview.url && <code>url: {targetPreview.url}</code>}
            {targetPreview.command && <code>$ {targetPreview.command}</code>}
          </div>
        )}

        {expanded && steps.length > 0 && (
          <ol className="confirmation-card-steps">
            {steps.map((step, index) => (
              <li key={`step-${index}`}>{step}</li>
            ))}
          </ol>
        )}

        {workIntent.verifyPlan && (
          <p className="confirmation-card-verify">
            <span className="confirmation-card-field-label">验证：</span>
            {workIntent.verifyPlan}
          </p>
        )}

        {workIntent.rollbackPlan && (
          <p className="confirmation-card-rollback">
            <span className="confirmation-card-field-label">回滚计划：</span>
            {workIntent.rollbackPlan}
          </p>
        )}

        {onShowDiff && (
          <button
            type="button"
            className="confirmation-card-diff-toggle"
            onClick={onShowDiff}
            disabled={busy}
          >
            查看 diff 预览
          </button>
        )}
      </div>

      <footer className="confirmation-card-actions">
        {busy ? (
          <ThinkingDots />
        ) : (
          <>
            <button
              type="button"
              className="button-danger confirmation-card-reject"
              onClick={handleReject}
              disabled={busy}
              aria-label="拒绝"
              title="放弃"
            >
              <X size={13} />
              <span>拒绝</span>
            </button>
            <button
              type="button"
              className="button-primary confirmation-card-approve"
              onClick={handleApprove}
              disabled={busy}
              aria-label="批准"
              title="批准执行"
            >
              <Check size={13} />
              <span>批准</span>
            </button>
          </>
        )}
      </footer>
    </article>
  )
}
