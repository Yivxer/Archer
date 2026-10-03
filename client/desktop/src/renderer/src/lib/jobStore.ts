/** Server-owned background jobs; runtimeStore events remain trace receipts. */
import * as api from '../adapters/jobAdapter'
import type { SpawnChildSpec, SpawnChildrenResult } from '../adapters/jobAdapter'
import type { BackgroundJob, BackgroundJobActionResult, BackgroundJobCreateResult } from '../types'
import { jobSnapshotToAgentEvent, type AgentEvent } from '../../../agent'
import { createExternalStore, useExternalStore, type LoadState } from './externalStore'
import { emitStoreEvent } from './storeEventBus'

export type JobStoreState = {
  jobs: BackgroundJob[]
  currentDetail: BackgroundJob | null
  loadState: LoadState
  detailState: LoadState
  error: string
  listError: string
  detailError: string
  actionError: string
  busyIds: Set<string>
}
const initialState: JobStoreState = {
  jobs: [], currentDetail: null, loadState: 'idle', detailState: 'idle',
  error: '', listError: '', detailError: '', actionError: '', busyIds: new Set(),
}
const store = createExternalStore<JobStoreState>(initialState)
let listGeneration = 0
let detailGeneration = 0
let resetGeneration = 0
let pendingList: Promise<void> | null = null
let detailTarget = ''
const jobReads = new Map<string, number>()
const errorText = (error: unknown): string => error instanceof Error ? error.message : String(error)
const superseded = (): DOMException => new DOMException('任务读取已由更新状态替代', 'AbortError')

export function getJobStoreState(): JobStoreState { return store.getState() }
export function subscribeJobStore(listener: () => void): () => void { return store.subscribe(listener) }

export function loadJobList(options: { force?: boolean } = {}): Promise<void> {
  if (pendingList && !options.force) return pendingList
  const generation = ++listGeneration
  store.setState((s) => ({ ...s, loadState: 'loading', listError: '' }))
  pendingList = readJobList(generation)
  return pendingList
}

async function readJobList(generation: number): Promise<void> {
  try {
    const result = await api.listBackgroundJobs()
    if (generation !== listGeneration) return
    assertReceipt(result)
    mergeJobItems(result.jobs)
  } catch (error) {
    if (generation !== listGeneration) return
    store.setState((s) => ({ ...s, loadState: 'error', listError: errorText(error), error: errorText(error) }))
  } finally {
    if (generation === listGeneration) pendingList = null
  }
}

export async function loadJobDetail(jobId: string): Promise<void> {
  const generation = ++detailGeneration
  const epoch = resetGeneration
  const readId = jobReads.get(jobId) ?? 0
  detailTarget = jobId
  store.setState((s) => ({ ...s, currentDetail: null, detailState: 'loading', detailError: '' }))
  try {
    const job = await api.fetchBackgroundJob(jobId)
    if (generation !== detailGeneration || epoch !== resetGeneration || readId !== (jobReads.get(jobId) ?? 0)) return
    store.setState((s) => ({ ...s, currentDetail: job, detailState: 'ready', detailError: '', error: '' }))
  } catch (error) {
    if (generation !== detailGeneration || epoch !== resetGeneration || readId !== (jobReads.get(jobId) ?? 0)) return
    store.setState((s) => ({ ...s, detailState: 'error', detailError: errorText(error), error: errorText(error) }))
  }
}

export function mergeJobItems(jobs: BackgroundJob[]): void {
  store.setState((s) => ({ ...s, jobs, loadState: 'ready', listError: '', error: '' }))
}

function assertReceipt(result: { ok: boolean; error?: string; message?: string }): void {
  if (!result.ok) throw new Error(result.error || result.message || '任务操作未完成，请刷新后重试')
}

function nextJobRead(id: string): number {
  const next = (jobReads.get(id) ?? 0) + 1
  jobReads.set(id, next)
  return next
}

function invalidateList(): boolean {
  const hadPending = pendingList !== null
  listGeneration += 1
  pendingList = null
  return hadPending
}

function projectJob(job: BackgroundJob): void {
  nextJobRead(job.id)
  if (detailTarget === job.id) detailGeneration += 1
  store.setState((s) => ({
    ...s,
    jobs: s.jobs.some((item) => item.id === job.id)
      ? s.jobs.map((item) => item.id === job.id ? job : item) : [...s.jobs, job],
    currentDetail: detailTarget === job.id ? job : s.currentDetail,
    detailState: detailTarget === job.id ? 'ready' : s.detailState,
    detailError: detailTarget === job.id ? '' : s.detailError,
  }))
}

