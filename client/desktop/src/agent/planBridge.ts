import type { PlanEvent, PlanStatus } from './contracts'

export function buildPlanExecutionPrompt(plan: PlanEvent): string {
  const base = plan.prompt?.trim() || plan.detail?.trim() || plan.title
  const stepLines = plan.steps.map(
    (step) => `${step.id}. ${step.action} (tool=${step.tool}${step.requiresApproval ? ', 需确认' : ''})`,
  )
  return [
    base,
    '',
    '[已确认任务计划]',
    plan.title,
    ...stepLines,
    '',
    '请按以上计划执行。涉及写入、保存、发布、Obsidian、shell、git 等副作用步骤必须先等待用户确认，不要声称已经执行。',
  ].join('\n')
}

export function planWithStatus(plan: PlanEvent, status: PlanStatus): PlanEvent {
  return {
    ...plan,
    status,
    createdAt: new Date().toISOString(),
  }
}
