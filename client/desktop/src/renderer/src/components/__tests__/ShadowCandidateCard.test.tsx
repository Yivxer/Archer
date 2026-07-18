import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ShadowCandidateCard } from '../ShadowCandidateCard'

const item = {
  id: 42,
  eventType: 'initiative_due',
  kind: 'thread_resume',
  title: '继续 Archer 的上下文验收',
  message: '上次停在 J8 的真实连续性测试。',
  delivered: false,
  decisionTrace: {},
  createdAt: '2026-07-18T12:00:00',
  feedback: '',
  archivedAt: null,
}

describe('ShadowCandidateCard', () => {
  it('shows one clearly labelled shadow candidate and all review actions', () => {
    const html = renderToStaticMarkup(
      <ShadowCandidateCard
        item={item}
        busy=""
        notice=""
        onAcknowledge={vi.fn()}
        onTooFrequent={vi.fn()}
        onMute={vi.fn()}
        onViewAll={vi.fn()}
      />,
    )

    expect(html).toContain('Archer 注意到')
    expect(html).toContain('不代表已经理解正确')
    expect(html).toContain('认可')
    expect(html).toContain('太频繁')
    expect(html).toContain('静音')
    expect(html).toContain('查看全部')
    expect(html).not.toContain('assistant')
    expect(html).not.toContain('notification')
  })
})
