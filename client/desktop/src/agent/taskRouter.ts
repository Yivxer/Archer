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

const APPROVAL_TARGETS = [
  'obsidian',
  '写入',
  '保存',
  '修改文件',
  '生成文档',
  '导出',
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

/** 枫弋札记发布/部署必须走前台流式聊天，才能带上 fileRefs 并执行 hugo_blog。 */
function isHugoBlogPublishRequest(text: string): boolean {
  if (isQuickQuestion(text)) {
    return false
  }
  const lowered = text.toLowerCase()
  const blogTarget = /枫弋|札记|yivxer-blog|iver\.yivxer|枫弋博客/.test(lowered)
  const publishAction = /部署|发布|上线|发到|投稿/.test(lowered)
  const localMarkdownPublish = /\/users\/.+\.md/.test(lowered) && /文章|笔记/.test(lowered) && publishAction
  return (blogTarget && publishAction) || localMarkdownPublish
}

function isApprovalFirstRequest(text: string): boolean {
  const lowered = text.toLowerCase()
  return APPROVAL_TARGETS.some((keyword) => lowered.includes(keyword.toLowerCase()))
}

function pythonOrchestratorRoute(title: string): RuntimeTaskRoute {
  return {
    mode: 'foreground',
    reason: 'python orchestrator owns routing',
    title,
    timeoutSeconds: 300,
  }
}

export function routeTaskForRuntime(input: RuntimeTaskRouteInput): RuntimeTaskRoute {
  const text = input.text.trim()
  const fileCount = input.fileCount ?? 0
  const lineCount = text.split('\n').length
  const hasSignal = hasImplementationSignal(text)
  const hasPathOrCode = looksLikePathOrCode(text)

  if (isHugoBlogPublishRequest(text)) {
    return {
      mode: 'foreground',
      reason: 'hugo blog publish uses attachments and tool stream',
      title: compactTitle(text),
      timeoutSeconds: 300,
    }
  }

  if (!text || isQuickQuestion(text)) {
    return {
      mode: 'foreground',
      reason: 'short conversational request',
      title: compactTitle(text),
      timeoutSeconds: 300,
    }
  }

  if (isApprovalFirstRequest(text)) {
    return {
      mode: 'foreground',
      reason: 'approval-first task',
      title: compactTitle(text),
      timeoutSeconds: 300,
    }
  }

  if (text.length >= 1200 || lineCount >= 14) {
    return pythonOrchestratorRoute(compactTitle(text))
  }

  if (hasSignal && (text.length >= 80 || fileCount > 0 || hasPathOrCode)) {
    if (fileCount > 0 && /部署|发布|上线/.test(text) && text.length < 240) {
      return {
        mode: 'foreground',
        reason: 'attached publish request should not lose fileRefs in background jobs',
        title: compactTitle(text),
        timeoutSeconds: 300,
      }
    }
    return pythonOrchestratorRoute(compactTitle(text))
  }

  return {
    mode: 'foreground',
    reason: 'interactive chat request',
    title: compactTitle(text),
    timeoutSeconds: 300,
  }
}
