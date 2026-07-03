/**
 * L4.3 — <WorkReceipt />
 *
 * 工具执行后的工作回执。展示「做了什么 / 来源 / 目标 / 验证方式 / 回滚方式」，
 * 是 Archer 区别于普通 ChatGPT 客户端的标志。
 *
 * 契约：docs/ui-primitives.md §2
 * 旧实现：pages/ChatPage.tsx WorkReceiptBlock（行 2235，无 trace 按钮 + 无左边色条 + 纯文本）
 *
 * 与旧实现的差异：
 * - 新增左边色条（--cyan success 色）
 * - 字段网格改为 2 列布局
 * - 新增 trace 跳转按钮（traceId 存在时显示）
 * - 卡片圆角 8px（比 ConfirmationCard 紧凑）
 */

import React from 'react'
import { Activity } from 'lucide-react'
import type { WorkReceipt as WorkReceiptType } from '../types'

export type WorkReceiptProps = {
  /** 工作回执数据（必填，来自 tool_event.receipt） */
  receipt: WorkReceiptType
  /** 关联的 traceId（可选，用于跳转 TracePanel） */
  traceId?: string
  /** 是否显示「查看 trace」按钮（默认 true） */
  showTraceAction?: boolean
  /** 点击「查看 trace」回调 */
  onViewTrace?: (traceId: string) => void
}

export function WorkReceipt({
  receipt,
  traceId,
  showTraceAction = true,
  onViewTrace,
}: WorkReceiptProps): React.ReactElement {
  const hasTraceButton = Boolean(showTraceAction && traceId && onViewTrace)
  const handleViewTrace = () => {
    if (traceId && onViewTrace) {
      onViewTrace(traceId)
    }
  }

  return (
    <article
      className="work-receipt"
      aria-label="工作回执"
      data-trace-id={traceId || undefined}
    >
      <span className="work-receipt-stripe" aria-hidden="true" />

      <header className="work-receipt-header">
        <strong className="work-receipt-done">{receipt.done}</strong>
        {hasTraceButton && (
          <button
            type="button"
            className="work-receipt-trace-button"
            onClick={handleViewTrace}
            aria-label="查看 trace"
            title="查看 trace 诊断"
          >
            <Activity size={13} />
          </button>
        )}
      </header>

      <dl className="work-receipt-grid">
        {receipt.source && (
          <div className="work-receipt-field">
            <dt>来源</dt>
            <dd>{receipt.source}</dd>
          </div>
        )}
        {receipt.target && (
          <div className="work-receipt-field">
            <dt>目标</dt>
            <dd>{receipt.target}</dd>
          </div>
        )}
        {receipt.verification && (
          <div className="work-receipt-field">
            <dt>验证</dt>
            <dd>{receipt.verification}</dd>
          </div>
        )}
        {receipt.rollback && (
          <div className="work-receipt-field work-receipt-rollback">
            <dt>回滚</dt>
            <dd>{receipt.rollback}</dd>
          </div>
        )}
      </dl>
    </article>
  )
}
