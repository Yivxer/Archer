import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { InitiativeShadowItem } from '../types'
import { ThreadClueActions } from './ThreadClueActions'

vi.mock('../lib/initiativeStore', () => ({ transitionThreadClueAction: vi.fn() }))

const item: InitiativeShadowItem = {
  id: 8, kind: 'thread_resume', eventType: 'initiative_due', title: '青禾', message: '待复查',
  decisionTrace: { threadId: 42 }, delivered: false, createdAt: '', feedback: '', archivedAt: null,
}

describe('cue lifecycle controls', () => {
  it('shows four explicit actions for a linked cue', () => {
    const html = renderToStaticMarkup(<ThreadClueActions item={item} />)
    for (const label of ['已完成', '关闭', '忽略', '已过期']) expect(html).toContain(label)
    expect(html).not.toContain('授权')
  })
  it.each([{ ...item, archivedAt: '2026-10-02' }, { ...item, decisionTrace: {} }, { ...item, decisionTrace: { threadId: 'conversation-42' } }, { ...item, decisionTrace: { threadId: true } }])('hides controls without an active numeric cue source', (candidate) => {
    expect(renderToStaticMarkup(<ThreadClueActions item={candidate} />)).toBe('')
  })
  it('disables all actions during another mutation', () => {
    const html = renderToStaticMarkup(<ThreadClueActions item={item} disabled />)
    expect(html.match(/disabled=""/g)).toHaveLength(4)
  })
})
