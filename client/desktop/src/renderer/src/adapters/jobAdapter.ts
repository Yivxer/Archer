/** Background-job HTTP only; store owns receipts, polling and projection. */
import { getJson, postJson } from './localArcher'
import type { BackgroundJob, BackgroundJobActionResult, BackgroundJobCreateResult, BackgroundJobListResult } from '../types'

export async function createBackgroundJob(payload: {
  title: string
  kind?: string
  prompt: string
  autoStart?: boolean
  timeoutSeconds?: number
  runtimeShadowRunId?: string
  vaultArgs?: {
    note_path: string
    force: false
  }
}): Promise<BackgroundJobCreateResult> {
  return postJson<BackgroundJobCreateResult>('/jobs', payload)
}

export async function listBackgroundJobs(): Promise<BackgroundJobListResult> {
  return getJson<BackgroundJobListResult>('/jobs')
}

export async function fetchBackgroundJob(jobId: string): Promise<BackgroundJob> {
  const result = await getJson<BackgroundJobCreateResult>(`/jobs/${encodeURIComponent(jobId)}`)
  if (!result.ok || !result.job) throw new Error('任务详情未读取成功，请刷新后重试')
  return result.job
}

export async function cancelBackgroundJob(jobId: string): Promise<BackgroundJobActionResult> {
  return postJson<BackgroundJobActionResult>(`/jobs/${encodeURIComponent(jobId)}/cancel`, {})
}

export async function retryBackgroundJob(jobId: string): Promise<BackgroundJobActionResult> {
  return postJson<BackgroundJobActionResult>(`/jobs/${encodeURIComponent(jobId)}/retry`, {})
}

export async function approveJobTool(
  jobId: string,
  eventId: string,
  decision: 'approved' | 'denied'
): Promise<BackgroundJobActionResult> {
  return postJson<BackgroundJobActionResult>(`/jobs/${encodeURIComponent(jobId)}/approve`, { eventId, decision })
}

export type SpawnChildSpec = {
  title: string
  kind?: string
  prompt: string
  autoStart?: boolean
  timeoutSeconds?: number
}

export type SpawnChildrenResult = {
  ok: boolean
  id: string
  spawned: number
  children: BackgroundJob[]
}

export async function spawnChildJobs(
  jobId: string,
  children: SpawnChildSpec[]
): Promise<SpawnChildrenResult> {
  return postJson<SpawnChildrenResult>(`/jobs/${encodeURIComponent(jobId)}/spawn`, { children })
}

