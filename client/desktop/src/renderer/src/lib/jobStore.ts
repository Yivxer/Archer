/**
 * L3.5 — jobStore
 *
 * 真值来源：/jobs + /jobs/{id} + cancel/retry/approve/spawn 动作
 * 订阅者：TasksPage、ChatPage 回执、Workspace
 *
 * 注意：runtimeStore 的 state.jobs 是 JobEvent（SSE 事件），
 *      jobStore 的 state.jobs 是 BackgroundJob（API 拉取）。
 *      两者并存，jobStore 是页面消费的真值。
 *
 * 契约：docs/api-contract.md §「jobStore（L3.5）」
 */

import {
  approveJobTool,
  cancelBackgroundJob,
  createBackgroundJob,
  fetchBackgroundJob,
  listBackgroundJobs,
  retryBackgroundJob,
  spawnChildJobs,
} from '../adapters/localArcher'
import type { BackgroundJob } from '../types'
import { createExternalStore, useExternalStore, type LoadState } from './externalStore'
import { emitStoreEvent } from './storeEventBus'

// ───────────────────────── State ─────────────────────────

export type JobStoreState = {
  jobs: BackgroundJob[]
  currentDetail: BackgroundJob | null
  loadState: LoadState
  detailState: LoadState
  error: string
  busyIds: Set<string>
}

const initialState: JobStoreState = {
  jobs: [],
  currentDetail: null,
  loadState: 'idle',
  detailState: 'idle',
  error: '',
  busyIds: new Set(),
}

// ───────────────────────── Store 单例 ─────────────────────────

const store = createExternalStore<JobStoreState>(initialState)

export function getJobStoreState(): JobStoreState {
  return store.getState()
}

export function subscribeJobStore(listener: () => void): () => void {
  return store.subscribe(listener)
}

// ───────────────────────── 内部辅助 ─────────────────────────

/** 把单个 job 替换到 jobs 列表（按 id 匹配），不存在则追加 */
function upsertJob(state: JobStoreState, job: BackgroundJob): BackgroundJob[] {
  const idx = state.jobs.findIndex((j) => j.id === job.id)
  if (idx === -1) return [...state.jobs, job]
  return state.jobs.map((j) => (j.id === job.id ? job : j))
}

// ───────────────────────── Actions ─────────────────────────

/**
 * 加载 job 列表。
 */
export async function loadJobList(): Promise<void> {
  store.setState((s) => ({ ...s, loadState: 'loading', error: '' }))
  try {
    const result = await listBackgroundJobs()
    store.setState((s) => ({
      ...s,
      jobs: result.jobs,
      loadState: 'ready',
      error: '',
    }))
  } catch (err) {
    store.setState((s) => ({
      ...s,
      loadState: 'error',
      error: err instanceof Error ? err.message : String(err),
    }))
  }
}

/**
 * 加载 job 详情（含 children）。
 */
export async function loadJobDetail(jobId: string): Promise<void> {
  store.setState((s) => ({ ...s, detailState: 'loading', error: '' }))
  try {
    const job = await fetchBackgroundJob(jobId)
    store.setState((s) => ({
      ...s,
      currentDetail: job,
      detailState: 'ready',
      error: '',
    }))
  } catch (err) {
    store.setState((s) => ({
      ...s,
      detailState: 'error',
      error: err instanceof Error ? err.message : String(err),
    }))
  }
}

/**
 * 创建 job。
 */
export async function createJob(
  payload: { title: string; kind: string; prompt: string; autoStart?: boolean; timeoutSeconds?: number; parentJobId?: string },
): Promise<BackgroundJob | null> {
  try {
    const result = await createBackgroundJob(payload)
    // 创建后 refresh 列表
    await loadJobList()
    // L3.7: 通知跨 store 联动（job 可能产生新会话）
    emitStoreEvent({ type: 'job:created', jobId: result.job.id })
    return result.job
  } catch (err) {
    store.setState((s) => ({
      ...s,
      error: err instanceof Error ? err.message : String(err),
    }))
    return null
  }
}

/**
 * 取消 job。
 */
