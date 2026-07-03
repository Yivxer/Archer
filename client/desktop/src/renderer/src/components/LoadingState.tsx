/**
 * L4.9 — <LoadingState />
 *
 * 统一加载状态文案。各页面/区块「正在加载」时的提示，避免「读取中」
 * 「加载中」「正在拉取」各自表述。
 *
 * 契约：docs/ui-primitives.md §8
 *
 * 与旧实现差异：
 * - 旧页面散落 ThinkingDots + 自定义文案（ChatPage 多处 / 各页面 loadState）
 * - 新 LoadingState 统一 stage 默认文案表 + showDots 开关 + compact 模式
 * - 不替代 ThinkingDots 组件（原语内部用独立 dot 元素，不复用 ThinkingDots
 *   以避免「思考中」文字干扰 connecting/fetching/applying 等阶段文案）
 * - 不处理错误状态（加载失败用 ErrorRecovery）
 * - 不自己决定何时显示（由父组件根据 loadState 控制 mount/unmount）
 */

import React from 'react'

export type LoadingStage = 'connecting' | 'fetching' | 'thinking' | 'applying'

export type LoadingStateProps = {
  /** 加载阶段（决定默认文案） */
  stage?: LoadingStage
  /** 自定义文案（覆盖 stage 默认文案） */
  hint?: string
  /** 是否显示 ThinkingDots 动画（默认 true） */
  showDots?: boolean
  /** 紧凑模式（行内） */
  compact?: boolean
}

const STAGE_TEXT: Record<LoadingStage, string> = {
  connecting: '正在连接 Archer...',
  fetching: '正在读取...',
  thinking: 'Archer 正在想...',
  applying: '正在应用...',
}

export function LoadingState({
  stage = 'fetching',
  hint,
  showDots = true,
  compact = false,
}: LoadingStateProps): React.ReactElement {
  const text = hint || STAGE_TEXT[stage]
  const containerClass = compact
    ? 'loading-state loading-state-compact'
    : 'loading-state loading-state-standard'
  const dotSize = compact ? 4 : 6

  return (
    <div
      className={containerClass}
      role="status"
      aria-label={text}
      data-stage={stage}
      data-compact={compact}
    >
      {showDots && (
        <span className="loading-state-dots" aria-hidden="true">
          <span className="loading-state-dot" style={{ width: dotSize, height: dotSize, animationDelay: '0s' }} />
          <span className="loading-state-dot" style={{ width: dotSize, height: dotSize, animationDelay: '0.18s' }} />
          <span className="loading-state-dot" style={{ width: dotSize, height: dotSize, animationDelay: '0.36s' }} />
        </span>
      )}
      <span className="loading-state-text">{text}</span>
    </div>
  )
}
