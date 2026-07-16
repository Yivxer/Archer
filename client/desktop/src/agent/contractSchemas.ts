import { z } from 'zod'
import type { AgentEvent } from './contracts'

const base = z.object({
  id: z.string().min(1),
  sessionId: z.string().min(1),
  createdAt: z.string().min(1),
  traceId: z.string().min(1).optional(),
})

const riskLevelSchema = z.enum(['low', 'medium', 'high', 'critical'])
const permissionLevelSchema = z.enum(['read-only', 'write-local', 'write-vault', 'deploy-remote'])
const toolStatusSchema = z.enum(['running', 'waiting_approval', 'complete', 'blocked', 'denied'])
const jobStatusSchema = z.enum(['queued', 'running', 'waiting_approval', 'complete', 'failed', 'cancelled'])
const planStatusSchema = z.enum(['proposed', 'accepted', 'dismissed'])
const workReceiptSchema = z.object({
  done: z.string(),
  source: z.string(),
  target: z.string(),
  verification: z.string(),
  rollback: z.string(),
  traceId: z.string().optional(),
})

export const textDeltaEventSchema = base.extend({
  type: z.literal('text.delta'),
  text: z.string(),
})

export const textFinalEventSchema = base.extend({
  type: z.literal('text.final'),
  text: z.string(),
})

export const toolRequestEventSchema = base.extend({
  type: z.literal('tool.request'),
  toolName: z.string().min(1),
  displayName: z.string().min(1),
  risk: riskLevelSchema,
  permissionLevel: permissionLevelSchema.optional(),
  status: toolStatusSchema,
  args: z.record(z.string(), z.unknown()),
  summary: z.string(),
  detail: z.string(),
  requiresApproval: z.boolean(),
  blocked: z.boolean(),
  draft: z.record(z.string(), z.unknown()).optional(),
})

export const toolResultEventSchema = base.extend({
  type: z.literal('tool.result'),
  requestId: z.string().min(1),
  toolName: z.string().min(1),
  status: z.enum(['complete', 'blocked', 'denied']),
  ok: z.boolean(),
  output: z.string(),
  message: z.string(),
  permissionLevel: permissionLevelSchema.optional(),
  receipt: workReceiptSchema.optional(),
})

export const approvalResultEventSchema = base.extend({
  type: z.literal('approval.result'),
  requestId: z.string().min(1),
  decision: z.enum(['approved', 'denied']),
  executed: z.boolean(),
  ok: z.boolean(),
  output: z.string(),
  message: z.string(),
  permissionLevel: permissionLevelSchema.optional(),
  receipt: workReceiptSchema.optional(),
})

export const jobEventSchema = base.extend({
  type: z.literal('job.event'),
  jobId: z.string().min(1),
  title: z.string(),
  status: jobStatusSchema,
  detail: z.string(),
  stale: z.boolean().optional(),
  progress: z.object({
    done: z.number().int().nonnegative(),
    total: z.number().int().nonnegative(),
  }).optional(),
})

export const planEventSchema = base.extend({
  type: z.literal('plan.event'),
  title: z.string(),
  status: planStatusSchema,
  detail: z.string(),
  prompt: z.string().optional(),
  steps: z.array(z.object({
    id: z.number().int().positive(),
    action: z.string().min(1),
    tool: z.string().min(1),
    requiresApproval: z.boolean(),
  })),
})

export const orchestrationEventSchema = base.extend({
  type: z.literal('orchestration.event'),
  intent: z.string(),
  subIntent: z.string(),
  mode: z.string(),
  depth: z.string(),
  labels: z.array(z.string()),
  needsMemory: z.boolean(),
  needsJob: z.boolean(),
  taskRoute: z.object({
    mode: z.enum(['foreground', 'background']),
    reason: z.string().min(1),
    title: z.string().min(1),
    timeoutSeconds: z.number().int().positive(),
  }),
})

export const statusEventSchema = base.extend({
  type: z.literal('status.event'),
  intentType: z.string(),
  intentLabel: z.string(),
  matchedSkills: z.array(z.string()),
  isBackground: z.boolean(),
  memoryScope: z.array(z.string()),
})

export const initiativeEventSchema = base.extend({
  type: z.literal('initiative.event'),
  kind: z.string(),
  title: z.string(),
  message: z.string(),
  shadow: z.boolean(),
  delivered: z.boolean(),
  decisionTrace: z.record(z.string(), z.unknown()),
})

export const runtimeContextEventSchema = base.extend({
  type: z.literal('runtime.context'),
  task: z.string(),
  phase: z.string(),
  userIntent: z.string(),
  lastResult: z.string(),
  expectedNext: z.string(),
  matchedSkills: z.array(z.string()).optional(),
  provider: z.string().optional(),
  model: z.string().optional(),
  baseUrlSummary: z.string().optional(),
})

export const failureHintEventSchema = base.extend({
  type: z.literal('failure.hint'),
  keyword: z.string(),
  stage: z.string(),
  recoverable: z.boolean(),
  detail: z.string(),
})

export const errorEventSchema = base.extend({
  type: z.literal('runtime.error'),
  scope: z.enum(['stream', 'approval', 'job', 'adapter']),
  message: z.string(),
  recoverable: z.boolean(),
})

export const agentEventSchema = z.discriminatedUnion('type', [
  textDeltaEventSchema,
  textFinalEventSchema,
  toolRequestEventSchema,
  toolResultEventSchema,
  approvalResultEventSchema,
  jobEventSchema,
  planEventSchema,
  orchestrationEventSchema,
  statusEventSchema,
  initiativeEventSchema,
  runtimeContextEventSchema,
  failureHintEventSchema,
  errorEventSchema,
])

export function parseAgentEvent(value: unknown): AgentEvent {
  return agentEventSchema.parse(value)
}
