import { describe, expect, it } from 'vitest'
import { routeTaskForRuntime } from '../taskRouter'

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

    expect(route.mode).toBe('foreground')
    expect(route.reason).toBe('hugo blog publish uses attachments and tool stream')
  })

  it('keeps local markdown article publish requests in the foreground', () => {
    const route = routeTaskForRuntime({
      text: '/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/个人知识管理系统/当训练变成习惯以后，人会对疲劳变得迟钝.md部署这一篇文章',
    })

    expect(route.mode).toBe('foreground')
    expect(route.reason).toBe('hugo blog publish uses attachments and tool stream')
  })

  it('keeps approval-first Obsidian writes in the foreground', () => {
    const route = routeTaskForRuntime({
      text: '帮我把这篇文章提炼成方法论，并写入 Obsidian',
      fileCount: 1,
    })

    expect(route.mode).toBe('foreground')
    expect(route.reason).toBe('approval-first task')
  })
})
