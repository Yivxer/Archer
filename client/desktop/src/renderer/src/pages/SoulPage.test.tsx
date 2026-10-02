import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SoulFiles } from '../types'

const api = vi.hoisted(() => ({
  fetchSoulProfile: vi.fn(),
  fetchSoulFiles: vi.fn(),
  fetchVaultReflections: vi.fn(),
}))
vi.mock('../adapters/soulAdapter', () => api)

import { mockArcher } from '../adapters/mockArcher'
import { loadAllSoul, resetSoulStore } from '../lib/soulStore'
import { SoulPage } from './SoulPage'

function render(connected: boolean): string {
  return renderToStaticMarkup(<SoulPage connected={connected} hypotheses={[]} journalReview={mockArcher.journalReview} periodReviews={mockArcher.periodReviews} />)
}

describe('SoulPage domain state', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    resetSoulStore()
    api.fetchSoulProfile.mockResolvedValue({ empty: false, sections: [{ id: 'sample', label: '合成档案', items: ['来自当前服务器'] }] })
    api.fetchSoulFiles.mockResolvedValue({ 'SOUL.md': '# 当前服务器文件' } as SoulFiles)
    api.fetchVaultReflections.mockResolvedValue({ ok: true, reflections: [] })
  })

  it('renders the loaded store without a compatibility profile fallback', async () => {
    await loadAllSoul()
    const html = render(true)
    expect(html).toContain('来自当前服务器')
    expect(html).toContain('当前服务器文件')
    expect(html).not.toContain('暂无结构化 Soul Profile')
  })

  it('shows connection guidance before a domain has been loaded', () => {
    const html = render(false)
    expect(html).toContain('连接本地 Archer 后加载档案')
    expect(html).toContain('档案文件尚未加载')
    expect(html).not.toContain('暂无结构化 Soul Profile')
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*title="从 JSON 文件导入 Soul 数据"/)
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*title="将 Soul 与 Memory 导出为 JSON \+ Markdown"/)
  })

  it('distinguishes a failed read from a successfully empty profile', async () => {
    api.fetchSoulProfile.mockRejectedValueOnce(new Error('档案读取失败'))
    await loadAllSoul()
    const html = render(true)
    expect(html).toContain('role="alert"')
    expect(html).toContain('档案读取失败')
    expect(html).not.toContain('暂无结构化 Soul Profile')
  })

  it('retains readable last-known content while exposing a refresh failure', async () => {
    await loadAllSoul()
    api.fetchSoulFiles.mockRejectedValueOnce(new Error('刷新失败'))
    await loadAllSoul()
    const html = render(true)
    expect(html).toContain('当前服务器文件')
    expect(html).toContain('来自当前服务器')
    expect(html).toContain('刷新失败')
  })

  it('only shows an empty profile after a successful empty server response', async () => {
    api.fetchSoulProfile.mockResolvedValueOnce({ empty: true, sections: [] })
    await loadAllSoul()
    expect(render(true)).toContain('暂无结构化 Soul Profile')
  })
})
