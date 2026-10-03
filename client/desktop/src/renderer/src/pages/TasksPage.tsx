import React from 'react'
import { Check, ChevronRight, Clock3, Copy, Loader2, Plus, Trash2, X } from 'lucide-react'
import { EmptyDetail, SearchBox } from '../components/common'
import { EmptyState } from '../components/EmptyState'
import type { BackgroundJob, BackgroundJobChildSummary, RuntimeRun } from '../types'
import type { SpawnChildSpec } from '../adapters/jobAdapter'
import {
  cancelJob as cancelStoredJob,
  clearJobDetail,
  loadJobDetail,
  loadJobList,
  retryJob as retryStoredJob,
  spawnChildren,
  useJobStore,
} from '../lib/jobStore'
import {
  cancelRuntimeRun,
  loadRuntimeRuns,
  retryRuntimeRun,
  useRuntimeRunStore,
} from '../lib/runtimeRunStore'

type ChildDraft = {
  key: string
  title: string
  kind: string
  prompt: string
  autoStart: boolean
}

function createChildDraft(): ChildDraft {
  return {
    key: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: '',
    kind: 'analysis',
    prompt: '',
    autoStart: false,
  }
}

export function TasksPage({ connected }: { connected: boolean }) {
  const jobs = useJobStore((state) => state.jobs)
  const runtimeRuns = useRuntimeRunStore((state) => state.runs)
  const runtimeLoadState = useRuntimeRunStore((state) => state.loadState)
  const jobDetail = useJobStore((state) => state.currentDetail)
  const loadState = useJobStore((state) => state.loadState)
  const listError = useJobStore((state) => state.listError)
  const detailError = useJobStore((state) => state.detailError)
  const detailState = useJobStore((state) => state.detailState)
  const busyIds = useJobStore((state) => state.busyIds)
  const [selectedId, setSelectedId] = React.useState('')
  const [query, setQuery] = React.useState('')
  const [notice, setNotice] = React.useState<{ jobId: string; text: string } | null>(null)
  const [runtimeNotice, setRuntimeNotice] = React.useState('')
  const [retryingRunId, setRetryingRunId] = React.useState('')
  const [cancellingRunId, setCancellingRunId] = React.useState('')

  async function refreshJobs() {
    if (!connected) return
    setNotice(null)
    await Promise.all([loadJobList({ force: true }), loadRuntimeRuns()])
  }

  React.useEffect(() => {
    void refreshJobs()
  }, [connected])

  React.useEffect(() => {
    if (selectedId && connected) void loadJobDetail(selectedId)
    else clearJobDetail()
    return clearJobDetail
  }, [selectedId, connected])

  React.useEffect(() => {
    if (jobs.length && !jobs.some((job) => job.id === selectedId)) {
      setSelectedId(jobs[0].id)
    }
    if (!jobs.length && selectedId) setSelectedId('')
  }, [jobs, selectedId])

  async function cancelJob(job: BackgroundJob) {
    try {
      const result = await cancelStoredJob(job.id)
      setSelectedId(job.id)
      setNotice({ jobId: job.id, text: result.message || `任务状态：${jobStatusLabel(result.job.status, result.job.stale)}` })
    } catch (error) {
      setNotice({ jobId: job.id, text: error instanceof Error ? error.message : '取消失败' })
    }
  }

  async function retryJob(job: BackgroundJob) {
    try {
      const result = await retryStoredJob(job.id)
      setSelectedId(job.id)
      setNotice({ jobId: job.id, text: result.message || `任务状态：${jobStatusLabel(result.job.status, result.job.stale)}` })
    } catch (error) {
      setNotice({ jobId: job.id, text: error instanceof Error ? error.message : '重试失败' })
    }
  }

  async function retryRunVerification(run: RuntimeRun) {
    setRetryingRunId(run.id)
    setRuntimeNotice('')
    try {
      await retryRuntimeRun(run.id)
      setRuntimeNotice('已重新验证现有产物；未重复写入 Obsidian。')
    } catch (error) {
      setRuntimeNotice(error instanceof Error ? error.message : '重新验证失败')
    } finally {
      setRetryingRunId('')
    }
  }

  async function cancelRunExecution(run: RuntimeRun) {
    setCancellingRunId(run.id)
    setRuntimeNotice('')
    try {
      const current = await cancelRuntimeRun(run.id)
      setRuntimeNotice(
        current.state === 'cancelled'
          ? 'Run 已取消；未产生新的副作用。'
          : '取消请求已记录；正在抑制迟到结果。',
      )
    } catch (error) {
      setRuntimeNotice(error instanceof Error ? error.message : '取消失败')
    } finally {
      setCancellingRunId('')
    }
  }

  async function spawnChildJobsForParent(job: BackgroundJob, specs: SpawnChildSpec[]) {
    try {
      const result = await spawnChildren(job.id, specs)
      setNotice({ jobId: job.id, text: `已创建 ${result.spawned} 个子任务` })
      return true
    } catch (error) {
      setNotice({ jobId: job.id, text: error instanceof Error ? error.message : '子任务创建失败' })
      return false
    }
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
  const selectedDetail = selected && jobDetail?.id === selected.id ? jobDetail : selected

  React.useEffect(() => {
    if (visibleJobs.length && !visibleJobs.some((job) => job.id === selectedId)) {
      setSelectedId(visibleJobs[0].id)
    }
  }, [selectedId, visibleJobs])

  if (!connected) {
    return <EmptyDetail icon={Clock3} title="等待连接" text="后台任务需要先连上 Archer 大脑。" />
  }

  return (
    <div className="split-page tasks-page">
      <div className="list-column">
        <div className="sessions-head">
          <div>
            <h1>后台任务</h1>
            <p>{loadState === 'loading' ? '同步中' : '已保存的后台任务'}</p>
          </div>
          <span>{visibleJobs.length}</span>
        </div>
        <div className="list-toolbar">
          <SearchBox placeholder="搜索任务" value={query} onChange={setQuery} />
          <button className="quiet-button" type="button" onClick={() => void refreshJobs()}>
            刷新
          </button>
        </div>
        {listError && <p className="detail-error" role="alert">任务列表刷新失败：{listError}。已保留最近内容，请刷新重试。</p>}
        {runtimeNotice && <p className="detail-muted">{runtimeNotice}</p>}
        {runtimeRuns.length > 0 && (
          <div className="runtime-run-list" aria-label="Runtime Runs">
            <span>运行中的 Run · {runtimeLoadState === 'loading' ? '同步中' : runtimeRuns.length}</span>
            {runtimeRuns.map((run) => (
              <div className={`list-row runtime-run-row run-${run.state}`} key={run.id}>
                <div>
                  <strong>{run.objective}</strong>
                  <span>{runtimeRunDisplayLabel(run)} · {run.source}</span>
                </div>
                {canRetryRuntimeRun(run) && (
                  <button
                    className="quiet-button strong"
                    type="button"
                    disabled={retryingRunId === run.id}
                    onClick={() => void retryRunVerification(run)}
                  >
                    {retryingRunId === run.id ? '验证中…' : '重新验证'}
                  </button>
                )}
                {canCancelRuntimeRun(run) && (
                  <button
                    className="quiet-button"
                    type="button"
                    disabled={cancellingRunId === run.id}
                    onClick={() => void cancelRunExecution(run)}
                  >
                    {cancellingRunId === run.id ? '取消中…' : '取消'}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        {visibleJobs.length ? visibleJobs.map((job) => (
          <button
            className={`list-row task-row ${selected?.id === job.id ? 'active' : ''}`}
            key={job.id}
            type="button"
            onClick={() => setSelectedId(job.id)}
          >
            <div>
              <strong>{job.title || job.id}</strong>
              <span>{jobStatusLabel(job.status, job.stale)} · {job.kind}</span>
              <span className="session-preview">{job.result || job.error || job.prompt}</span>
            </div>
            <ChevronRight size={16} />
          </button>
        )) : (
          <EmptyState compact title={loadState === 'error' ? '任务读取失败' : loadState === 'idle' || loadState === 'loading' ? '正在读取任务' : '暂无后台任务'} />
        )}
      </div>

      {selectedDetail ? (
        <TaskDetail
          key={selectedDetail.id}
          job={selectedDetail}
          canAct={loadState === 'ready' && detailState === 'ready' && jobDetail?.id === selectedDetail.id && !busyIds.has(selectedDetail.id)}
          busy={busyIds.has(selectedDetail.id)}
          notice={[notice?.jobId === selectedDetail.id ? notice.text : '', detailError ? `详情读取失败：${detailError}` : ''].filter(Boolean).join('；')}
          onCancel={() => void cancelJob(selectedDetail)}
          onRetry={() => void retryJob(selectedDetail)}
          onSpawnChildren={(specs) => spawnChildJobsForParent(selectedDetail, specs)}
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
  canAct,
  busy,
  onCancel,
  onRetry,
  onSpawnChildren,
}: {
  job: BackgroundJob
  notice: string
  canAct: boolean
  busy: boolean
  onCancel: () => void
  onRetry: () => void
  onSpawnChildren: (specs: SpawnChildSpec[]) => Promise<boolean>
}) {
  const isActive = job.status === 'queued' || job.status === 'running' || job.status === 'waiting_approval'
  const canRetry = job.status === 'failed' || job.status === 'cancelled'
  const StatusIcon = isActive ? Loader2 : job.status === 'complete' ? Check : X
  const [showChildForm, setShowChildForm] = React.useState(false)
  const [childDrafts, setChildDrafts] = React.useState<ChildDraft[]>([createChildDraft()])
  const [copyNotice, setCopyNotice] = React.useState('')
  const children = job.children ?? []
  const childProgress = summarizeChildProgress(children)
  const childSummaryText = buildChildJobsSummary(children)

  function updateDraft(key: string, patch: Partial<ChildDraft>) {
    setChildDrafts((current) => current.map((draft) => (
      draft.key === key ? { ...draft, ...patch } : draft
    )))
  }

  function addDraftRow() {
    setChildDrafts((current) => [...current, createChildDraft()])
  }

  function removeDraftRow(key: string) {
    setChildDrafts((current) => (
      current.length <= 1 ? current : current.filter((draft) => draft.key !== key)
    ))
  }

  async function handleSpawnChildren(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const specs = childDrafts
      .map((draft) => ({
        title: draft.title.trim(),
        kind: draft.kind,
        prompt: draft.prompt.trim(),
        autoStart: draft.autoStart,
      }))
      .filter((spec) => spec.title && spec.prompt)
    if (!specs.length || !canAct) return
    if (!await onSpawnChildren(specs)) return
    setChildDrafts([createChildDraft()])
    setShowChildForm(false)
  }

  async function copyChildSummary() {
    if (!childSummaryText) return
    try {
      await navigator.clipboard.writeText(childSummaryText)
      setCopyNotice('已复制子任务汇总')
      window.setTimeout(() => setCopyNotice(''), 1800)
    } catch {
      setCopyNotice('复制失败')
    }
  }

  const validDraftCount = childDrafts.filter((draft) => draft.title.trim() && draft.prompt.trim()).length

  return (
    <div className="session-detail task-detail">
      <div className="session-detail-head">
        <div className={`session-detail-icon task-status-${job.status}`}>
          <StatusIcon size={18} />
        </div>
        <div>
          <h2>{job.title || job.id}</h2>
          <p>{job.id} · {jobStatusLabel(job.status, job.stale)} · {formatDate(job.updatedAt)}</p>
        </div>
        <div className="task-actions">
          <button className="quiet-button" type="button" disabled={!canAct} onClick={() => setShowChildForm((value) => !value)}>
            <Plus size={14} />
            拆分子任务
          </button>
          {isActive && <button className="quiet-button" type="button" disabled={!canAct} onClick={onCancel}>{busy ? '处理中…' : '取消'}</button>}
          {canRetry && <button className="quiet-button strong" type="button" disabled={!canAct} onClick={onRetry}>{busy ? '处理中…' : '重试'}</button>}
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
        <form className="task-child-form" onSubmit={(event) => void handleSpawnChildren(event)}>
          <div className="task-child-form-head">
            <strong>批量创建子任务</strong>
            <span>一次最多提交 20 个</span>
          </div>
          {childDrafts.map((draft, index) => (
            <div className="task-child-draft-row" key={draft.key}>
              <div className="task-child-draft-row-head">
                <strong>子任务 {index + 1}</strong>
                {childDrafts.length > 1 ? (
                  <button className="quiet-button task-child-draft-remove" type="button" onClick={() => removeDraftRow(draft.key)}>
                    <Trash2 size={14} />
                    移除
                  </button>
                ) : null}
              </div>
              <label>
                <span>标题</span>
                <input value={draft.title} onChange={(event) => updateDraft(draft.key, { title: event.target.value })} />
              </label>
              <label>
                <span>类型</span>
                <select value={draft.kind} onChange={(event) => updateDraft(draft.key, { kind: event.target.value })}>
                  <option value="analysis">analysis</option>
                  <option value="review">review</option>
                  <option value="work">work</option>
                </select>
              </label>
              <label className="task-child-prompt">
                <span>Prompt</span>
                <textarea value={draft.prompt} onChange={(event) => updateDraft(draft.key, { prompt: event.target.value })} />
              </label>
              <label className="task-child-autostart">
                <input
                  type="checkbox"
                  checked={draft.autoStart}
                  onChange={(event) => updateDraft(draft.key, { autoStart: event.target.checked })}
                />
                <span>立即开始</span>
              </label>
            </div>
          ))}
          <div className="task-child-form-toolbar">
            <button className="quiet-button" type="button" onClick={addDraftRow}>
              <Plus size={14} />
              添加一行
            </button>
          </div>
          <div className="task-child-form-actions">
            <button className="quiet-button" type="button" onClick={() => setShowChildForm(false)}>取消</button>
            <button className="quiet-button strong" type="submit" disabled={!canAct || !validDraftCount}>
              创建 {validDraftCount || ''} 个子任务
            </button>
          </div>
        </form>
      )}
      <section className="task-section">
        <h3>请求</h3>
        <p>{job.prompt}</p>
      </section>
      {children.length ? (
        <>
          <section className="task-section">
            <div className="task-section-head">
              <h3>子任务汇总</h3>
              <button className="quiet-button" type="button" onClick={() => void copyChildSummary()}>
                <Copy size={14} />
                复制汇总
              </button>
            </div>
            {copyNotice ? <p className="detail-muted">{copyNotice}</p> : null}
            <p className="task-child-summary-stats">
              共 {childProgress.total} 个 · 已完成 {childProgress.complete} · 进行中 {childProgress.active} · 失败/取消 {childProgress.failed}
            </p>
            <pre className="task-child-summary-text">{childSummaryText}</pre>
          </section>
          <section className="task-section">
            <h3>子任务</h3>
            <div className="task-child-list">
              {children.map((child) => {
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
        </>
      ) : null}
      <section className="task-section">
        <h3>结果</h3>
        <p>{job.result || '暂无结果'}</p>
      </section>
    </div>
  )
}

export function summarizeChildProgress(children: BackgroundJobChildSummary[]) {
  return {
    total: children.length,
    complete: children.filter((child) => child.status === 'complete').length,
    failed: children.filter((child) => child.status === 'failed' || child.status === 'cancelled').length,
    active: children.filter((child) => (
      child.status === 'queued' || child.status === 'running' || child.status === 'waiting_approval'
    )).length,
  }
}

export function buildChildJobsSummary(children: BackgroundJobChildSummary[]): string {
  if (!children.length) return ''
  const progress = summarizeChildProgress(children)
  const lines = [
    `子任务进度：${progress.complete}/${progress.total} 已完成，${progress.active} 进行中，${progress.failed} 失败或取消。`,
  ]
  for (const child of children) {
    lines.push('')
    lines.push(`## ${child.title || child.id}（${jobStatusLabel(child.status)}）`)
    if (child.error) {
      lines.push(`错误：${child.error}`)
    } else if (child.result) {
      lines.push(child.result)
    } else {
      lines.push('（暂无结果）')
    }
  }
  return lines.join('\n')
}

function runtimeRunStateLabel(state: RuntimeRun['state']): string {
  if (state === 'waiting_approval') return '等待确认'
  if (state === 'waiting_user') return '等待用户'
  if (state === 'executing') return '执行中'
  if (state === 'verifying') return '验证中'
  if (state === 'uncertain') return '结果待确认'
  if (state === 'interrupted') return '已中断'
  if (state === 'cancelling') return '取消中'
  return '准备中'
}

function runtimeRunDisplayLabel(run: RuntimeRun): string {
  if (run.recovery?.classification === 'invalid') return '恢复信息异常，等待人工处理'
  if (run.recovery?.classification === 'manual') return `${runtimeRunStateLabel(run.state)}，需要人工继续`
  if (run.recovery?.classification === 'recoverable') return '结果待确认，可安全重新验证'
  return runtimeRunStateLabel(run.state)
}

function canRetryRuntimeRun(run: RuntimeRun): boolean {
  return run.state === 'uncertain'
    && run.recovery?.classification === 'recoverable'
}

function canCancelRuntimeRun(run: RuntimeRun): boolean {
  return run.source === 'desktop.obsidian_write' && (
    run.state === 'waiting_approval'
    || run.state === 'executing'
    || run.state === 'uncertain'
    || run.state === 'interrupted'
  )
}

function jobStatusLabel(status: BackgroundJob['status'], stale?: boolean): string {
  if (status === 'queued') return '等待中'
  if (status === 'running') return '执行中'
  if (status === 'waiting_approval') return '等待确认'
  if (status === 'complete') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'cancelled' && stale) return '已取消（无进展超时）'
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
