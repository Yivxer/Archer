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
  errorEventSchema,
])

export function parseAgentEvent(value: unknown): AgentEvent {
  return agentEventSchema.parse(value)
}
