import type { ConversationThread, SessionItem } from '../types'

export const SIDEBAR_PROJECTS_STORAGE_KEY = 'archer-sidebar-projects-v1'

export type ProjectRecord = {
  id: string
  name: string
  createdAt: string
  updatedAt: string
  summary?: string
  notes?: string
  threadIds: string[]
  sessionIds: string[]
}

export type SidebarTaskGroups = {
  unassignedSessions: SessionItem[]
  unassignedThreads: SidebarThreadGroup[]
  projectThreadIds: Set<string>
  projectSessionIds: Set<string>
}

export type SidebarThreadGroup = {
  id: string
  title: string
  date: string
  sessions: SessionItem[]
  sessionIds: string[]
  latestSession: SessionItem
  summary?: string
}

export function readSidebarProjects(storage: Pick<Storage, 'getItem'> = window.localStorage): ProjectRecord[] {
  try {
    return normalizeProjectRecords(JSON.parse(storage.getItem(SIDEBAR_PROJECTS_STORAGE_KEY) || '[]'))
  } catch {
    return []
  }
}

export function writeSidebarProjects(
  projects: ProjectRecord[],
  storage: Pick<Storage, 'setItem'> = window.localStorage,
): ProjectRecord[] {
  const normalized = normalizeProjectRecords(projects)
  storage.setItem(SIDEBAR_PROJECTS_STORAGE_KEY, JSON.stringify(normalized))
  return normalized
}

export function createSidebarProject(projects: ProjectRecord[], name: string, now = new Date()): ProjectRecord[] {
  const cleanName = name.trim() || nextProjectName(projects)
  const timestamp = now.toISOString()
  return [
    ...projects,
    {
      id: `project-${now.getTime()}-${Math.random().toString(36).slice(2, 8)}`,
      name: cleanName,
      createdAt: timestamp,
      updatedAt: timestamp,
      threadIds: [],
      sessionIds: [],
    },
  ]
}

export function renameSidebarProject(
  projects: ProjectRecord[],
  projectId: string,
  name: string,
  now = new Date(),
): ProjectRecord[] {
  const cleanName = name.trim()
  if (!cleanName) return projects
  return projects.map((project) => (
    project.id === projectId
      ? { ...project, name: cleanName, updatedAt: now.toISOString() }
      : project
  ))
}

export function deleteSidebarProject(projects: ProjectRecord[], projectId: string): ProjectRecord[] {
  return projects.filter((project) => project.id !== projectId)
}

export function updateSidebarProjectDetails(
  projects: ProjectRecord[],
  projectId: string,
  patch: { summary?: string; notes?: string },
  now = new Date(),
): ProjectRecord[] {
  return projects.map((project) => (
    project.id === projectId
      ? {
          ...project,
          summary: typeof patch.summary === 'string' ? patch.summary.slice(0, 500) : project.summary,
          notes: typeof patch.notes === 'string' ? patch.notes.slice(0, 1000) : project.notes,
          updatedAt: now.toISOString(),
        }
      : project
  ))
}

export function addSessionToProject(
  projects: ProjectRecord[],
  projectId: string,
  sessionId: string,
  now = new Date(),
): ProjectRecord[] {
  return projects.map((project) => {
    if (project.id !== projectId) return project
    if (project.sessionIds.includes(sessionId)) return project
    return {
      ...project,
      sessionIds: [...project.sessionIds, sessionId],
      updatedAt: now.toISOString(),
    }
  })
}

export function addThreadToProject(
  projects: ProjectRecord[],
  projectId: string,
  threadId: string,
  now = new Date(),
): ProjectRecord[] {
  return projects.map((project) => {
    if (project.id !== projectId) return project
    if (project.threadIds.includes(threadId)) return project
    return {
      ...project,
      threadIds: [...project.threadIds, threadId],
      updatedAt: now.toISOString(),
    }
  })
}

export function removeSessionFromProject(
  projects: ProjectRecord[],
  projectId: string,
  sessionId: string,
  now = new Date(),
): ProjectRecord[] {
  return projects.map((project) => (
    project.id === projectId
      ? {
          ...project,
          sessionIds: project.sessionIds.filter((id) => id !== sessionId),
          updatedAt: now.toISOString(),
        }
      : project
  ))
}

export function removeThreadFromProject(
  projects: ProjectRecord[],
  projectId: string,
  threadId: string,
  now = new Date(),
): ProjectRecord[] {
  return projects.map((project) => (
    project.id === projectId
      ? {
          ...project,
          threadIds: project.threadIds.filter((id) => id !== threadId),
          updatedAt: now.toISOString(),
        }
      : project
  ))
}

