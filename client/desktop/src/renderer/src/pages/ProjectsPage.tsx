import { useSessionStore } from '../lib/sessionStore'
import { useThreadStore } from '../lib/threadStore'
import React from 'react'
import { Folder, FolderPlus, Plus, Trash2, X } from 'lucide-react'
import { EmptyDetail, SearchBox } from '../components/common'
import {
  addSessionToProject,
  addThreadToProject,
  buildSidebarTaskGroups,
  deleteSidebarProject,
  removeSessionFromProject,
  removeThreadFromProject,
  renameSidebarProject,
  sessionsForProject,
  threadsForProject,
  updateSidebarProjectDetails,
  writeSidebarProjects,
  type ProjectRecord,
} from '../lib/sidebarProjects'
import type { SessionItem } from '../types'

export function ProjectsPage({
  projects,
  selectedProjectId,
  onProjectsChange,
  onProjectSelect,
  onOpenSession,
  onCreateProject,
}: {
  projects: ProjectRecord[]
  selectedProjectId: string
  onProjectsChange: (projects: ProjectRecord[]) => void
  onProjectSelect: (projectId: string) => void
  onOpenSession: (session: SessionItem) => void
  onCreateProject: () => void
}) {
  const sessions = useSessionStore((state) => state.items)
  const threads = useThreadStore((state) => state.items)
  const sessionError = useSessionStore((state) => state.listError)
  const threadError = useThreadStore((state) => state.error)
  const [query, setQuery] = React.useState('')
  const selectedProject = projects.find((project) => project.id === selectedProjectId) ?? projects[0]
  const projectThreads = threadsForProject(threads, sessions, selectedProject)
  const projectSessions = sessionsForProject(sessions, selectedProject)
  const sidebarGroups = buildSidebarTaskGroups(sessions, projects, threads)
  const availableThreads = sidebarGroups.unassignedThreads
  const assignedSessionIds = new Set(selectedProject?.sessionIds ?? [])
  const availableSessions = sessions.filter((session) => !session.threadId && !assignedSessionIds.has(session.id))
  const cleanQuery = query.trim().toLowerCase()
  const visibleAvailableThreads = cleanQuery
    ? availableThreads.filter((thread) => [thread.title, thread.summary, thread.date].filter(Boolean).join(' ').toLowerCase().includes(cleanQuery))
    : availableThreads
  const visibleAvailableSessions = cleanQuery
    ? availableSessions.filter((session) => [session.title, session.preview, session.date, session.tone].filter(Boolean).join(' ').toLowerCase().includes(cleanQuery))
    : availableSessions

  React.useEffect(() => {
    if (!selectedProject && projects[0]) onProjectSelect(projects[0].id)
  }, [selectedProject, projects, onProjectSelect])

  function commitProjects(nextProjects: ProjectRecord[]) {
    onProjectsChange(writeSidebarProjects(nextProjects))
  }

  function renameProject(project: ProjectRecord) {
    const nextName = window.prompt('项目名称', project.name)
    if (nextName === null) return
    commitProjects(renameSidebarProject(projects, project.id, nextName))
  }

  function deleteProject(project: ProjectRecord) {
    if (!window.confirm(`删除项目「${project.name}」？会话不会被删除，只会回到任务列表。`)) return
    const nextProjects = deleteSidebarProject(projects, project.id)
    commitProjects(nextProjects)
    onProjectSelect(nextProjects[0]?.id || '')
  }

  function updateProjectDetails(patch: { summary?: string; notes?: string }) {
    if (!selectedProject) return
    commitProjects(updateSidebarProjectDetails(projects, selectedProject.id, patch))
  }

  function addSession(sessionId: string) {
    if (!selectedProject) return
    commitProjects(addSessionToProject(projects, selectedProject.id, sessionId))
  }

  function addThread(threadId: string) {
    if (!selectedProject) return
    commitProjects(addThreadToProject(projects, selectedProject.id, threadId))
  }

  function removeSession(sessionId: string) {
    if (!selectedProject) return
    commitProjects(removeSessionFromProject(projects, selectedProject.id, sessionId))
  }

  function removeThread(threadId: string) {
    if (!selectedProject) return
    commitProjects(removeThreadFromProject(projects, selectedProject.id, threadId))
  }

  return (
    <div className="split-page projects-page">
      <div className="list-column project-list-column">
        <div className="sessions-head">
          <div>
            <h1>项目</h1>
            <p>本地文件夹</p>
          </div>
          <button className="quiet-button icon-only" type="button" onClick={onCreateProject} title="创建项目" aria-label="创建项目">
            <FolderPlus size={16} />
          </button>
        </div>
        {(sessionError || threadError) && <p role="alert">{sessionError || threadError}</p>}
        {projects.length ? projects.map((project) => (
          <button
            className={`list-row project-row ${selectedProject?.id === project.id ? 'active' : ''}`}
            key={project.id}
            type="button"
            onClick={() => onProjectSelect(project.id)}
          >
            <Folder size={17} />
            <div>
              <strong>{project.name}</strong>
              <span>{project.threadIds.length || project.sessionIds.length} 个话题</span>
            </div>
          </button>
        )) : (
          <div className="empty-inline">暂无项目</div>
        )}
      </div>

      {selectedProject ? (
        <section className="session-detail project-detail">
          <div className="session-detail-head">
            <div className="session-detail-icon">
              <Folder size={18} />
            </div>
            <div>
              <h2>{selectedProject.name}</h2>
              <p>{projectThreads.length || projectSessions.length} 个话题 · 本地项目</p>
            </div>
            <div className="task-actions">
              <button className="quiet-button" type="button" onClick={() => renameProject(selectedProject)}>重命名</button>
              <button className="quiet-button" type="button" onClick={() => deleteProject(selectedProject)}>
                <Trash2 size={14} />
                删除
              </button>
            </div>
          </div>

          <div className="project-section">
            <div className="section-head compact">
              <div>
                <h3>项目记忆</h3>
                <p>本地保存，不写入全局记忆。</p>
              </div>
            </div>
            <label className="project-memory-field">
              <span>摘要</span>
              <textarea
                value={selectedProject.summary || ''}
                onChange={(event) => updateProjectDetails({ summary: event.currentTarget.value })}
                placeholder="这个项目的目标、边界或当前重点"
                rows={3}
              />
            </label>
            <label className="project-memory-field">
              <span>备注</span>
              <textarea
                value={selectedProject.notes || ''}
                onChange={(event) => updateProjectDetails({ notes: event.currentTarget.value })}
                placeholder="临时备注、待办或后续要接住的线索"
                rows={4}
              />
            </label>
          </div>

          <div className="project-section">
            <div className="section-head compact">
              <div>
                <h3>项目话题</h3>
                <p>打开后进入该话题的最新对话。</p>
              </div>
            </div>
            {projectThreads.length ? projectThreads.map((thread) => (
              <div className="project-session-row" key={thread.id}>
                <button type="button" onClick={() => onOpenSession(thread.latestSession)}>
                  <strong>{thread.title}</strong>
                  <span>{thread.summary || `${thread.date} · ${thread.sessions.length} 次`}</span>
                </button>
                <button className="icon-button" type="button" onClick={() => removeThread(thread.id)} title="移出项目" aria-label="移出项目">
                  <X size={15} />
                </button>
              </div>
            )) : projectSessions.length ? projectSessions.map((session) => (
              <div className="project-session-row" key={session.id}>
                <button type="button" onClick={() => onOpenSession(session)}>
                  <strong>{session.title}</strong>
                  <span>{session.date} · {session.turns} 轮</span>
                </button>
                <button className="icon-button" type="button" onClick={() => removeSession(session.id)} title="移出项目" aria-label="移出项目">
                  <X size={15} />
                </button>
              </div>
            )) : (
              <div className="empty-inline">这个项目还没有话题。</div>
            )}
          </div>

          <div className="project-section">
            <div className="section-head compact">
              <div>
                <h3>加入话题</h3>
                <p>从任务列表里挑选话题放进项目。</p>
              </div>
            </div>
            <SearchBox placeholder="搜索可加入的话题" value={query} onChange={setQuery} />
            <div className="project-add-list">
              {visibleAvailableThreads.length ? visibleAvailableThreads.map((thread) => (
                <button className="project-add-row" type="button" key={thread.id} onClick={() => addThread(thread.id)}>
                  <Plus size={15} />
                  <span>
                    <strong>{thread.title}</strong>
                    <em>{thread.date} · {thread.sessions.length} 次</em>
                  </span>
                </button>
              )) : visibleAvailableSessions.length ? visibleAvailableSessions.map((session) => (
                <button className="project-add-row" type="button" key={session.id} onClick={() => addSession(session.id)}>
                  <Plus size={15} />
                  <span>
                    <strong>{session.title}</strong>
                    <em>{session.date} · {session.turns} 轮</em>
                  </span>
                </button>
              )) : (
                <div className="empty-inline">{cleanQuery ? '没有匹配话题' : '没有可加入的话题'}</div>
              )}
            </div>
          </div>
        </section>
      ) : (
        <EmptyDetail icon={Folder} title="暂无项目" text="创建一个项目后，可以把相关话题放进文件夹。" />
      )}
    </div>
  )
}
