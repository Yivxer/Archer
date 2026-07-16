/**
 * L4.4 — <TracePanel />
 *
 * 诊断信息展开面板。展示 traceId、runtime context、failure hint、最近事件流，
 * 帮助用户定位「为什么这一轮失败」。
 *
 * 契约：docs/ui-primitives.md §3
 * 旧实现：pages/ChatPage.tsx TraceDiagnosticsPanel（行 1857）+ describeTraceEvent（行 1896）
 *
 * 与旧实现的差异：
 * - 抽成独立组件，不依赖 ChatPage 内部函数
 * - 新增 defaultExpandFailure prop（默认 true，失败时优先看 failure hint）
 * - 新增 onRetry prop（recoverable=true 时显示「重试」按钮）
 * - 复用 buildTraceDiagnostics / TraceDiagnostics 类型（不重写）
 */

import React from 'react'
import { ChevronDown, RotateCw, X } from 'lucide-react'
import type { AgentEvent, TraceDiagnostics } from '../../../agent'

export type TracePanelProps = {
  /** 诊断数据（必填，来自 buildTraceDiagnostics） */
  diagnostics: TraceDiagnostics
  /** 是否默认展开 failureHint 区（默认 true，失败时优先看） */
  defaultExpandFailure?: boolean
  /** 关闭回调 */
  onClose: () => void
  /** 可选：重试回调（失败时显示「重试」按钮） */
  onRetry?: () => void
}

function shortTraceText(value: string, maxLength = 96): string {
  const compact = value.replace(/\s+/g, ' ').trim()
  if (compact.length <= maxLength) return compact
  return `${compact.slice(0, maxLength - 1)}…`
}

function describeTraceEvent(event: AgentEvent): string {
  if (event.type === 'runtime.context') return `${event.task} / ${event.phase}`
  if (event.type === 'failure.hint') return `${event.keyword} / ${event.stage}`
  if (event.type === 'tool.request') {
    return `${event.toolName} / ${event.status} / ${shortTraceText(event.summary || event.detail || '无摘要')}`
  }
  if (event.type === 'tool.result') {
    return `${event.toolName} / ${event.status} / ${shortTraceText(event.message || event.output || '无摘要')}`
  }
  if (event.type === 'approval.result') {
    return `${event.decision} / ${event.executed ? 'executed' : 'skipped'} / ${shortTraceText(event.message || event.output || '无摘要')}`
  }
  if (event.type === 'job.event') return `${event.title} / ${event.status}${event.stale ? ' / stale' : ''}`
  if (event.type === 'status.event') return `${event.intentType} / ${event.intentLabel}`
  return event.type
}

const KEYWORD_TONE: Record<string, string> = {
  provider_connection_failed: 'trace-keyword-danger',
  command_timeout: 'trace-keyword-warning',
  write_permission: 'trace-keyword-warning',
  dependency_missing: 'trace-keyword-warning',
  syntax_mismatch: 'trace-keyword-warning',
  runtime_failure: 'trace-keyword-danger',
  model_empty_response: 'trace-keyword-info',
  tool_executed_no_summary: 'trace-keyword-info',
}

export function TracePanel({
  diagnostics,
  defaultExpandFailure = true,
  onClose,
  onRetry,
}: TracePanelProps): React.ReactElement {
  const context = diagnostics.runtimeContext
  const modelContext = diagnostics.modelContext
  const failure = diagnostics.failureHint
  const [failureExpanded, setFailureExpanded] = React.useState(defaultExpandFailure)
  const canRetry = Boolean(failure?.recoverable && onRetry)

  const keywordTone = failure ? (KEYWORD_TONE[failure.keyword] || 'trace-keyword-danger') : ''

  return (
    <aside className="trace-panel" aria-label="诊断面板" data-trace-id={diagnostics.traceId}>
      <header className="trace-panel-header">
        <div className="trace-panel-title">
          <strong>诊断</strong>
          <span className="trace-panel-trace-id">{diagnostics.traceId || '暂无 traceId'}</span>
        </div>
        <button
          type="button"
          className="trace-panel-close"
          onClick={onClose}
          title="关闭"
          aria-label="关闭"
        >
          <X size={14} />
        </button>
      </header>

      {diagnostics.empty ? (
        <p className="trace-empty">暂无诊断事件</p>
      ) : (
        <>
          <dl className="trace-kv">
            <div>
              <dt>任务</dt>
              <dd>{context?.task || '未知'}</dd>
            </div>
            <div>
              <dt>阶段</dt>
              <dd>{context?.phase || failure?.stage || '未知'}</dd>
            </div>
            <div>
              <dt>下一步</dt>
              <dd>{context?.expectedNext || '未记录'}</dd>
            </div>
            <div>
              <dt>故障</dt>
              <dd>
                {failure ? `${failure.keyword} · ${failure.recoverable ? '可恢复' : '不可恢复'}` : '无'}
              </dd>
            </div>
            <div>
              <dt>Provider</dt>
              <dd>{modelContext?.provider || '未记录'}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{modelContext?.model || '未记录'}</dd>
            </div>
            <div>
              <dt>Endpoint</dt>
              <dd>{modelContext?.baseUrlSummary || '未记录'}</dd>
            </div>
          </dl>

          {failure && (
            <section className="trace-failure-section">
              <button
                type="button"
                className="trace-failure-toggle"
                onClick={() => setFailureExpanded((value) => !value)}
                aria-expanded={failureExpanded}
              >
                <ChevronDown size={13} />
                <span className={`trace-keyword-badge ${keywordTone}`}>{failure.keyword}</span>
                <span className="trace-failure-stage">{failure.stage}</span>
              </button>
              {failureExpanded && (
                <div className="trace-failure-detail">
                  <p className="trace-failure-text">{failure.detail}</p>
                  {canRetry && (
                    <button
                      type="button"
                      className="trace-retry-button"
                      onClick={onRetry}
                      aria-label="重试"
                      title="重试"
                    >
                      <RotateCw size={13} />
                      <span>重试</span>
                    </button>
                  )}
                </div>
              )}
            </section>
          )}

          <div className="trace-events">
            {diagnostics.recentEvents.map((event) => (
              <div key={event.id} className="trace-event-row">
                <span className="trace-event-type">{event.type}</span>
                <em className="trace-event-summary">{describeTraceEvent(event)}</em>
              </div>
            ))}
          </div>
        </>
      )}
    </aside>
  )
}
