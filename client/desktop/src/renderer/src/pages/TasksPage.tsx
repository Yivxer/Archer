import React from 'react'
import { Check, ChevronRight, Clock3, Loader2, Plus, RotateCcw, X } from 'lucide-react'
import { cancelBackgroundJob, listBackgroundJobs, retryBackgroundJob, spawnChildJobs } from '../adapters/localArcher'
import { EmptyDetail, SearchBox } from '../components/common'
import type { ArcherAdapter, BackgroundJob } from '../types'
import type { SpawnChildSpec } from '../adapters/localArcher'

type LoadState = 'idle' | 'loading' | 'error'

export function TasksPage({ data }: { data: ArcherAdapter }) {
  const [jobs, setJobs] = React.useState<BackgroundJob[]>([])
  const [selectedId, setSelectedId] = React.useState('')
  const [query, setQuery] = React.useState('')
  const [loadState, setLoadState] = React.useState<LoadState>('idle')
  const [notice, setNotice] = React.useState('')

  async function refreshJobs() {
    if (data.status.adapter !== 'local') return
    setLoadState('loading')
    setNotice('')
    try {
      const result = await listBackgroundJobs()
      setJobs(result.jobs)
      setSelectedId((current) => current && result.jobs.some((job) => job.id === current)
        ? current
        : result.jobs[0]?.id || '')
      setLoadState('idle')
    } catch (error) {
      setLoadState('error')
      setNotice(error instanceof Error ? error.message : '后台任务读取失败')
    }
  }

  React.useEffect(() => {
    void refreshJobs()
  }, [data.status.adapter])

  async function cancelJob(job: BackgroundJob) {
    try {
      const result = await cancelBackgroundJob(job.id)
      upsertJob(result.job)
      setNotice(result.message)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '取消失败')
    }
  }

  async function retryJob(job: BackgroundJob) {
    try {
      const result = await retryBackgroundJob(job.id)
      upsertJob(result.job)
      setNotice(result.message)
      window.setTimeout(() => void refreshJobs(), 600)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '重试失败')
    }
  }

  async function spawnChildJob(job: BackgroundJob, spec: SpawnChildSpec) {
    try {
      const result = await spawnChildJobs(job.id, [spec])
      setNotice(`已创建 ${result.spawned} 个子任务`)
      await refreshJobs()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '子任务创建失败')
    }
  }

  function upsertJob(job: BackgroundJob) {
    setJobs((current) => current.map((item) => (item.id === job.id ? job : item)))
    setSelectedId(job.id)
  }

  const visibleJobs = React.useMemo(() => {
    const clean = query.trim().toLowerCase()
    if (!clean) return jobs
    return jobs.filter((job) => [job.title, job.kind, job.prompt, job.status, job.result, job.error]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
      .includes(clean))
  }, [jobs, query])
  const selected = visibleJobs.find((job) => job.id === selectedId) ?? visibleJobs[0]

  React.useEffect(() => {
    if (visibleJobs.length && !visibleJobs.some((job) => job.id === selectedId)) {
      setSelectedId(visibleJobs[0].id)
    }
  }, [selectedId, visibleJobs])

  if (data.status.adapter !== 'local') {
    return <EmptyDetail icon={Clock3} title="等待连接" text="后台任务需要先连上 Archer 大脑。" />
  }

  return (
    <div className="split-page tasks-page">
      <div className="list-column">
        <div className="sessions-head">
          <div>
            <h1>后台任务</h1>
            <p>{loadState === 'loading' ? '同步中' : '本地 jobs'}</p>
          </div>
          <span>{visibleJobs.length}</span>
        </div>
        <div className="list-toolbar">
          <SearchBox placeholder="搜索任务" value={query} onChange={setQuery} />
          <button className="quiet-button" type="button" onClick={() => void refreshJobs()}>
            刷新
          </button>
        </div>
        {visibleJobs.length ? visibleJobs.map((job) => (
          <button
            className={`list-row task-row ${selected?.id === job.id ? 'active' : ''}`}
            key={job.id}
            type="button"
            onClick={() => setSelectedId(job.id)}
          >
            <div>
              <strong>{job.title || job.id}</strong>
              <span>{jobStatusLabel(job.status)} · {job.kind}</span>
              <span className="session-preview">{job.result || job.error || job.prompt}</span>
            </div>
            <ChevronRight size={16} />
          </button>
        )) : (
          <div className="empty-inline">{loadState === 'error' ? '任务读取失败' : '暂无后台任务'}</div>
        )}
      </div>

      {selected ? (
        <TaskDetail
          job={selected}
          notice={notice}
          onCancel={() => void cancelJob(selected)}
          onRetry={() => void retryJob(selected)}
          onSpawnChild={(spec) => spawnChildJob(selected, spec)}
        />
      ) : (
        <EmptyDetail icon={Clock3} title="暂无任务" text="后台 jobs 记录为空。" />
      )}
    </div>
  )
}

