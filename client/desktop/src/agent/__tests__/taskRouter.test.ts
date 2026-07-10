import { describe, expect, it } from 'vitest'
import type { PlanEvent } from '../contracts'
import { classifyHugoIntent, isForegroundOnlyWritingFeedbackPlan, isHugoBlogPublishPlan, routeTaskForRuntime } from '../taskRouter'

describe('task router', () => {
  it('keeps short conversational questions in the foreground', () => {
    const route = routeTaskForRuntime({ text: '为什么 Archer 现在还不能自动发布博客？' })

    expect(route.mode).toBe('foreground')
    expect(route.reason).toBe('short conversational request')
  })

  it('keeps large requests in foreground so Python orchestrator owns routing', () => {
    const route = routeTaskForRuntime({
      text: Array.from({ length: 15 }, (_, index) => `第 ${index + 1} 步：继续优化 runtime`).join('\n'),
    })

    expect(route.mode).toBe('foreground')
    expect(route.reason).toBe('python orchestrator owns routing')
    expect(route.timeoutSeconds).toBe(300)
  })

  it('keeps implementation-style requests with paths in foreground for Python orchestration', () => {
    const route = routeTaskForRuntime({
      text: '继续优化昨天的内容，修改 client/desktop/src/renderer/src/pages/ChatPage.tsx 并跑测试',
    })

    expect(route.mode).toBe('foreground')
    expect(route.reason).toBe('python orchestrator owns routing')
  })

  it('keeps attached-file implementation requests in foreground for Python orchestration', () => {
    const route = routeTaskForRuntime({
      text: '按照计划继续实现这部分能力',
      fileCount: 1,
    })

    expect(route.mode).toBe('foreground')
    expect(route.reason).toBe('python orchestrator owns routing')
  })

  it('keeps hugo blog publish with attachment in the foreground', () => {
    const route = routeTaskForRuntime({
      text: '部署这篇文章到枫弋札记上',
      fileCount: 1,
    })

    expect(classifyHugoIntent('部署这篇文章到枫弋札记上')).toBe('execute_publish')
    expect(route.mode).toBe('foreground')
    expect(route.reason).toBe('hugo blog publish uses attachments and tool stream')
  })

  it('keeps local markdown article publish requests in the foreground', () => {
    const route = routeTaskForRuntime({
      text: '/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/个人知识管理系统/当训练变成习惯以后，人会对疲劳变得迟钝.md部署这一篇文章',
    })

    expect(classifyHugoIntent('/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/文章.md部署这一篇文章')).toBe('execute_publish')
    expect(route.mode).toBe('foreground')
    expect(route.reason).toBe('hugo blog publish uses attachments and tool stream')
  })

  it('classifies Hugo asset capability questions without publishing', () => {
    const text = '枫弋札记里好像没有办法部署图片你这边可以部署图片么？'
    const route = routeTaskForRuntime({ text })

    expect(classifyHugoIntent(text)).toBe('ask_capability')
    expect(route.reason).not.toBe('hugo blog publish uses attachments and tool stream')
  })

  it('classifies read-only review requests with past publish mentions without publishing', () => {
    const text = '我让 Codex 帮我部署了，/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/读书笔记/不存在另一半的灵魂.md，你可以看看这一篇读后感如何'
    const route = routeTaskForRuntime({ text })

    expect(classifyHugoIntent(text)).toBe('content_review')
    expect(route.reason).not.toBe('hugo blog publish uses attachments and tool stream')
  })

  it('keeps approval-first Obsidian writes in the foreground', () => {
    const route = routeTaskForRuntime({
      text: '帮我把这篇文章提炼成方法论，并写入 Obsidian',
      fileCount: 1,
    })

    expect(route.mode).toBe('foreground')
    expect(route.reason).toBe('approval-first task')
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
