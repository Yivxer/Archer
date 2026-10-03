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
