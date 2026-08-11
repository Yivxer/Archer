import type { PlanEvent } from './contracts'

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
  // A structured execution contract is an explicit background handoff. Do not let
  // path/title keywords (for example a note named "写作方法") override it.
  if (plan.execution?.jobKind === 'vault_reflection') return false

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