function TaskDetail({
  job,
  notice,
  onCancel,
  onRetry,
  onSpawnChild,
}: {
  job: BackgroundJob
  notice: string
  onCancel: () => void
  onRetry: () => void
  onSpawnChild: (spec: SpawnChildSpec) => Promise<void>
}) {
  const isActive = job.status === 'queued' || job.status === 'running' || job.status === 'waiting_approval'
  const canRetry = job.status === 'failed' || job.status === 'cancelled'
  const StatusIcon = isActive ? Loader2 : job.status === 'complete' ? Check : X
  const [showChildForm, setShowChildForm] = React.useState(false)
  const [childTitle, setChildTitle] = React.useState('')
  const [childKind, setChildKind] = React.useState('analysis')
  const [childPrompt, setChildPrompt] = React.useState('')
  const [childAutoStart, setChildAutoStart] = React.useState(false)

  async function handleSpawnChild(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const title = childTitle.trim()
    const prompt = childPrompt.trim()
    if (!title || !prompt) return
    await onSpawnChild({
      title,
      kind: childKind,
      prompt,
      autoStart: childAutoStart,
    })
    setChildTitle('')
    setChildPrompt('')
    setChildKind('analysis')
    setChildAutoStart(false)
    setShowChildForm(false)
  }

  return (
    <div className="session-detail task-detail">
      <div className="session-detail-head">
        <div className={`session-detail-icon task-status-${job.status}`}>
          <StatusIcon size={18} />
        </div>
        <div>
          <h2>{job.title || job.id}</h2>
          <p>{job.id} · {jobStatusLabel(job.status)} · {formatDate(job.updatedAt)}</p>
        </div>
        <div className="task-actions">
          <button className="quiet-button" type="button" onClick={() => setShowChildForm((value) => !value)}>
            <Plus size={14} />
            拆分子任务
          </button>
          {isActive && <button className="quiet-button" type="button" onClick={onCancel}>取消</button>}
          {canRetry && <button className="quiet-button strong" type="button" onClick={onRetry}>重试</button>}
        </div>
      </div>
      <dl>
        <div>
          <dt>类型</dt>
          <dd>{job.kind}</dd>
        </div>
        <div>
          <dt>超时</dt>
          <dd>{job.timeoutSeconds ?? 300}s</dd>
        </div>
        <div>
          <dt>创建</dt>
          <dd>{formatDate(job.createdAt)}</dd>
        </div>
      </dl>
      {notice && <p className="detail-muted">{notice}</p>}
      {job.error && <p className="detail-error">{job.error}</p>}
      {showChildForm && (
        <form className="task-child-form" onSubmit={(event) => void handleSpawnChild(event)}>
          <label>
            <span>标题</span>
            <input value={childTitle} onChange={(event) => setChildTitle(event.target.value)} />
          </label>
          <label>
            <span>类型</span>
            <select value={childKind} onChange={(event) => setChildKind(event.target.value)}>
              <option value="analysis">analysis</option>
              <option value="review">review</option>
              <option value="work">work</option>
            </select>
          </label>
          <label className="task-child-prompt">
            <span>Prompt</span>
            <textarea value={childPrompt} onChange={(event) => setChildPrompt(event.target.value)} />
          </label>
          <label className="task-child-autostart">
            <input type="checkbox" checked={childAutoStart} onChange={(event) => setChildAutoStart(event.target.checked)} />
            <span>立即开始</span>
          </label>
          <div className="task-child-form-actions">
            <button className="quiet-button" type="button" onClick={() => setShowChildForm(false)}>取消</button>
            <button className="quiet-button strong" type="submit" disabled={!childTitle.trim() || !childPrompt.trim()}>创建</button>
          </div>
        </form>
      )}
      <section className="task-section">
        <h3>请求</h3>
        <p>{job.prompt}</p>
      </section>
      {job.children?.length ? (
        <section className="task-section">
          <h3>子任务</h3>
          <div className="task-child-list">
            {job.children.map((child) => {
              const ChildIcon = childStatusIcon(child.status)
              return (
                <div className={`task-child-row task-status-${child.status}`} key={child.id}>
                  <div className="task-child-row-head">
                    <div className={`task-child-status-icon task-status-${child.status}`}>
                      <ChildIcon size={14} />
                    </div>
                    <strong>{child.title || child.id}</strong>
                    {(child.parentJobId || child.isolated) && (
                      <span className="task-child-isolated">隔离</span>
                    )}
                  </div>
                  <span>{jobStatusLabel(child.status)} · {formatDate(child.createdAt)}</span>
                  {child.error ? <p className="task-child-error">{child.error}</p> : null}
                  {child.result ? <p className="task-child-preview">{child.result}</p> : null}
                </div>
              )
            })}
          </div>
        </section>
      ) : null}
      <section className="task-section">
        <h3>结果</h3>
        <p>{job.result || '暂无结果'}</p>
      </section>
    </div>
  )
}

function jobStatusLabel(status: BackgroundJob['status']): string {
  if (status === 'queued') return '等待中'
  if (status === 'running') return '执行中'
  if (status === 'waiting_approval') return '等待确认'
  if (status === 'complete') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'cancelled') return '已取消'
  return status
}

function childStatusIcon(status: BackgroundJob['status']) {
  if (status === 'queued' || status === 'running' || status === 'waiting_approval') return Loader2
  if (status === 'complete') return Check
  return X
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value || '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}
