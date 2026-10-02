import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ fetchMemoryItems: vi.fn(), fetchMemoryStats: vi.fn(), fetchMemoryGroups: vi.fn() }))
vi.mock('../adapters/memoryAdapter', () => api)
import { loadAllMemory, resetMemoryStore } from '../lib/memoryStore'
import { MemoryPage } from './MemoryPage'

const pending = { id: 1, status: 'pending', type: 'preference', content: '仅合成样本中的待确认记忆', confidence: '0.8', source: 'test' }
function render(connected = true) { return renderToStaticMarkup(<MemoryPage connected={connected} />) }

describe('MemoryPage domain projection', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    resetMemoryStore()
    api.fetchMemoryItems.mockResolvedValue([pending])
    api.fetchMemoryStats.mockResolvedValue({ activeCount: 2, pendingCount: 1, dbPath: '/synthetic/memory.db', contradictions: 0, stale: 0 })
    api.fetchMemoryGroups.mockResolvedValue({})
  })
  it('distinguishes an unloaded domain from a successful empty result', async () => {
    expect(render()).toContain('等待记忆加载')
    expect(render()).not.toContain('暂无待确认记忆')
    api.fetchMemoryItems.mockResolvedValueOnce([])
    await loadAllMemory()
    expect(render()).toContain('暂无待确认记忆')
  })
  it('renders authoritative pending content and stats', async () => {
    await loadAllMemory()
    const html = render()
    expect(html).toContain(pending.content)
    expect(html).toContain('2 条')
    expect(html).toContain('1 待确认')
  })
  it('retains readable cached content when a refresh fails', async () => {
    await loadAllMemory()
    api.fetchMemoryGroups.mockRejectedValueOnce(new Error('合成读取故障'))
    await loadAllMemory({ force: true })
    const html = render()
    expect(html).toContain(pending.content)
    expect(html).toContain('role="alert"')
    expect(html).toContain('合成读取故障')
  })
  it('disconnected pages retain content and prevent writes or refresh', async () => {
    await loadAllMemory()
    const html = render(false)
    expect(html).toContain(pending.content)
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>刷新记忆/)
    expect(html).not.toContain('全部确认')
    expect(html).not.toContain('>确认</button>')
    expect(html).toContain('连接后可更新记忆')
  })
  it('failed initial loading stays visible and permits retry', async () => {
    api.fetchMemoryItems.mockRejectedValueOnce(new Error('合成读取失败'))
    await loadAllMemory()
    const html = render()
    expect(html).toContain('合成读取失败')
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>刷新记忆/)
    expect(html).not.toContain('暂无待确认记忆')
  })
})