async function refreshAfterWrite(jobId?: string): Promise<void> {
  const selected = jobId && detailTarget === jobId
  await Promise.all([
    loadJobList({ force: true }),
    selected ? loadJobDetail(jobId) : Promise.resolve(),
  ])
}

export async function createJobReceipt(payload: Parameters<typeof api.createBackgroundJob>[0]): Promise<BackgroundJobCreateResult> {
  const epoch = resetGeneration
  const result = await api.createBackgroundJob(payload)
  assertReceipt(result)
  if (epoch === resetGeneration) {
    invalidateList()
    projectJob(result.job)
    await refreshAfterWrite()
    if (epoch === resetGeneration) emitStoreEvent({ type: 'job:created', jobId: result.job.id })
  }
  return result
}

export async function createJob(payload: Parameters<typeof api.createBackgroundJob>[0]): Promise<BackgroundJob | null> {
  const epoch = resetGeneration
  try { return (await createJobReceipt(payload)).job }
  catch (error) {
    if (epoch === resetGeneration) store.setState((s) => ({ ...s, actionError: errorText(error), error: errorText(error) }))
    return null
  }
}

async function mutateJob<T extends { ok: boolean }>(jobId: string, action: () => Promise<T>, project: (result: T) => void): Promise<T> {
  if (store.getState().busyIds.has(jobId)) throw new Error('该任务正在处理，请稍后再试')
  const epoch = resetGeneration
  nextJobRead(jobId)
  store.setState((s) => ({ ...s, actionError: '', busyIds: new Set([...s.busyIds, jobId]) }))
  try {
    const result = await action()
    assertReceipt(result)
    if (epoch !== resetGeneration) return result
    invalidateList()
    project(result)
    await refreshAfterWrite(jobId)
    return result
  } catch (error) {
    if (epoch === resetGeneration) store.setState((s) => ({ ...s, actionError: errorText(error), error: errorText(error) }))
    throw error
  } finally {
    if (epoch === resetGeneration) {
      store.setState((s) => ({ ...s, busyIds: new Set([...s.busyIds].filter((id) => id !== jobId)) }))
      if (detailTarget === jobId && store.getState().detailState === 'loading') void loadJobDetail(jobId)
    }
  }
}

export async function cancelJob(jobId: string): Promise<BackgroundJobActionResult> {
  return mutateJob(jobId, () => api.cancelBackgroundJob(jobId), (result) => {
    projectJob(result.job)
    emitStoreEvent({ type: 'job:cancelled', jobId })
  })
}

export async function retryJob(jobId: string): Promise<BackgroundJobActionResult> {
  return mutateJob(jobId, () => api.retryBackgroundJob(jobId), (result) => {
    projectJob(result.job)
    emitStoreEvent({ type: 'job:retried', jobId })
  })
}

export async function approveJob(jobId: string, eventId: string, decision: 'approved' | 'denied'): Promise<BackgroundJobActionResult> {
  return mutateJob(jobId, () => api.approveJobTool(jobId, eventId, decision), (result) => {
    projectJob(result.job)
    emitStoreEvent({ type: 'job:approved', jobId, decision })
  })
}

export async function spawnChildren(jobId: string, children: SpawnChildSpec[]): Promise<SpawnChildrenResult> {
  return mutateJob(jobId, () => api.spawnChildJobs(jobId, children), (result) => {
    // Publish only returned children; parent and rollup come from a fresh read.
    for (const child of result.children) projectJob(child)
    emitStoreEvent({ type: 'job:spawned', parentJobId: jobId, childCount: result.spawned })
  })
}

/** Poll snapshots refresh the store without replacing the current selection. */
export async function fetchBackgroundJob(jobId: string): Promise<BackgroundJob> {
  const epoch = resetGeneration
  const readId = nextJobRead(jobId)
  let job: BackgroundJob
  try { job = await api.fetchBackgroundJob(jobId) }
  catch (error) {
    if (epoch !== resetGeneration || readId !== jobReads.get(jobId)) throw superseded()
    throw error
  }
  if (epoch !== resetGeneration || readId !== jobReads.get(jobId)) throw superseded()
  const hadPending = invalidateList()
  projectJob(job)
  if (hadPending) void loadJobList({ force: true })
  return job
}

