/**
 * L4.6 — <PermissionPrompt />
 *
 * 权限等级提示。当工具被 blocked（权限不足、degraded 模式、高危操作未确认）
 * 时显示原因 + 等级 + 可选提权入口。
 *
 * 契约：docs/ui-primitives.md §5
 *
 * 与旧实现差异：
 * - 旧 ChatPage `ToolEventBody` 中 blocked 分支内联渲染，文案散落
 * - 新 PermissionPrompt 统一 4 级色条 + 图标 + target 渲染 + 提权/忽略动作
 * - 不自己判断权限等级（由父组件根据 connectionState + tool_event 决定）
 * - 不执行提权操作（只触发 onEscalate 回调）
 *
 * 类型说明：
 *   这里 PermissionLevel 是原语自己的简化类型（read/write/deploy/shell），
 *   来自 ui-primitives.md §5 契约。父组件负责把 contracts.ts 的 PermissionLevel
 *   （read-only/write-local/write-vault/deploy-remote）映射过来。
 */

import React from 'react'
import { Shield, ShieldAlert, X } from 'lucide-react'

export type PermissionLevel = 'read' | 'write' | 'deploy' | 'shell'

export type PermissionPromptProps = {
  /** 权限等级（必填） */
  level: PermissionLevel
  /** 被阻止的原因（必填，来自 tool_event.detail 或 dispatcher） */
  reason: string
  /** 被阻止的操作目标（path / url / command） */
  target?: {
    path?: string
    url?: string
    command?: string
  }
  /** 是否可申请提权（默认 false，degraded 模式下为 true） */
  canEscalate?: boolean
  /** 申请提权回调（打开 SettingsPage 连接设置） */
  onEscalate?: () => void
  /** 关闭/忽略回调 */
  onDismiss?: () => void
}

// ── 色条色调 ────────────────────────────────────────────────
type StripeTone = 'blue' | 'amber' | 'orange' | 'red'

const LEVEL_TONE: Record<PermissionLevel, StripeTone> = {
  read: 'blue',
  write: 'amber',
  deploy: 'orange',
  shell: 'red',
}

const LEVEL_LABEL: Record<PermissionLevel, string> = {
  read: '读取',
  write: '写入',
  deploy: '部署',
  shell: '命令',
}

export function PermissionPrompt({
  level,
  reason,
  target,
  canEscalate = false,
  onEscalate,
  onDismiss,
}: PermissionPromptProps): React.ReactElement {
  const tone = LEVEL_TONE[level]
  const Icon = level === 'shell' || level === 'deploy' ? ShieldAlert : Shield
  const canEscalateAction = canEscalate && Boolean(onEscalate)
  const targetText = target?.path || target?.url || target?.command || ''
  const targetKind = target?.path ? 'path' : target?.url ? 'url' : target?.command ? 'command' : null

  return (
    <aside
      className={`permission-prompt permission-prompt-tone-${tone}`}
      aria-label="权限提示"
      data-level={level}
    >
      <span className="permission-prompt-stripe" aria-hidden="true" />
      <div className="permission-prompt-body">
        <div className="permission-prompt-head">
          <Icon size={16} className="permission-prompt-icon" />
          <strong className="permission-prompt-title">
            {LEVEL_LABEL[level]}权限被阻止
          </strong>
          {onDismiss && (
            <button
              type="button"
              className="permission-prompt-dismiss"
              onClick={onDismiss}
              aria-label="忽略"
              title="忽略"
            >
              <X size={13} />
            </button>
          )}
        </div>
        <p className="permission-prompt-reason">{reason}</p>
        {targetText && (
          <code className={`permission-prompt-target permission-prompt-target-${targetKind}`}>
            {targetText}
          </code>
        )}
        {(canEscalateAction) && (
          <div className="permission-prompt-actions">
            <button
              type="button"
              className="permission-prompt-escalate"
              onClick={onEscalate}
              aria-label="前往设置"
              title="前往设置"
            >
              <ShieldAlert size={13} />
              <span>前往设置</span>
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}
