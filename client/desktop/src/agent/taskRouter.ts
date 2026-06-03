export type RuntimeTaskRoute = {
  mode: 'foreground' | 'background'
  reason: string
  title: string
  timeoutSeconds: number
}

export type RuntimeTaskRouteInput = {
  text: string
  fileCount?: number
}

const BACKGROUND_KEYWORDS = [
  '继续做',
  '继续优化',
  '按照计划',
  '执行计划',
  '开始执行',
  '实现',
  '修复',
  '重构',
  '迁移',
  '接入',
  '跑测试',
  '构建',
  '部署',
  '发布博客',
  '上传博客',
  'hugo',
  'deploy',
  '整理成文档',
  '更新文档',
]

const QUICK_QUESTION_PREFIXES = [
  '为什么',
  '怎么理解',
  '什么是',
  '能不能解释',
  '你觉得',
]

function compactTitle(text: string): string {
  return text.replace(/\s+/g, ' ').trim().slice(0, 42) || '后台任务'
}

function hasImplementationSignal(text: string): boolean {
  const lowered = text.toLowerCase()
  return BACKGROUND_KEYWORDS.some((keyword) => lowered.includes(keyword.toLowerCase()))
}

function looksLikePathOrCode(text: string): boolean {
  return /\/Users\/|client\/|terminal\/|src\/|tests\/|```|`[^`]+`|\.(ts|tsx|py|md|json|toml|css)\b/.test(text)
}

function isQuickQuestion(text: string): boolean {
  const compact = text.trim()
  return compact.length < 180 && QUICK_QUESTION_PREFIXES.some((prefix) => compact.startsWith(prefix))
}

export function routeTaskForRuntime(input: RuntimeTaskRouteInput): RuntimeTaskRoute {
  const text = input.text.trim()
  const fileCount = input.fileCount ?? 0
  const lineCount = text.split('\n').length
  const hasSignal = hasImplementationSignal(text)
  const hasPathOrCode = looksLikePathOrCode(text)

  if (!text || isQuickQuestion(text)) {
    return {
      mode: 'foreground',
      reason: 'short conversational request',
      title: compactTitle(text),
      timeoutSeconds: 300,
    }
  }

  if (text.length >= 1200 || lineCount >= 14) {
    return {
      mode: 'background',
      reason: 'large request',
      title: compactTitle(text),
      timeoutSeconds: 600,
    }
  }

  if (hasSignal && (text.length >= 80 || fileCount > 0 || hasPathOrCode)) {
    return {
      mode: 'background',
      reason: 'implementation-style request',
      title: compactTitle(text),
      timeoutSeconds: 600,
    }
  }

  return {
    mode: 'foreground',
    reason: 'interactive chat request',
    title: compactTitle(text),
    timeoutSeconds: 300,
  }
}
