import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, expect, it, vi } from 'vitest'
const api = vi.hoisted(() => ({ listLocalSessions: vi.fn(), listLocalThreads: vi.fn() }))
vi.mock('../adapters/conversationAdapter', () => api)
import { ProjectsPage } from './ProjectsPage'
import { ReviewPage } from './ReviewPage'
import { mockArcher } from '../adapters/mockArcher'
import { loadSessionList, resetSessionStore } from '../lib/sessionStore'
import { loadThreadList, resetThreadStore } from '../lib/threadStore'
const session = { id: 'saved', threadId: 'topic', title: 'Synthetic session', date: '20261002', turns: 2, tone: '' }
const thread = { id: 'topic', title: 'Synthetic topic', summary: 'Confirmed context', sessionIds: ['saved'], createdAt: '', updatedAt: '' }
function project() {
  return renderToStaticMarkup(<ProjectsPage projects={[{ id: 'project', name: 'Synthetic project', threadIds: ['topic'], sessionIds: [], createdAt: '', updatedAt: '' }]} selectedProjectId="project" onProjectsChange={() => {}} onProjectSelect={() => {}} onOpenSession={() => {}} onCreateProject={() => {}} />)
}
function review(connected = true) {
  return renderToStaticMarkup(<ReviewPage data={mockArcher} connected={connected} onRefresh={async () => {}} onOpenSession={() => {}} onNavigate={() => {}} />)
}
function reviewContinue(connected = true) {
  return renderToStaticMarkup(<ReviewPage data={mockArcher} connected={connected} onRefresh={async () => {}} onOpenSession={() => {}} onContinueThread={() => {}} onNavigate={() => {}} />)
}
beforeEach(() => {
  vi.resetAllMocks(); resetSessionStore(); resetThreadStore()
  api.listLocalSessions.mockResolvedValue([session]); api.listLocalThreads.mockResolvedValue([thread])
})
it('project and review render the same independent server lists', async () => {
  await Promise.all([loadSessionList(), loadThreadList()])
  expect(project()).toContain('Synthetic topic')
  expect(review()).toContain('Synthetic session')
})
it('failed refresh preserves readable project and review content with an error', async () => {
  await Promise.all([loadSessionList(), loadThreadList()])
  api.listLocalSessions.mockRejectedValueOnce(new Error('Synthetic offline'))
  await loadSessionList()
  expect(project()).toContain('Synthetic topic')
  expect(project()).toContain('Synthetic offline')
  expect(review()).toContain('Synthetic session')
  expect(review()).toContain('role="alert"')
})
it('unloaded review does not claim a successful empty result and disconnected refresh is disabled', () => {
  expect(review(false)).toContain('会话尚未读取成功')
  expect(review(false)).toMatch(/<button[^>]*disabled=""[^>]*>刷新/)
  expect(review(false)).not.toContain('无匹配会话')
})
it('offers continue for a well-formed threadId missing from the live index', async () => {
  api.listLocalSessions.mockResolvedValue([{ ...session, id: '20260101_000000', threadId: 'thread-missing', title: 'Synthetic session' }])
  api.listLocalThreads.mockResolvedValue([])
  await Promise.all([loadSessionList(), loadThreadList()])
  const html = reviewContinue()
  expect(html).toContain('在新会话继续这个话题')
  expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>在新会话继续这个话题/)
})
it('keeps continue for a known thread and hides it for an invalid id', async () => {
  await Promise.all([loadSessionList(), loadThreadList()])
  expect(reviewContinue()).toContain('在新会话继续这个话题')
  resetSessionStore()
  api.listLocalSessions.mockResolvedValue([{ ...session, threadId: '../invalid' }])
  await loadSessionList()
  expect(reviewContinue()).not.toContain('在新会话继续这个话题')
  resetSessionStore()
  api.listLocalSessions.mockResolvedValue([{ ...session, threadId: undefined }])
  await loadSessionList()
  expect(reviewContinue()).not.toContain('在新会话继续这个话题')
})
