/**
 * L4.8 — <EmptyState />
 *
 * 统一空状态文案。各页面「没有数据」时的友好提示，避免每个页面自己拼。
 *
 * 契约：docs/ui-primitives.md §7
 *
 * 与旧实现差异：
 * - 旧页面各自拼 div + 文案（TasksPage empty-inline / TodayPage today-empty /
 *   ChatPage trace-empty / MemoryPage 等）
 * - 新 EmptyState 统一 title/hint/action/icon/compact 五个维度
 * - 不处理错误状态文案（错误用 ErrorRecovery，EmptyState 只处理「无数据」）
 * - 不自己定义文案（由父组件传入 title/hint）
 */

import React from 'react'
import { Inbox } from 'lucide-react'

export type EmptyStateProps = {
  /** 标题（必填，如「暂无记忆」） */
  title: string
  /** 提示文案（可选，如「连接本地 API 后会读取」） */
  hint?: string
  /** 行动按钮（可选，ReactNode 让父组件控制样式） */
  action?: React.ReactNode
  /** 图标（可选，lucide icon 组件，默认 `Inbox`） */
  icon?: React.ElementType
  /** 紧凑模式（行内，不占满屏，用于侧边栏小区域） */
  compact?: boolean
}

export function EmptyState({
  title,
  hint,
  action,
  icon: Icon = Inbox,
  compact = false,
}: EmptyStateProps): React.ReactElement {
  const containerClass = compact ? 'empty-state empty-state-compact' : 'empty-state empty-state-standard'

  return (
    <div
      className={containerClass}
      role="status"
      aria-label={title}
      data-compact={compact}
    >
      <Icon size={compact ? 13 : 32} className="empty-state-icon" />
      <div className="empty-state-text">
        <strong className="empty-state-title">{title}</strong>
        {hint && <span className="empty-state-hint">{hint}</span>}
      </div>
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  )
}
