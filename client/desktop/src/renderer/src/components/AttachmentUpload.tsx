/**
 * L4.7 — <AttachmentUpload />
 *
 * 附件后台上传 + 状态展示。fire-and-forget 上传，发送时才显示状态，
 * 不阻塞用户输入。
 *
 * 契约：docs/ui-primitives.md §6
 *
 * 与旧实现差异：
 * - 旧 ChatPage 内联渲染 file-ref-row / message-file-ref-row
 * - 新 AttachmentUpload 抽成原语，统一 composer / message 两种变体
 * - 新增状态色点（8px 圆点，ready/reading/ok/failed 四色）
 * - 不自己管理 fileRefs state（由父组件传入）
 * - 不实现上传逻辑（上传在 adapters/localArcher.ts，原语只渲染状态）
 * - 不处理截图捕获（那是 composer 菜单的事）
 */

import React from 'react'
import { FileText, RotateCw, X } from 'lucide-react'
import type { FileRef } from '../types'

export type AttachmentUploadProps = {
  /** 当前附件列表（必填，来自 ChatPage fileRefs state） */
  files: FileRef[]
  /** 渲染变体：'composer'（输入框上方 chip）/ 'message'（消息内回看） */
  variant: 'composer' | 'message'
  /** 单个附件重试回调（attachStatus='failed' 时显示重试按钮） */
  onRetry?: (path: string) => void
  /** 移除附件回调（仅 'composer' 变体） */
  onRemove?: (path: string) => void
}

// ── 状态色点 ────────────────────────────────────────────────
type StatusDot = 'ready' | 'reading' | 'ok' | 'failed'

function statusOf(file: FileRef): StatusDot {
  return file.attachStatus || 'ready'
}

function statusLabel(status: StatusDot): string {
  switch (status) {
    case 'ready': return '待发送'
    case 'reading': return '读取中'
    case 'ok': return '已读取'
    case 'failed': return '读取失败'
  }
}

export function AttachmentUpload({
  files,
  variant,
  onRetry,
  onRemove,
}: AttachmentUploadProps): React.ReactElement | null {
  if (files.length === 0) return null

  const isComposer = variant === 'composer'
  const rowClass = isComposer ? 'file-ref-row' : 'message-file-ref-row'
  const chipClass = isComposer ? 'file-ref-chip' : 'message-file-ref-chip'
  const rowAriaLabel = isComposer ? '已引用文件' : '本轮引用文件'

  return (
    <div className={rowClass} aria-label={rowAriaLabel} data-variant={variant}>
      {files.map((file) => {
        const status = statusOf(file)
        const showRetry = !isComposer ? false : (status === 'failed' && Boolean(onRetry))
        const showRemove = isComposer && Boolean(onRemove)
        const title = file.attachDetail
          ? `${file.path}\n${file.attachDetail}`
          : file.path

        return (
          <span
            key={file.path}
            className={`${chipClass}${file.previewDataUrl ? ' has-preview' : ''}`}
            data-status={status}
            title={title}
          >
            {file.previewDataUrl ? (
              <img src={file.previewDataUrl} alt="" />
            ) : (
              <FileText size={13} />
            )}
            <span>
              <strong>{file.name}</strong>
              <em>{file.attachDetail || statusLabel(status)}</em>
            </span>
            <span
              className={`attachment-status-dot attachment-status-${status}`}
              aria-label={statusLabel(status)}
            />
            {showRetry && (
              <button
                type="button"
                className="attachment-retry-btn"
                onClick={() => onRetry?.(file.path)}
                aria-label={`重试 ${file.name}`}
                title="重试"
              >
                <RotateCw size={12} />
              </button>
            )}
            {showRemove && (
              <button
                type="button"
                className="attachment-remove-btn"
                onClick={() => onRemove?.(file.path)}
                aria-label={`移除 ${file.name}`}
              >
                <X size={12} />
              </button>
            )}
          </span>
        )
      })}
    </div>
  )
}
