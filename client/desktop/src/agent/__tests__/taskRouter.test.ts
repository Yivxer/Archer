import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { PlanEvent } from '../contracts'
import { isForegroundOnlyWritingFeedbackPlan, isHugoBlogPublishPlan } from '../taskRouter'

describe('task router', () => {
  it('does not route messages in Desktop before the Python stream', () => {
    const chatPage = readFileSync(resolve('src/renderer/src/pages/ChatPage.tsx'), 'utf8')

    expect(chatPage).not.toContain('routeTaskForRuntime')
  })

  it('detects attachment blog publish plans from surrounding conversation context', () => {
    const plan: PlanEvent = {
      type: 'plan.event',
      id: 'plan-1',
      sessionId: 's1',
      createdAt: '2026-07-04T00:00:00Z',
      title: '我在附件里加了，你看看帮我重新部署一下',
      status: 'proposed',
      detail: '先按计划处理；涉及写入、保存或发布的步骤需要用户确认。',
      prompt: '我在附件里加了，你看看帮我重新部署一下，格式记得调整调整',
      steps: [
        { id: 1, action: 'inspect_context', tool: 'project_context', requiresApproval: false },
        { id: 2, action: 'draft_plan', tool: 'llm', requiresApproval: false },
        { id: 3, action: 'request_approval', tool: 'approval', requiresApproval: true },
      ],
    }

    expect(isHugoBlogPublishPlan(plan, '当前话题：部署枫弋札记，补全博客正文')).toBe(true)
  })

  it('does not classify ordinary approval plans as Hugo publish plans', () => {
    const plan: PlanEvent = {
      type: 'plan.event',
      id: 'plan-2',
      sessionId: 's1',
      createdAt: '2026-07-04T00:00:00Z',
      title: '整理训练计划',
      status: 'proposed',
      detail: '确认后写入 Obsidian。',
      prompt: '把训练计划整理成文档',
      steps: [
        { id: 1, action: 'draft_plan', tool: 'llm', requiresApproval: false },
        { id: 2, action: 'request_approval', tool: 'approval', requiresApproval: true },
      ],
    }

    expect(isHugoBlogPublishPlan(plan, '当前话题：训练计划')).toBe(false)
  })

  it('keeps read-only writing feedback plans out of background execution', () => {
    const plan: PlanEvent = {
      type: 'plan.event',
      id: 'plan-3',
      sessionId: 's1',
      createdAt: '2026-07-06T00:00:00Z',
      title: '提炼内容并写入 Obsidian',
      status: 'proposed',
      detail: '先按计划处理；涉及写入、保存或发布的步骤需要用户确认。',
      prompt: '/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/AI 算不出命.md 这是初稿，AI 味太重，先不要更改原文件，说说你的想法',
      steps: [
        { id: 1, action: 'read_source', tool: 'input_context', requiresApproval: false },
        { id: 2, action: 'summarize', tool: 'llm', requiresApproval: false },
        { id: 3, action: 'format_note', tool: 'llm', requiresApproval: false },
        { id: 4, action: 'write_obsidian', tool: 'obsidian_write', requiresApproval: true },
      ],
    }

    expect(isForegroundOnlyWritingFeedbackPlan(plan)).toBe(true)
  })

  it('keeps article review plans with local Obsidian paths out of background execution', () => {
    const plan: PlanEvent = {
      type: 'plan.event',
      id: 'plan-4',
      sessionId: 's1',
      createdAt: '2026-07-06T00:00:00Z',
      title: '提炼内容并写入 Obsidian',
      status: 'proposed',
      detail: '先按计划处理；涉及写入、保存或发布的步骤需要用户确认。',
      prompt: '/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/AI 算不出命，但能照见你.md这厮最后的精修版本，你觉得怎么样？如果要调整的话还有哪些可以调整的地方？',
      steps: [
        { id: 1, action: 'read_source', tool: 'input_context', requiresApproval: false },
        { id: 2, action: 'summarize', tool: 'llm', requiresApproval: false },
        { id: 3, action: 'format_note', tool: 'llm', requiresApproval: false },
        { id: 4, action: 'write_obsidian', tool: 'obsidian_write', requiresApproval: true },
      ],
    }

    expect(isForegroundOnlyWritingFeedbackPlan(plan)).toBe(true)
  })
})
