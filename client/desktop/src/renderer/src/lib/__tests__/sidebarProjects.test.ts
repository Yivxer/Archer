import { describe, expect, it, vi } from 'vitest'
import {
  addSessionToProject,
  addThreadToProject,
  buildSidebarTaskGroups,
  buildSidebarThreadGroups,
  createSidebarProject,
  deleteSidebarProject,
  normalizeProjectRecords,
  readSidebarProjects,
  removeSessionFromProject,
  removeThreadFromProject,
  renameSidebarProject,
  sessionsForProject,
  threadsForProject,
  SIDEBAR_PROJECTS_STORAGE_KEY,
  writeSidebarProjects,
  type ProjectRecord,
} from '../sidebarProjects'
import type { ConversationThread, SessionItem } from '../../types'

function memoryStorage(seed: Record<string, string> = {}) {
  const store = new Map(Object.entries(seed))
  return {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, value)
    }),
  }
}

const sessions: SessionItem[] = [
  { id: 's1', title: '六月复盘', date: '今天', turns: 4, tone: 'writer' },
  { id: 's2', title: '读书笔记', date: '昨天', turns: 8, tone: 'reader' },
  { id: 's3', title: '训练计划', date: '本周', turns: 2, tone: 'coach' },
]

describe('sidebarProjects', () => {
  it('falls back to an empty project list when stored data is invalid', () => {
    const storage = memoryStorage({ [SIDEBAR_PROJECTS_STORAGE_KEY]: '{bad json' })

    expect(readSidebarProjects(storage)).toEqual([])
  })

  it('normalizes project records and removes unusable entries', () => {
    expect(normalizeProjectRecords([
      { id: 'p1', name: ' 月度复盘 ', threadIds: ['t1', 't1', '', 3], sessionIds: ['s1', 's1', '', 3] },
      { id: 'p1', name: '重复项目', sessionIds: ['s2'] },
      { id: '', name: '无 id' },
      { id: 'p2', name: '读书', sessionIds: ['s2'] },
    ])).toEqual([
      { id: 'p1', name: '月度复盘', createdAt: '', updatedAt: '', summary: '', notes: '', threadIds: ['t1'], sessionIds: ['s1'] },
      { id: 'p2', name: '读书', createdAt: '', updatedAt: '', summary: '', notes: '', threadIds: [], sessionIds: ['s2'] },
    ])
  })

  it('creates, renames, deletes, and persists local projects', () => {
    const now = new Date('2026-07-01T12:00:00.000Z')
    const projects = createSidebarProject([], '月度复盘', now)
    const renamed = renameSidebarProject(projects, projects[0].id, '六月复盘', now)
    const storage = memoryStorage()

    writeSidebarProjects(renamed, storage)

    expect(renamed[0]).toMatchObject({
      name: '六月复盘',
      createdAt: now.toISOString(),
      updatedAt: now.toISOString(),
      threadIds: [],
      sessionIds: [],
    })
    expect(storage.setItem).toHaveBeenCalledWith(SIDEBAR_PROJECTS_STORAGE_KEY, JSON.stringify(normalizeProjectRecords(renamed)))
    expect(deleteSidebarProject(renamed, renamed[0].id)).toEqual([])
  })

  it('moves assigned sessions out of the default task list', () => {
    const project: ProjectRecord = {
      id: 'p1',
      name: '读书',
      createdAt: '',
      updatedAt: '',
      threadIds: [],
      sessionIds: ['s2'],
    }

    const groups = buildSidebarTaskGroups(sessions, [project])

    expect(groups.projectSessionIds.has('s2')).toBe(true)
    expect(groups.unassignedSessions.map((session) => session.id)).toEqual(['s1', 's3'])
    expect(groups.unassignedThreads.map((thread) => thread.title)).toEqual(['六月复盘', '训练计划'])
    expect(sessionsForProject(sessions, project).map((session) => session.id)).toEqual(['s2'])
  })

  it('uses persisted conversation threads before legacy title grouping', () => {
    const threadedSessions: SessionItem[] = [
      { id: 's1', threadId: 't1', title: '旧标题 A', date: '20260702', turns: 2, tone: 'saved' },
      { id: 's2', threadId: 't1', title: '旧标题 B', date: '20260701', turns: 4, tone: 'saved' },
      { id: 's3', title: '无归属旧会话', date: '20260701', turns: 1, tone: 'saved' },
    ]
    const threads: ConversationThread[] = [
      { id: 't1', title: '持续话题', summary: '线程摘要', createdAt: '', updatedAt: '', sessionIds: ['s1', 's2'] },
    ]
    const project: ProjectRecord = {
      id: 'p1',
      name: '项目',
      createdAt: '',
      updatedAt: '',
      threadIds: ['t1'],
      sessionIds: [],
    }

    const grouped = buildSidebarTaskGroups(threadedSessions, [project], threads)

    expect(grouped.projectThreadIds.has('t1')).toBe(true)
    expect(grouped.unassignedThreads.map((thread) => thread.title)).toEqual(['无归属旧会话'])
    expect(threadsForProject(threads, threadedSessions, project)[0].title).toBe('持续话题')
  })

  it('groups repeated saved sessions into one sidebar topic row', () => {
    const repeatedSessions: SessionItem[] = [
      { id: 's3', title: '上传文章到枫弋札记', date: '20260702', turns: 2, tone: 'saved' },
      { id: 's2', title: ' 上传文章到枫弋札记 ', date: '20260701', turns: 4, tone: 'saved' },
      { id: 's1', title: '写作大纲', date: '20260701', turns: 3, tone: 'saved' },
    ]

    const threads = buildSidebarThreadGroups(repeatedSessions)

    expect(threads).toHaveLength(2)
    expect(threads[0]).toMatchObject({
      title: '上传文章到枫弋札记',
      date: '20260702',
      sessionIds: ['s3', 's2'],
      latestSession: repeatedSessions[0],
    })
    expect(threads[1].sessionIds).toEqual(['s1'])
  })

  it('adds and removes a session assignment without duplicates', () => {
    const now = new Date('2026-07-01T12:00:00.000Z')
    const projects: ProjectRecord[] = [{ id: 'p1', name: '读书', createdAt: '', updatedAt: '', threadIds: [], sessionIds: [] }]

    const once = addSessionToProject(projects, 'p1', 's2', now)
    const twice = addSessionToProject(once, 'p1', 's2', now)
    const removed = removeSessionFromProject(twice, 'p1', 's2', now)

    expect(twice[0].sessionIds).toEqual(['s2'])
    expect(removed[0].sessionIds).toEqual([])
  })

  it('adds and removes a thread assignment without duplicates', () => {
    const now = new Date('2026-07-01T12:00:00.000Z')
    const projects: ProjectRecord[] = [{ id: 'p1', name: '读书', createdAt: '', updatedAt: '', threadIds: [], sessionIds: [] }]

    const once = addThreadToProject(projects, 'p1', 't1', now)
    const twice = addThreadToProject(once, 'p1', 't1', now)
    const removed = removeThreadFromProject(twice, 'p1', 't1', now)

    expect(twice[0].threadIds).toEqual(['t1'])
    expect(removed[0].threadIds).toEqual([])
  })
})
