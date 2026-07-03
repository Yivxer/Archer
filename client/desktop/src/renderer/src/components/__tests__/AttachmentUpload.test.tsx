/**
 * L4.7 — <AttachmentUpload /> 组件测试。
 *
 * 测试策略：
 *   - 用 react-dom/server 静态渲染 + 字符串断言
 *   - 覆盖：composer/message 两种变体、状态色点 4 色、预览图、
 *     重试按钮（仅 composer + failed + onRetry）、移除按钮（仅 composer + onRemove）、
 *     空列表返回 null、aria-label
 */

import { describe, expect, it } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { AttachmentUpload } from '../AttachmentUpload'
import type { FileRef } from '../../types'

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
}

const baseFile: FileRef = {
  path: '/tmp/notes.md',
  name: 'notes.md',
  size: 1024,
  attachStatus: 'ready',
  attachDetail: '',
}

function fileWith(overrides: Partial<FileRef>): FileRef {
  return { ...baseFile, ...overrides }
}

// ── 基础渲染 ────────────────────────────────────────────────

describe('AttachmentUpload — L4.7 基础渲染', () => {
  it('空列表返回 null', () => {
    const html = render(<AttachmentUpload files={[]} variant="composer" />)
    expect(html).toBe('')
  })

  it('composer 变体渲染 file-ref-row + aria-label', () => {
    const html = render(<AttachmentUpload files={[baseFile]} variant="composer" />)
    expect(html).toContain('class="file-ref-row"')
    expect(html).toContain('aria-label="已引用文件"')
  })

  it('message 变体渲染 message-file-ref-row + aria-label', () => {
    const html = render(<AttachmentUpload files={[baseFile]} variant="message" />)
    expect(html).toContain('class="message-file-ref-row"')
    expect(html).toContain('aria-label="本轮引用文件"')
  })

  it('data-variant 注入', () => {
    const html = render(<AttachmentUpload files={[baseFile]} variant="composer" />)
    expect(html).toContain('data-variant="composer"')
  })

  it('渲染文件名 + path key', () => {
    const html = render(<AttachmentUpload files={[baseFile]} variant="composer" />)
    expect(html).toContain('notes.md')
  })
})

// ── 状态色点 ────────────────────────────────────────────────

describe('AttachmentUpload — 状态色点', () => {
  const statuses: Array<{ status: NonNullable<FileRef['attachStatus']>; className: string; label: string }> = [
    { status: 'ready', className: 'attachment-status-ready', label: '待发送' },
    { status: 'reading', className: 'attachment-status-reading', label: '读取中' },
    { status: 'ok', className: 'attachment-status-ok', label: '已读取' },
    { status: 'failed', className: 'attachment-status-failed', label: '读取失败' },
  ]

  for (const { status, className, label } of statuses) {
    it(`status=${status} → ${className} + aria-label="${label}"`, () => {
      const html = render(
        <AttachmentUpload
          files={[fileWith({ attachStatus: status, attachDetail: '' })]}
          variant="composer"
        />,
      )
      expect(html).toContain(className)
      expect(html).toContain(`aria-label="${label}"`)
    })
  }

  it('attachStatus 缺失时默认 ready', () => {
    const html = render(
      <AttachmentUpload
        files={[fileWith({ attachStatus: undefined })]}
        variant="composer"
      />,
    )
    expect(html).toContain('attachment-status-ready')
    expect(html).toContain('data-status="ready"')
  })

  it('attachDetail 提供时 em 显示 detail（覆盖默认 label）', () => {
    const html = render(
      <AttachmentUpload
        files={[fileWith({ attachStatus: 'reading', attachDetail: '自定义读取中文案' })]}
        variant="composer"
      />,
    )
    expect(html).toContain('自定义读取中文案')
  })
})

// ── 预览图 ───────────────────────────────────────────────────

describe('AttachmentUpload — 预览图', () => {
  it('previewDataUrl 提供时渲染 img + has-preview class', () => {
    const html = render(
      <AttachmentUpload
        files={[fileWith({ previewDataUrl: 'data:image/png;base64,xxx' })]}
        variant="composer"
      />,
    )
    expect(html).toContain('has-preview')
    expect(html).toContain('<img')
    expect(html).toContain('src="data:image/png;base64,xxx"')
  })

  it('previewDataUrl 缺失时渲染 FileText 图标', () => {
    const html = render(<AttachmentUpload files={[baseFile]} variant="composer" />)
    expect(html).not.toContain('has-preview')
    expect(html).not.toContain('<img')
    // FileText lucide icon 渲染为 svg
    expect(html).toContain('<svg')
  })
})

