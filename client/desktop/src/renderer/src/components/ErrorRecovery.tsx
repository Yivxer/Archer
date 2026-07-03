/**
 * L4.5 — <ErrorRecovery />
 *
 * 错误提示 + 恢复动作。与 L2 chatEventDispatcher 的失败类型联动，
 * 按 failureType 显示默认文案 + 色条 + 可选重试/诊断入口。
 *
 * 契约：docs/ui-primitives.md §4
 * 失败类型来源：lib/chatEventDispatcher.ts FailureType（**复用，不重定义**）
 *
 * 与旧实现差异：
 * - 旧 chat-error div 由 ChatPage 内联渲染，文案散落各处
 * - 新 ErrorRecovery 统一文案矩阵 + 色条分类 + recoverable 推导
 * - 不自己推导 failureType（由 dispatcher 或 failureHintEvent 提供）
 */

import React from 'react'
import { Activity, RotateCw } from 'lucide-react'
import type { FailureType } from '../lib/chatEventDispatcher'

export type ErrorRecoveryProps = {
  /** 失败类型（必填，来自 dispatcher 输出或 failureHintEvent.keyword） */
  failureType: FailureType
  /** 关联 traceId（可选，用于跳转 TracePanel） */
  traceId?: string
  /** 自定义错误文案（覆盖默认文案，用于流内 error.detail） */
  detail?: string
  /** 是否可重试（默认按 failureType 推导，可显式覆盖） */
  recoverable?: boolean
  /** 重试回调（recoverable=true 时显示「重试」按钮） */
  onRetry?: () => void
  /** 查看 trace 回调（traceId 提供时显示「诊断」按钮） */
  onViewTrace?: (traceId: string) => void
}

// ── 色条色调 ────────────────────────────────────────────────
type StripeTone = 'amber' | 'orange' | 'blue' | 'red'

const FAILURE_TONE: Record<FailureType, StripeTone> = {
  // connection / timeout 类 → amber
  provider_connection_failed: 'amber',
  command_timeout: 'amber',
  model_stream_timeout: 'amber',
  dependency_missing: 'amber',
  syntax_mismatch: 'amber',
  // permission / rejected 类 → orange
  write_permission: 'orange',
  tool_failed: 'orange',
  approval_rejected: 'orange',
  job_stale_cancelled: 'orange',
  // empty / 事务性 / 提示类 → blue
  model_empty_response: 'blue',
  tool_executed_no_summary: 'blue',
  chat_busy: 'blue',
  context_trimmed: 'blue',
  approval_duplicated: 'blue',
  // 严重未知 → red
  runtime_failure: 'red',
  unknown_failure: 'red',
}

// ── 默认文案 + recoverable 矩阵 ────────────────────────────
const DEFAULT_TEXT: Record<FailureType, string> = {
  model_empty_response: '模型没有回复，可以重试一次',
  tool_executed_no_summary: '已执行操作，详见上方卡片',
  model_stream_timeout: '回复超时，请重试',
  provider_connection_failed: '模型服务连接失败',
  command_timeout: '命令执行超时，可重试',
  write_permission: '写入权限被拒绝，请检查配置',
  dependency_missing: '依赖未找到，请进入设置/doctor 检查',
  syntax_mismatch: '语法/解析错误，可重试',
  runtime_failure: '运行时异常，请查看诊断',
  chat_busy: 'Archer 正在处理上一轮',
  context_trimmed: '上下文已压缩，可继续',
  tool_failed: '工具执行失败',
  approval_rejected: '已拒绝操作',
  job_stale_cancelled: '后台任务已过期取消',
  approval_duplicated: '重复的确认请求，已忽略',
  unknown_failure: '发生未知错误，请查看诊断',
}

const DEFAULT_RECOVERABLE: Record<FailureType, boolean> = {
  model_empty_response: true,
  tool_executed_no_summary: false,
  model_stream_timeout: true,
  provider_connection_failed: true,
  command_timeout: true,
  write_permission: false,
  dependency_missing: true,
  syntax_mismatch: true,
  runtime_failure: true,
  chat_busy: false,
  context_trimmed: false,
  tool_failed: true,
  approval_rejected: false,
  job_stale_cancelled: false,
  approval_duplicated: false,
  unknown_failure: true,
}

export function ErrorRecovery({
  failureType,
  traceId,
  detail,
  recoverable,
  onRetry,
  onViewTrace,
}: ErrorRecoveryProps): React.ReactElement {
  const tone = FAILURE_TONE[failureType] || 'red'
  const isRecoverable = recoverable ?? DEFAULT_RECOVERABLE[failureType]
  const text = detail || DEFAULT_TEXT[failureType]
  const canRetry = isRecoverable && Boolean(onRetry)
  const canViewTrace = Boolean(traceId && onViewTrace)

  return (
    <aside
      className={`error-recovery error-recovery-tone-${tone}`}
      aria-label="错误恢复"
      data-failure-type={failureType}
      data-trace-id={traceId}
    >
      <span className="error-recovery-stripe" aria-hidden="true" />
      <p className="error-recovery-text">{text}</p>
      {(canRetry || canViewTrace) && (
        <div className="error-recovery-actions">
          {canRetry && (
            <button
              type="button"
              className="error-recovery-retry"
              onClick={onRetry}
              aria-label="重试"
              title="重试"
            >
              <RotateCw size={13} />
              <span>重试</span>
            </button>
          )}
          {canViewTrace && (
            <button
              type="button"
              className="error-recovery-trace"
              onClick={() => traceId && onViewTrace?.(traceId)}
              aria-label="查看诊断"
              title="查看诊断"
            >
              <Activity size={13} />
            </button>
          )}
        </div>
      )}
    </aside>
  )
}