export async function cancelJob(jobId: string): Promise<void> {
  store.setState((s) => ({
    ...s,
    busyIds: new Set([...s.busyIds, jobId]),
  }))
  try {
    const result = await cancelBackgroundJob(jobId)
    store.setState((s) => ({
      ...s,
      jobs: upsertJob(s, result.job),
      busyIds: new Set([...s.busyIds].filter((id) => id !== jobId)),
    }))
    // L3.7: 通知跨 store 联动
    emitStoreEvent({ type: 'job:cancelled', jobId })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      busyIds: new Set([...s.busyIds].filter((id) => id !== jobId)),
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

/**
 * 重试 job（成功后 600ms 延迟 refresh，与原 TasksPage 逻辑一致）。
 */
export async function retryJob(jobId: string): Promise<void> {
  store.setState((s) => ({
    ...s,
    busyIds: new Set([...s.busyIds, jobId]),
  }))
  try {
    const result = await retryBackgroundJob(jobId)
    store.setState((s) => ({
      ...s,
      jobs: upsertJob(s, result.job),
      busyIds: new Set([...s.busyIds].filter((id) => id !== jobId)),
    }))
    // L3.7: 通知跨 store 联动
    emitStoreEvent({ type: 'job:retried', jobId })
    // 600ms 后 refresh 列表（等后端状态稳定）
    setTimeout(() => {
      loadJobList().catch(() => {})
    }, 600)
  } catch (err) {
    store.setState((s) => ({
      ...s,
      busyIds: new Set([...s.busyIds].filter((id) => id !== jobId)),
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

/**
 * 审批 job 的待确认工具。
 */
export async function approveJob(
  jobId: string,
  eventId: string,
  decision: 'approved' | 'denied',
): Promise<void> {
  store.setState((s) => ({
    ...s,
    busyIds: new Set([...s.busyIds, jobId]),
  }))
  try {
    const result = await approveJobTool(jobId, eventId, decision)
    store.setState((s) => ({
      ...s,
      jobs: upsertJob(s, result.job),
      busyIds: new Set([...s.busyIds].filter((id) => id !== jobId)),
    }))
    // L3.7: 通知跨 store 联动
    emitStoreEvent({ type: 'job:approved', jobId, decision })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      busyIds: new Set([...s.busyIds].filter((id) => id !== jobId)),
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

/**
 * 派生子 job。
 */
export async function spawnChildren(
  jobId: string,
  children: { title: string; kind: string; prompt: string; timeoutSeconds?: number; isolated?: boolean }[],
): Promise<void> {
  store.setState((s) => ({
    ...s,
    busyIds: new Set([...s.busyIds, jobId]),
  }))
  try {
    await spawnChildJobs(jobId, children)
    // spawn 返回 SpawnChildrenResult（含 children 数组，无 parent job），
    // 直接 refresh 列表拿到更新后的 parent + children
    store.setState((s) => ({
      ...s,
      busyIds: new Set([...s.busyIds].filter((id) => id !== jobId)),
    }))
    await loadJobList()
    // L3.7: 通知跨 store 联动
    emitStoreEvent({ type: 'job:spawned', parentJobId: jobId, childCount: children.length })
  } catch (err) {
    store.setState((s) => ({
      ...s,
      busyIds: new Set([...s.busyIds].filter((id) => id !== jobId)),
      error: err instanceof Error ? err.message : String(err),
    }))
    throw err
  }
}

/**
 * 由 SSE JobEvent 合并到 jobs 列表（runtimeStore 的 JobEvent → BackgroundJob 桶）。
 *
 * 注意：JobEvent 和 BackgroundJob 字段不完全一致，这里只更新 status/detail/stale。
 */
export function mergeJobEvent(jobId: string, patch: Partial<BackgroundJob>): void {
  store.setState((s) => {
    const idx = s.jobs.findIndex((j) => j.id === jobId)
    if (idx === -1) return s // 列表里没有，忽略（等下次 loadJobList）
    const jobs = s.jobs.map((j) => (j.id === jobId ? { ...j, ...patch } : j))
    return { ...s, jobs }
  })
}

/**
 * 清空 currentDetail。
 */
export function clearJobDetail(): void {
  store.setState((s) => ({ ...s, currentDetail: null, detailState: 'idle' }))
}

/**
 * 重置 store。
 */
export function resetJobStore(): void {
  store.setState(() => initialState)
}

// ───────────────────────── React hook ─────────────────────────

export function useJobStore<U>(selector: (state: JobStoreState) => U): U {
  return useExternalStore(store, selector)
}
