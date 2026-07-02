/**
 * L1.2.4 — <ConnectionBadge /> 连接状态徽章组件。
 *
 * 视觉规范（稳定性框架 §四 徽章视觉规范表）：
 *   disconnected  #9ca3af 灰   空心圆    未连接
 *   connecting    #f59e0b 琥珀  旋转环    正在连接…
 *   ready         #10b981 翠绿  实心圆+柔光 已就绪
 *   degraded      #f59e0b 琥珀  实心三角   降级中：<原因>
 *   recovering    #3b82f6 蓝    旋转弧    正在恢复本地 API…
 *   dead          #ef4444 红    实心叉    本地 API 不可用
 *
 * 用法：
 *   <ConnectionBadge state={state} reason={reason} size="footer" onClick={openDiagnostics} />
 */

import React from 'react'

import { badgeVisual } from '../lib/connectionState'
import type { ConnectionState } from '../lib/connectionState'

export type ConnectionBadgeSize = 'footer' | 'banner' | 'inline'

export type ConnectionBadgeProps = {
  state: ConnectionState
  /** degraded 状态的原因（来自 doctor warn / ready 5xx） */
  reason?: string
  /** dead 状态的原因（来自 launch_fail / restart 失败） */
  deadReason?: string
  size?: ConnectionBadgeSize
  /** 是否显示文案（默认 true） */
  showLabel?: boolean
  /** 点击回调（通常进入诊断面板） */
  onClick?: () => void
  /** 是否可点击（默认有 onClick 即可点击） */
  clickable?: boolean
}

export function ConnectionBadge({
  state,
  reason,
  deadReason,
  size = 'footer',
  showLabel = true,
  onClick,
  clickable,
}: ConnectionBadgeProps): React.ReactElement {
  const visual = badgeVisual(state)
  const label = computeLabel(state, reason, deadReason)
  const isClickable = clickable ?? Boolean(onClick)

  const className = [
    'connection-badge',
    `connection-badge-${size}`,
    `connection-badge-${state}`,
    isClickable ? 'clickable' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <button
      type="button"
      className={className}
      onClick={onClick}
      disabled={!isClickable}
      aria-label={label}
      title={computeTitle(state, reason, deadReason)}
    >
      <span className="connection-badge-dot" aria-hidden="true">
        {renderDot(visual.dot, visual.color)}
      </span>
      {showLabel && (
        <span className="connection-badge-label">{label}</span>
      )}
    </button>
  )
}

// ───────────────────────── 文案 ─────────────────────────

function computeLabel(
  state: ConnectionState,
  reason?: string,
  deadReason?: string,
): string {
  if (state === 'degraded' && reason) {
    return `降级中：${reason}`
  }
  if (state === 'dead' && deadReason) {
    return '本地 API 不可用'
  }
  return badgeVisual(state).label
}

function computeTitle(
  state: ConnectionState,
  reason?: string,
  deadReason?: string,
): string {
  const visual = badgeVisual(state)
  if (state === 'degraded' && reason) {
    return `${visual.labelEn}: ${reason}`
  }
  if (state === 'dead' && deadReason) {
    return `${visual.labelEn}: ${deadReason}`
  }
  return visual.labelEn
}

// ───────────────────────── 圆点渲染 ─────────────────────────

function renderDot(
  style: 'hollow' | 'spin' | 'solid-glow' | 'triangle' | 'arc' | 'cross',
  color: string,
): React.ReactNode {
  switch (style) {
    case 'hollow':
      // 空心圆：disconnected
      return (
        <span
          className="cb-dot cb-dot-hollow"
          style={{ borderColor: color }}
        />
      )
    case 'spin':
      // 旋转环：connecting
      return (
        <span
          className="cb-dot cb-dot-spin"
          style={{ borderColor: color, borderTopColor: 'transparent' }}
        />
      )
    case 'solid-glow':
      // 实心圆 + 柔光：ready
      return (
        <span
          className="cb-dot cb-dot-solid-glow"
          style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}` }}
        />
      )
    case 'triangle':
      // 实心三角：degraded
      return (
        <span
          className="cb-dot cb-dot-triangle"
          style={{ borderBottomColor: color }}
        />
      )
    case 'arc':
      // 旋转弧：recovering
      return (
        <span
          className="cb-dot cb-dot-arc"
          style={{ borderColor: color, borderTopColor: 'transparent' }}
        />
      )
    case 'cross':
      // 实心叉：dead
      return (
        <span
          className="cb-dot cb-dot-cross"
          style={{ '--cb-cross-color': color } as React.CSSProperties}
        >
          <span className="cb-cross-line cb-cross-line-1" />
          <span className="cb-cross-line cb-cross-line-2" />
        </span>
      )
    default:
      return null
  }
}