export function mergeJobEvent(jobId: string, patch: Partial<BackgroundJob>): boolean {
  const existing = store.getState().jobs.find((job) => job.id === jobId)
  if (!existing) return false
  const hadPending = invalidateList()
  const changed = patch.status !== undefined && patch.status !== existing.status
  nextJobRead(jobId)
  // Event detail is progress text; only a complete HTTP snapshot owns result/evidence.
  const projection = {
    ...(patch.status !== undefined ? { status: patch.status } : {}),
    ...(patch.stale !== undefined ? { stale: patch.stale } : {}),
  }
  store.setState((s) => ({
    ...s, jobs: s.jobs.map((job) => job.id === jobId ? { ...job, ...projection } : job),
    currentDetail: s.currentDetail?.id === jobId ? { ...s.currentDetail, ...projection } : s.currentDetail,
  }))
  if (detailTarget === jobId && (changed || store.getState().detailState === 'loading')) void loadJobDetail(jobId)
  if (hadPending || changed) void loadJobList({ force: true })
  return true
}

export function clearJobDetail(): void {
  detailGeneration += 1
  detailTarget = ''
  store.setState((s) => ({ ...s, currentDetail: null, detailState: 'idle', detailError: '' }))
}

export function resetJobStore(): void {
  listGeneration += 1
  detailGeneration += 1
  resetGeneration += 1
  pendingList = null
  detailTarget = ''
  jobReads.clear()
  store.setState(() => initialState)
}

export function useJobStore<U>(selector: (state: JobStoreState) => U): U { return useExternalStore(store, selector) }

function eventSnapshot(job: BackgroundJob): BackgroundJob {
  return store.getState().jobs.find((item) => item.id === job.id) ?? job
}

export async function createBackgroundJobEvent(sessionId: string, payload: Parameters<typeof api.createBackgroundJob>[0]): Promise<{ result: BackgroundJobCreateResult; event: AgentEvent }> {
  const result = await createJobReceipt(payload)
  return { result, event: jobSnapshotToAgentEvent(sessionId, eventSnapshot(result.job)) }
}

export async function cancelBackgroundJobEvent(sessionId: string, jobId: string): Promise<{ result: BackgroundJobActionResult; event: AgentEvent }> {
  const result = await cancelJob(jobId)
  return { result, event: jobSnapshotToAgentEvent(sessionId, eventSnapshot(result.job)) }
}

export async function retryBackgroundJobEvent(sessionId: string, jobId: string): Promise<{ result: BackgroundJobActionResult; event: AgentEvent }> {
  const result = await retryJob(jobId)
  return { result, event: jobSnapshotToAgentEvent(sessionId, eventSnapshot(result.job)) }
}

export async function approveJobToolEvent(sessionId: string, jobId: string, eventId: string, decision: 'approved' | 'denied'): Promise<{ result: BackgroundJobActionResult; event: AgentEvent }> {
  const result = await approveJob(jobId, eventId, decision)
  return { result, event: jobSnapshotToAgentEvent(sessionId, eventSnapshot(result.job)) }
}

export async function pollBackgroundJobEvents(sessionId: string, jobId: string, onAgentEvent: (event: AgentEvent) => void, options: {
  intervalMs?: number; maxAttempts?: number; signal?: AbortSignal
  onSnapshot?: (job: BackgroundJob) => void | Promise<void>
} = {}): Promise<BackgroundJob> {
  const epoch = resetGeneration
  let lastEventId = ''
  let latestJob: BackgroundJob | undefined
  for (let attempt = 0; attempt < (options.maxAttempts ?? 120); attempt += 1) {
    if (options.signal?.aborted || epoch !== resetGeneration) throw superseded()
    const job = await fetchBackgroundJob(jobId)
    if (options.signal?.aborted || epoch !== resetGeneration) throw superseded()
    latestJob = job
    await options.onSnapshot?.(job)
    const event = jobSnapshotToAgentEvent(sessionId, job)
    if (event.id !== lastEventId) { onAgentEvent(event); lastEventId = event.id }
    if (job.status === 'complete' || job.status === 'failed' || job.status === 'cancelled') return job
    await new Promise((resolve) => window.setTimeout(resolve, options.intervalMs ?? 1200))
  }
  if (latestJob) return latestJob
  throw new Error('[job] background job polling ended before receiving a job snapshot')
}
