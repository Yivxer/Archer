import { describe, expect, it } from 'vitest'
import { routeTaskForRuntime } from '../taskRouter'

describe('task router', () => {
  it('keeps short conversational questions in the foreground', () => {
    const route = routeTaskForRuntime({ text: '为什么 Archer 现在还不能自动发布博客？' })

    expect(route.mode).toBe('foreground')
    expect(route.reason).toBe('short conversational request')
  })

  it('routes large requests to background jobs', () => {
    const route = routeTaskForRuntime({
      text: Array.from({ length: 15 }, (_, index) => `第 ${index + 1} 步：继续优化 runtime`).join('\n'),
    })

    expect(route.mode).toBe('background')
    expect(route.reason).toBe('large request')
    expect(route.timeoutSeconds).toBe(600)
  })

  it('routes implementation-style requests with paths to background jobs', () => {
    const route = routeTaskForRuntime({
      text: '继续优化昨天的内容，修改 client/desktop/src/renderer/src/pages/ChatPage.tsx 并跑测试',
    })

    expect(route.mode).toBe('background')
    expect(route.reason).toBe('implementation-style request')
  })

  it('routes attached-file implementation requests to background jobs', () => {
    const route = routeTaskForRuntime({
      text: '按照计划继续实现这部分能力',
      fileCount: 1,
    })

    expect(route.mode).toBe('background')
  })
})
