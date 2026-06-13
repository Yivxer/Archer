import { z } from 'zod'
import type { AgentEvent } from './contracts'

const base = z.object({
  id: z.string().min(1),
  sessionId: z.string().min(1),
  createdAt: z.string().min(1),
})

const riskLevelSchema = z.enum(['low', 'medium', 'high', 'critical'])
const toolStatusSchema = z.enum(['running', 'waiting_approval', 'complete', 'blocked', 'denied'])
const jobStatusSchema = z.enum(['queued', 'running', 'waiting_approval', 'complete', 'failed', 'cancelled'])
const planStatusSchema = z.enum(['proposed', 'accepted', 'dismissed'])

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
})

export const approvalResultEventSchema = base.extend({
  type: z.literal('approval.result'),
  requestId: z.string().min(1),
  decision: z.enum(['approved', 'denied']),
  executed: z.boolean(),
  ok: z.boolean(),
  output: z.string(),
  message: z.string(),
})

export const jobEventSchema = base.extend({
  type: z.literal('job.event'),
  jobId: z.string().min(1),
  title: z.string(),
  status: jobStatusSchema,
  detail: z.string(),
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
  errorEventSchema,
])

export function parseAgentEvent(value: unknown): AgentEvent {
  return agentEventSchema.parse(value)
}
