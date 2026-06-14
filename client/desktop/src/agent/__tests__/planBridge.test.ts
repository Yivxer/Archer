import { describe, expect, it } from 'vitest'
import { buildPlanChildJobSpecs, buildPlanCoordinatorPrompt, buildPlanExecutionPrompt, planWithStatus } from '../planBridge'
import type { PlanEvent } from '../contracts'

const samplePlan: PlanEvent = {
  type: 'plan.event',
  id: 'plan-1',
  sessionId: 'session-1',
  createdAt: '2026-06-11T10:00:00.000Z',
  title: '提炼内容并写入 Obsidian',
  status: 'proposed',
  detail: '先按计划处理',
  prompt: '帮我把这篇文章提炼成方法论，并写入 Obsidian',
  steps: [
    { id: 1, action: 'read_source', tool: 'input_context', requiresApproval: false },
    { id: 4, action: 'write_obsidian', tool: 'obsidian_write', requiresApproval: true },
  ],
}

describe('plan bridge', () => {
  it('builds a job prompt with confirmed plan context', () => {
    const prompt = buildPlanExecutionPrompt(samplePlan)

    expect(prompt).toContain('帮我把这篇文章提炼成方法论')
    expect(prompt).toContain('[已确认任务计划]')
    expect(prompt).toContain('write_obsidian')
    expect(prompt).toContain('必须先等待用户确认')
  })

  it('falls back to detail when prompt is missing', () => {
    const { prompt: _prompt, ...withoutPrompt } = samplePlan
    const prompt = buildPlanExecutionPrompt(withoutPrompt)

    expect(prompt.startsWith('先按计划处理')).toBe(true)
    expect(prompt).toContain('[已确认任务计划]')
  })

  it('updates plan status while preserving id', () => {
    const accepted = planWithStatus(samplePlan, 'accepted')

    expect(accepted.id).toBe('plan-1')
    expect(accepted.status).toBe('accepted')
  })

  it('builds child job specs with approval gating', () => {
    const specs = buildPlanChildJobSpecs(samplePlan)

    expect(specs).toHaveLength(2)
    expect(specs[0]?.autoStart).toBe(true)
    expect(specs[1]?.autoStart).toBe(false)
    expect(specs[1]?.prompt).toContain('write_obsidian')
  })

  it('builds coordinator prompt for parent job', () => {
    const prompt = buildPlanCoordinatorPrompt(samplePlan)

    expect(prompt).toContain('[计划协调任务]')
    expect(prompt).toContain('write_obsidian')
  })
})
