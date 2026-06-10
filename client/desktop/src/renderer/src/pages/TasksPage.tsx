import React from 'react'
import { Check, ChevronRight, Clock3, Loader2, RotateCcw, X } from 'lucide-react'
import { cancelBackgroundJob, listBackgroundJobs, retryBackgroundJob } from '../adapters/localArcher'
import { EmptyDetail, SearchBox } from '../components/common'
import type { ArcherAdapter, BackgroundJob } from '../types'

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
        <TaskDetail job={selected} notice={notice} onCancel={() => void cancelJob(selected)} onRetry={() => void retryJob(selected)} />
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
}: {
  job: BackgroundJob
  notice: string
  onCancel: () => void
  onRetry: () => void
}) {
  const isActive = job.status === 'queued' || job.status === 'running' || job.status === 'waiting_approval'
  const canRetry = job.status === 'failed' || job.status === 'cancelled'
  const StatusIcon = isActive ? Loader2 : job.status === 'complete' ? Check : X

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
      <section className="task-section">
        <h3>请求</h3>
        <p>{job.prompt}</p>
      </section>
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

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value || '-'
  return date.toLocaleString('zh-CN', { hour12: false })
}
