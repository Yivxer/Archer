import type { FileRef } from '../../types'

export function messageWantsHugoPublish(text: string): boolean {
  const lowered = text.toLowerCase()
  const publishSignal = /部署|上线|发布|枫弋|札记|博客|iver\.yivxer|yivxer-blog/.test(lowered)
  const localMarkdownArticle = /\/users\/.+\.md/.test(lowered) && /文章|笔记/.test(lowered)
  return publishSignal || localMarkdownArticle
}

export function isTextLikeFile(path: string): boolean {
  return /\.(md|txt|json|toml|ya?ml|py|tsx?|jsx?|css|html|csv|log)$/i.test(path)
}

export function isObsidianMarkdownPath(path: string): boolean {
  return /\.md$/i.test(path) && (/iCloud~md~obsidian|Obsidian|\/Documents\/个人知识管理系统\//i.test(path))
}

export function extractMarkdownPathRefs(text: string): FileRef[] {
  const matches = text.match(/(?:~|\/Users)\/[^\n\r]+?\.md\b/g) || []
  return matches.map((raw) => {
    const path = raw.trim()
    return {
      path,
      name: path.split(/[\\/]/).pop() || path,
      attachStatus: 'reading' as const,
      attachDetail: '读取中…',
    }
  })
}

export function shouldLetBackendReadExplicitMarkdownPath(text: string): boolean {
  if (!extractMarkdownPathRefs(text).length) return false
  return /(?:枫弋札记|博客|博文|部署|发布|上传|发到|写到博客|hugo|yivxer-blog)/i.test(text)
}

export function isExplicitMarkdownPath(text: string, path: string): boolean {
  return extractMarkdownPathRefs(text).some((ref) => ref.path === path)
}

export function dedupeFileRefs(refs: FileRef[]): FileRef[] {
  const byPath = new Map<string, FileRef>()
  for (const ref of refs) {
    if (!ref.path || byPath.has(ref.path)) continue
    byPath.set(ref.path, ref)
  }
  return [...byPath.values()]
}

export function fileAttachLabel(file: FileRef): string {
  if (file.attachStatus === 'reading') return file.attachDetail || '读取中…'
  if (file.attachStatus === 'ok') return file.attachDetail || '已读取'
  if (file.attachStatus === 'failed') return file.attachDetail || '读取失败'
  if (file.attachStatus === 'ready') return file.attachDetail || '待发送'
  return formatFileSize(file.size)
}

export function formatFileSize(size?: number): string {
  if (!size) return '未知大小'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