export function buildSidebarTaskGroups(
  sessions: SessionItem[],
  projects: ProjectRecord[],
  threads: ConversationThread[] = [],
): SidebarTaskGroups {
  const projectThreadIds = new Set(projects.flatMap((project) => project.threadIds))
  const projectSessionIds = new Set(projects.flatMap((project) => project.sessionIds))
  const threadGroups = buildGroupsFromThreads(threads, sessions)
    .filter((thread) => !projectThreadIds.has(thread.id))
  const threadedSessionIds = new Set(threadGroups.flatMap((thread) => thread.sessionIds))
  const unassignedSessions = sessions.filter((session) => {
    if (projectSessionIds.has(session.id)) return false
    if (session.threadId && projectThreadIds.has(session.threadId)) return false
    return !threadedSessionIds.has(session.id)
  })
  return {
    projectThreadIds,
    projectSessionIds,
    unassignedSessions,
    unassignedThreads: [
      ...threadGroups,
      ...buildSidebarThreadGroups(unassignedSessions),
    ],
  }
}

export function buildSidebarThreadGroups(sessions: SessionItem[]): SidebarThreadGroup[] {
  const groups = new Map<string, SidebarThreadGroup>()
  sessions.forEach((session) => {
    const title = normalizeThreadTitle(session.title || session.preview || session.id)
    const key = title.toLowerCase()
    const current = groups.get(key)
    if (!current) {
      groups.set(key, {
        id: `thread-${key}`,
        title,
        date: session.date,
        sessions: [session],
        sessionIds: [session.id],
        latestSession: session,
      })
      return
    }
    current.sessions.push(session)
    current.sessionIds.push(session.id)
  })
  return Array.from(groups.values())
}

export function threadsForProject(
  threads: ConversationThread[],
  sessions: SessionItem[],
  project: ProjectRecord | undefined,
): SidebarThreadGroup[] {
  if (!project) return []
  const threadMap = new Map(buildGroupsFromThreads(threads, sessions).map((thread) => [thread.id, thread]))
  return project.threadIds.map((id) => threadMap.get(id)).filter((thread): thread is SidebarThreadGroup => Boolean(thread))
}

export function sessionsForProject(sessions: SessionItem[], project: ProjectRecord | undefined): SessionItem[] {
  if (!project) return []
  const sessionMap = new Map(sessions.map((session) => [session.id, session]))
  return project.sessionIds
    .map((id) => sessionMap.get(id))
    .filter((session): session is SessionItem => Boolean(session))
}

export function normalizeProjectRecords(value: unknown): ProjectRecord[] {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  return value.flatMap((item): ProjectRecord[] => {
    if (!item || typeof item !== 'object') return []
    const raw = item as Partial<ProjectRecord>
    const id = typeof raw.id === 'string' ? raw.id.trim() : ''
    const name = typeof raw.name === 'string' ? raw.name.trim() : ''
    if (!id || !name || seen.has(id)) return []
    seen.add(id)
    return [{
      id,
      name,
      createdAt: typeof raw.createdAt === 'string' ? raw.createdAt : '',
      updatedAt: typeof raw.updatedAt === 'string' ? raw.updatedAt : '',
      summary: typeof raw.summary === 'string' ? raw.summary : '',
      notes: typeof raw.notes === 'string' ? raw.notes : '',
      threadIds: Array.isArray(raw.threadIds)
        ? Array.from(new Set(raw.threadIds.filter((threadId): threadId is string => typeof threadId === 'string' && Boolean(threadId.trim()))))
        : [],
      sessionIds: Array.isArray(raw.sessionIds)
        ? Array.from(new Set(raw.sessionIds.filter((sessionId): sessionId is string => typeof sessionId === 'string' && Boolean(sessionId.trim()))))
        : [],
    }]
  })
}

function nextProjectName(projects: ProjectRecord[]): string {
  return `新项目 ${projects.length + 1}`
}

function normalizeThreadTitle(title: string): string {
  return title
    .replace(/\s+/g, ' ')
    .replace(/\s*\/Users\/.*$/u, '')
    .trim()
    .slice(0, 42) || '未命名话题'
}

function buildGroupsFromThreads(threads: ConversationThread[], sessions: SessionItem[]): SidebarThreadGroup[] {
  const sessionMap = new Map(sessions.map((session) => [session.id, session]))
  return threads.flatMap((thread) => {
    if (thread.archived) return []
    const threadSessions = thread.sessionIds
      .map((id) => sessionMap.get(id))
      .filter((session): session is SessionItem => Boolean(session))
    const linkedSessions = sessions.filter((session) => session.threadId === thread.id && !threadSessions.some((item) => item.id === session.id))
    const allSessions = [...threadSessions, ...linkedSessions]
    const latestSession = allSessions[0]
    if (!latestSession) return []
    return [{
      id: thread.id,
      title: normalizeThreadTitle(thread.title || latestSession.title),
      date: latestSession.date,
      sessions: allSessions,
      sessionIds: allSessions.map((session) => session.id),
      latestSession,
      summary: thread.summary,
    }]
  })
}
