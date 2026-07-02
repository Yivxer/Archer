import type { JobEvent, JobStatus } from './contracts'

export type RuntimeJobSnapshot = {
  id: string
  title: string
  status: JobStatus
  result: string
  createdAt: string
  updatedAt: string
  error?: string
  stale?: boolean
}

const JOB_STATUS_DETAIL: Record<JobStatus, string> = {
  queued: '等待后台执行',
  running: '后台执行中',
  waiting_approval: '等待确认',
  complete: '后台任务完成',
  failed: '后台任务失败',
  cancelled: '后台任务已取消',
}

function sanitizeEventPart(value: string): string {
  return value.replace(/[^a-zA-Z0-9_.:-]/g, '-')
}

export function jobSnapshotToAgentEvent(sessionId: string, job: RuntimeJobSnapshot): JobEvent {
  const timestamp = job.updatedAt || job.createdAt
  const staleDetail = job.stale
    ? `任务长时间没有进展，已自动取消。${job.error ? job.error : ''}`.trim()
    : ''
  const detail = staleDetail || (job.status === 'complete'
    ? job.result
    : job.status === 'failed'
      ? job.error || job.result || JOB_STATUS_DETAIL.failed
      : JOB_STATUS_DETAIL[job.status])

  return {
    type: 'job.event',
    id: `job-${sanitizeEventPart(job.id)}-${job.status}-${sanitizeEventPart(timestamp)}`,
    sessionId,
    createdAt: timestamp,
    jobId: job.id,
    title: job.title,
    status: job.status,
    detail,
    stale: job.stale || undefined,
  }
}
