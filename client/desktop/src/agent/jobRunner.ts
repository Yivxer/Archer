import type { JobEvent } from './contracts'

type JobDefinition = {
  title: string
  run: () => Promise<string>
}

type QueuedJob = JobDefinition & {
  id: string
}

type JobRunnerOptions = {
  sessionId?: string
  emit: (event: JobEvent) => void
}

function nowIso(): string {
  return new Date().toISOString()
}

function makeJobEvent(sessionId: string, job: QueuedJob, status: JobEvent['status'], detail: string): JobEvent {
  return {
    type: 'job.event',
    id: `${job.id}-${status}-${Date.now()}`,
    sessionId,
    createdAt: nowIso(),
    jobId: job.id,
    title: job.title,
    status,
    detail,
  }
}

export function createJobRunner(options: JobRunnerOptions) {
  const queue: QueuedJob[] = []
  const sessionId = options.sessionId || 'desktop-session'
  let counter = 0

  return {
    enqueue(definition: JobDefinition): string {
      counter += 1
      const job = { ...definition, id: `job-${counter}` }
      queue.push(job)
      options.emit(makeJobEvent(sessionId, job, 'queued', '等待后台执行'))
      return job.id
    },
    async runNext(): Promise<void> {
      const job = queue.shift()
      if (!job) return
      options.emit(makeJobEvent(sessionId, job, 'running', '后台执行中'))
      try {
        const result = await job.run()
        options.emit(makeJobEvent(sessionId, job, 'complete', result))
      } catch (error) {
        options.emit(makeJobEvent(sessionId, job, 'failed', error instanceof Error ? error.message : 'unknown error'))
      }
    },
    pendingCount(): number {
      return queue.length
    },
  }
}
