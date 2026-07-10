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

export type HugoIntent =
  | 'execute_publish'
  | 'ask_capability'
  | 'content_review'
  | 'historical_mention'
  | 'delete_or_unpublish'
  | 'none'

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
export function classifyHugoIntent(text: string): HugoIntent {
  if (isQuickQuestion(text)) {
    return 'none'
  }
  const lowered = text.toLowerCase()
  const blogTarget = /博客|博文|枫弋|札记|yivxer-blog|iver\.yivxer|枫弋博客|hugo|网站|站点|posts\/|content\/posts/.test(lowered)
  const publishAction = /部署|发布|上线|上传|推送|同步到服务器|发到|投稿|deploy|publish|upload|rsync/.test(lowered)
  const questionMarker = /吗|么|？|\?|可以|可不可以|能不能|能否|有没有办法|支持|怎么|如何/.test(text)
  const assetTarget = /图片|图像|封面|配图|静态资源|static\/images|image|images|cover/i.test(text)
  const reviewIntent = /帮我分析|分析一下|帮我看看|看一下|看看这|读后感如何|读后感怎么样|读后感|如何|怎么样|评价|建议|优化|调整/.test(text)
  const pastPublish = /(?:部署|发布|上传|上线)了/.test(text)
  const activePublishCommand = /(?:帮我|请|麻烦|直接|现在|立刻|马上|给我).{0,16}(?:部署|发布|上传|上线|发到|写到|推送)(?!了)/.test(text)

  if (questionMarker && blogTarget && publishAction && assetTarget) return 'ask_capability'
  if (reviewIntent && (/\/users\/.+\.md/.test(lowered) || pastPublish) && !activePublishCommand) return 'content_review'
  if (blogTarget && /删除|下架|移除|撤回|删掉/.test(text)) return 'delete_or_unpublish'
  if (blogTarget && publishAction) return 'execute_publish'
  const localMarkdownPublish = /\/users\/.+\.md/.test(lowered) && /文章|笔记/.test(lowered) && publishAction
  if (localMarkdownPublish) return 'execute_publish'
  if (pastPublish) return 'historical_mention'
  return 'none'
}

function isHugoBlogPublishRequest(text: string): boolean {
  const intent = classifyHugoIntent(text)
  return intent === 'execute_publish' || intent === 'delete_or_unpublish'
}

export function isHugoBlogPublishPlan(plan: PlanEvent, contextText = ''): boolean {
  const planText = [
    plan.prompt,
    plan.title,
    plan.detail,
    ...plan.steps.flatMap((step) => [step.action, step.tool]),
  ].filter(Boolean).join(' ')
  const combined = `${contextText} ${planText}`.toLowerCase()
  const blogTarget = /枫弋|札记|yivxer-blog|iver\.yivxer|枫弋博客|hugo/.test(combined)
  const publishAction = /部署|发布|上线|发到|投稿|上传|deploy|publish/.test(planText.toLowerCase())
  const attachmentContinuation = /附件|这篇|这段|重新|格式/.test(planText)
  const approvalPlan = plan.steps.some((step) => (
    /approval|request_approval|确认/.test(`${step.action} ${step.tool}`.toLowerCase())
  ))
  return blogTarget && (publishAction || attachmentContinuation) && approvalPlan
}

export function isForegroundOnlyWritingFeedbackPlan(plan: PlanEvent): boolean {
  const requestText = (plan.prompt || '').toLowerCase()
  const planText = [
    plan.prompt,
    plan.title,
    plan.detail,
    ...plan.steps.flatMap((step) => [step.action, step.tool]),
  ].filter(Boolean).join(' ').toLowerCase()
  const hasMarkdownPath = /\/users\/.+\.md/.test(planText)
  const readonlyIntent = /不要更改|先不要改|不要修改|不改原文|不改文件|不直接改|先别改|先说说|说说你的想法|看看你的想法|我看看/.test(requestText)
  const writingFeedback = /ai\s*味|ai味|初稿|写作|文风|语气|优化处理|润色|修改思路|精修版本|你觉得|怎么样|调整|优化|分析一下|可以调整/.test(requestText)
  const userRequestedWrite = /写入|保存|修改文件|生成文档|发布|部署|上线|shell|git/.test(requestText)
  const writeStep = plan.steps.some((step) => /write|obsidian_write|写入/.test(`${step.action} ${step.tool}`.toLowerCase()))
  return hasMarkdownPath && writingFeedback && !userRequestedWrite && writeStep || (
    hasMarkdownPath && readonlyIntent && writingFeedback && writeStep
  )
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
import type { PlanEvent } from './contracts'