// ── 重试按钮（仅 composer + failed + onRetry） ─────────────

describe('AttachmentUpload — 重试按钮', () => {
  it('composer + failed + onRetry → 渲染重试按钮', () => {
    const html = render(
      <AttachmentUpload
        files={[fileWith({ attachStatus: 'failed' })]}
        variant="composer"
        onRetry={() => {}}
      />,
    )
    expect(html).toContain('attachment-retry-btn')
    expect(html).toContain('aria-label="重试 notes.md"')
  })

  it('composer + failed 但 onRetry 缺失 → 不渲染重试按钮', () => {
    const html = render(
      <AttachmentUpload
        files={[fileWith({ attachStatus: 'failed' })]}
        variant="composer"
      />,
    )
    expect(html).not.toContain('attachment-retry-btn')
  })

  it('composer + 非 failed → 不渲染重试按钮', () => {
    const html = render(
      <AttachmentUpload
        files={[fileWith({ attachStatus: 'ok' })]}
        variant="composer"
        onRetry={() => {}}
      />,
    )
    expect(html).not.toContain('attachment-retry-btn')
  })

  it('message 变体 + failed + onRetry → 不渲染重试按钮（message 只读）', () => {
    const html = render(
      <AttachmentUpload
        files={[fileWith({ attachStatus: 'failed' })]}
        variant="message"
        onRetry={() => {}}
      />,
    )
    expect(html).not.toContain('attachment-retry-btn')
  })
})

// ── 移除按钮（仅 composer + onRemove） ─────────────────────

describe('AttachmentUpload — 移除按钮', () => {
  it('composer + onRemove → 渲染移除按钮', () => {
    const html = render(
      <AttachmentUpload
        files={[baseFile]}
        variant="composer"
        onRemove={() => {}}
      />,
    )
    expect(html).toContain('attachment-remove-btn')
    expect(html).toContain('aria-label="移除 notes.md"')
  })

  it('composer + onRemove 缺失 → 不渲染移除按钮', () => {
    const html = render(
      <AttachmentUpload files={[baseFile]} variant="composer" />,
    )
    expect(html).not.toContain('attachment-remove-btn')
  })

  it('message 变体 + onRemove → 不渲染移除按钮（message 只读）', () => {
    const html = render(
      <AttachmentUpload
        files={[baseFile]}
        variant="message"
        onRemove={() => {}}
      />,
    )
    expect(html).not.toContain('attachment-remove-btn')
  })
})

// ── 多文件 ──────────────────────────────────────────────────

describe('AttachmentUpload — 多文件', () => {
  it('多个文件按顺序渲染', () => {
    const files: FileRef[] = [
      fileWith({ path: '/a.md', name: 'a.md' }),
      fileWith({ path: '/b.md', name: 'b.md' }),
      fileWith({ path: '/c.md', name: 'c.md' }),
    ]
    const html = render(<AttachmentUpload files={files} variant="composer" />)
    expect(html).toContain('a.md')
    expect(html).toContain('b.md')
    expect(html).toContain('c.md')
    // 3 个 chip
    const chipCount = (html.match(/file-ref-chip/g) || []).length
    expect(chipCount).toBeGreaterThanOrEqual(3)
  })

  it('混合状态文件', () => {
    const files: FileRef[] = [
      fileWith({ path: '/a.md', name: 'a.md', attachStatus: 'ok' }),
      fileWith({ path: '/b.md', name: 'b.md', attachStatus: 'reading' }),
      fileWith({ path: '/c.md', name: 'c.md', attachStatus: 'failed' }),
    ]
    const html = render(
      <AttachmentUpload
        files={files}
        variant="composer"
        onRetry={() => {}}
        onRemove={() => {}}
      />,
    )
    expect(html).toContain('attachment-status-ok')
    expect(html).toContain('attachment-status-reading')
    expect(html).toContain('attachment-status-failed')
  })
})

// ── title 属性 ──────────────────────────────────────────────

describe('AttachmentUpload — title 属性', () => {
  it('attachDetail 提供时 title 含 path + detail', () => {
    const html = render(
      <AttachmentUpload
        files={[fileWith({ attachDetail: '读取中…' })]}
        variant="composer"
      />,
    )
    expect(html).toContain('title="/tmp/notes.md')
    expect(html).toContain('读取中…')
  })

  it('attachDetail 缺失时 title 仅含 path', () => {
    const html = render(
      <AttachmentUpload
        files={[fileWith({ attachDetail: '' })]}
        variant="composer"
      />,
    )
    expect(html).toContain('title="/tmp/notes.md"')
  })
})
