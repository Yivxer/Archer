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

export type ConfirmedPlanJobPayload = {
  title: string
  kind: string
  prompt: string
  timeoutSeconds: number
  runtimeShadowRunId?: string
  vaultArgs?: {
    note_path: string
    force: false
  }
}

export type PlanResultSessionMessage = {
  role: 'system' | 'user' | 'assistant'
  content: string
}

export function buildPlanResultSessionMessages(
  plan: PlanEvent,
  messages: PlanResultSessionMessage[],
  reply: string,
): PlanResultSessionMessage[] {
  const source = [...messages]
  if (!source.some((message) => message.role === 'user')) {
    source.unshift({
      role: 'user',
      content: plan.prompt?.trim() || plan.title,
    })
  }
  return [...source, { role: 'assistant', content: reply }]
}

export function buildConfirmedPlanJobPayload(plan: PlanEvent): ConfirmedPlanJobPayload {
  const common = {
    title: plan.title || '任务计划',
    prompt: buildPlanExecutionPrompt(plan),
    runtimeShadowRunId: plan.shadowProjection?.runId,
  }
  if (plan.execution?.jobKind === 'vault_reflection') {
    return {
      ...common,
      kind: 'vault_reflection',
      timeoutSeconds: plan.execution.timeoutSeconds,
      vaultArgs: {
        note_path: plan.execution.vaultArgs.notePath,
        force: false,
      },
    }
  }
  return {
    ...common,
    kind: 'chat',
    timeoutSeconds: 600,
  }
}

export function planWithStatus(plan: PlanEvent, status: PlanStatus): PlanEvent {
  const shadowProjection = plan.shadowProjection && status !== 'proposed'
    ? {
        ...plan.shadowProjection,
        legacyStatus: status,
        status: 'unsupported' as const,
        differences: [
          {
            field: 'legacy.status',
            expected: 'proposed',
            actual: status,
          },
        ],
      }
    : plan.shadowProjection
  return {
    ...plan,
    status,
    createdAt: new Date().toISOString(),
    shadowProjection,
  }
}

export type PlanChildJobSpec = {
  title: string
  kind: string
  prompt: string
  autoStart?: boolean
  timeoutSeconds?: number
}

export function buildPlanCoordinatorPrompt(plan: PlanEvent): string {
  const context = plan.prompt?.trim() || plan.detail?.trim() || plan.title
  const stepLines = plan.steps.map(
    (step) => `${step.id}. ${step.action} (tool=${step.tool}${step.requiresApproval ? ', 需确认' : ''})`,
  )
  return [
    context,
    '',
    '[计划协调任务]',
    plan.title,
    ...stepLines,
    '',
    '这是父任务：子任务会按步骤并行/顺序执行。你只需在全部子任务完成后汇总结果，不要在此重复执行各步骤。',
  ].join('\n')
}

export function buildPlanChildJobSpecs(plan: PlanEvent): PlanChildJobSpec[] {
  const context = plan.prompt?.trim() || plan.detail?.trim() || plan.title
  return plan.steps.map((step) => ({
    title: `${plan.title || '任务计划'} · 步骤 ${step.id}`,
    kind: step.requiresApproval ? 'tool' : 'analysis',
    prompt: [
      `原始请求：${context}`,
      '',
      `当前步骤 ${step.id}：${step.action}`,
      `预期工具：${step.tool}${step.requiresApproval ? '（需用户确认后再执行副作用）' : ''}`,
      '',
      '只完成这一步；完成后简要汇报结果，不要跳过后续步骤声称全部完成。',
    ].join('\n'),
    autoStart: !step.requiresApproval,
    timeoutSeconds: step.requiresApproval ? 900 : 600,
  }))
}
