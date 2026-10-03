import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { BackgroundJob, BackgroundJobListResult } from '../../types'
import * as api from '../../adapters/jobAdapter'
import { cancelJob, clearJobDetail, createBackgroundJobEvent, fetchBackgroundJob, getJobStoreState, loadJobDetail, loadJobList, mergeJobEvent, mergeJobItems, resetJobStore, spawnChildren } from '../jobStore'

vi.mock('../../adapters/jobAdapter', () => ({
  listBackgroundJobs: vi.fn(), fetchBackgroundJob: vi.fn(), createBackgroundJob: vi.fn(),
  cancelBackgroundJob: vi.fn(), retryBackgroundJob: vi.fn(), approveJobTool: vi.fn(), spawnChildJobs: vi.fn(),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
const job = (status: BackgroundJob['status'] = 'queued', id = 'job-1'): BackgroundJob => ({ id, title: '合成任务', kind: 'chat', prompt: '合成输入', status, result: '', createdAt: '2026-10-03', updatedAt: '2026-10-03' })
const listing = (...jobs: BackgroundJob[]): BackgroundJobListResult => ({ ok: true, jobs })

beforeEach(() => {
  resetJobStore(); vi.resetAllMocks()
  vi.mocked(api.listBackgroundJobs).mockResolvedValue(listing(job()))
})

describe('job store concurrency and receipts', () => {
  it('force refresh isolates an older successful response', async () => {
    const old = deferred<BackgroundJobListResult>()
    vi.mocked(api.listBackgroundJobs).mockReturnValueOnce(old.promise).mockResolvedValueOnce(listing(job('complete')))
    const first = loadJobList(); await loadJobList({ force: true }); old.resolve(listing(job())); await first
    expect(getJobStoreState().jobs[0].status).toBe('complete')
  })

  it('reset prevents a pending list from repopulating the store', async () => {
    const old = deferred<BackgroundJobListResult>()
    vi.mocked(api.listBackgroundJobs).mockReturnValueOnce(old.promise)
    const pending = loadJobList(); resetJobStore(); old.resolve(listing(job())); await pending
    expect(getJobStoreState().jobs).toEqual([])
    expect(getJobStoreState().loadState).toBe('idle')
  })

  it('clearing a detail makes its late response ineffective', async () => {
    const old = deferred<BackgroundJob>()
    vi.mocked(api.fetchBackgroundJob).mockReturnValueOnce(old.promise)
    const pending = loadJobDetail('job-1'); clearJobDetail(); old.resolve(job()); await pending
    expect(getJobStoreState().currentDetail).toBeNull()
    expect(getJobStoreState().detailState).toBe('idle')
  })

  it('a pre-cancel list cannot overwrite the confirmed cancellation', async () => {
    mergeJobItems([job()]); const old = deferred<BackgroundJobListResult>()
    vi.mocked(api.listBackgroundJobs).mockReturnValueOnce(old.promise).mockResolvedValueOnce(listing(job('cancelled')))
    const pending = loadJobList()
    vi.mocked(api.cancelBackgroundJob).mockResolvedValue({ ok: true, job: job('cancelled'), message: '已取消' })
    await cancelJob('job-1'); old.resolve(listing(job())); await pending
    expect(getJobStoreState().jobs[0].status).toBe('cancelled')
  })

  it('spawn refreshes selected parent details from the server', async () => {
    const parent = job(); mergeJobItems([parent])
    vi.mocked(api.fetchBackgroundJob).mockResolvedValueOnce(parent)
    await loadJobDetail(parent.id)
    const refreshed = { ...parent, childJobIds: ['child-1'], children: [job('queued', 'child-1')] }
    vi.mocked(api.spawnChildJobs).mockResolvedValue({ ok: true, id: parent.id, spawned: 1, children: [job('queued', 'child-1')] })
    vi.mocked(api.listBackgroundJobs).mockResolvedValue(listing(refreshed))
    vi.mocked(api.fetchBackgroundJob).mockResolvedValue(refreshed)
    await spawnChildren(parent.id, [{ title: '子任务', prompt: '合成' }])
    expect(getJobStoreState().currentDetail?.childJobIds).toEqual(['child-1'])
  })

  it('an ok=false cancellation never publishes a fake success', async () => {
    mergeJobItems([job()])
    vi.mocked(api.cancelBackgroundJob).mockResolvedValue({ ok: false, job: job('cancelled'), message: '未取消' })
    await expect(cancelJob('job-1')).rejects.toThrow()
    expect(getJobStoreState().jobs[0].status).toBe('queued')
  })

  it('normal concurrent lists share a request; old failures cannot erase a forced success', async () => {
    const old = deferred<BackgroundJobListResult>()
    vi.mocked(api.listBackgroundJobs).mockReturnValueOnce(old.promise).mockResolvedValueOnce(listing(job('complete')))
    const first = loadJobList(); const shared = loadJobList()
    expect(api.listBackgroundJobs).toHaveBeenCalledTimes(1)
    await loadJobList({ force: true }); old.reject(new Error('old read')); await Promise.all([first, shared])
    expect(getJobStoreState().loadState).toBe('ready')
    expect(getJobStoreState().listError).toBe('')
  })

  it('a failed refresh keeps the confirmed cancellation and does not repeat its POST', async () => {
    mergeJobItems([job()])
    vi.mocked(api.cancelBackgroundJob).mockResolvedValue({ ok: true, job: job('cancelled'), message: '已取消' })
    vi.mocked(api.listBackgroundJobs).mockRejectedValue(new Error('read unavailable'))
    await expect(cancelJob('job-1')).resolves.toMatchObject({ ok: true })
    expect(getJobStoreState().jobs[0].status).toBe('cancelled')
    expect(getJobStoreState().listError).toBe('read unavailable')
    expect(getJobStoreState().actionError).toBe('')
    expect(getJobStoreState().busyIds.size).toBe(0)
    expect(api.cancelBackgroundJob).toHaveBeenCalledTimes(1)
  })

  it('two clicks on the same busy task cause one mutation', async () => {
    const pending = deferred<Awaited<ReturnType<typeof api.cancelBackgroundJob>>>()
    vi.mocked(api.cancelBackgroundJob).mockReturnValueOnce(pending.promise)
    const first = cancelJob('job-1')
    await expect(cancelJob('job-1')).rejects.toThrow('正在处理')
    pending.resolve({ ok: true, job: job('cancelled'), message: '已取消' }); await first
    expect(api.cancelBackgroundJob).toHaveBeenCalledTimes(1)
    expect(getJobStoreState().busyIds.size).toBe(0)
  })

  it('a reset during a write prevents receipt, refresh and busy cleanup from repopulating state', async () => {
    const pending = deferred<Awaited<ReturnType<typeof api.cancelBackgroundJob>>>()
    vi.mocked(api.cancelBackgroundJob).mockReturnValueOnce(pending.promise)
    const first = cancelJob('job-1'); resetJobStore()
    pending.resolve({ ok: true, job: job('cancelled'), message: '已取消' }); await first
    expect(getJobStoreState().jobs).toEqual([])
    expect(getJobStoreState().loadState).toBe('idle')
    expect(api.listBackgroundJobs).not.toHaveBeenCalled()
  })

  it('switching detail ignores both an old success and an old error', async () => {
    for (const fail of [false, true]) {
      const old = deferred<BackgroundJob>()
      vi.mocked(api.fetchBackgroundJob).mockReturnValueOnce(old.promise).mockResolvedValueOnce(job('complete', 'job-2'))
      const first = loadJobDetail('job-1'); await loadJobDetail('job-2')
      if (fail) old.reject(new Error('old detail')); else old.resolve(job())
      await first
      expect(getJobStoreState().currentDetail?.id).toBe('job-2')
      expect(getJobStoreState().detailError).toBe('')
    }
  })

  it('a poll that started before cancellation cannot resurrect the queued status', async () => {
    mergeJobItems([job()]); const pending = deferred<BackgroundJob>()
    vi.mocked(api.fetchBackgroundJob).mockReturnValueOnce(pending.promise)
    const poll = fetchBackgroundJob('job-1')
    const rejected = expect(poll).rejects.toMatchObject({ name: 'AbortError' })
    vi.mocked(api.cancelBackgroundJob).mockResolvedValue({ ok: true, job: job('cancelled'), message: '已取消' })
    vi.mocked(api.listBackgroundJobs).mockResolvedValue(listing(job('cancelled')))
    await cancelJob('job-1'); pending.resolve(job()); await rejected
    expect(getJobStoreState().jobs[0].status).toBe('cancelled')
  })

  it('passive detail selection does not abort a chat poll for the same task', async () => {
    const pending = deferred<BackgroundJob>()
    vi.mocked(api.fetchBackgroundJob).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(job('running'))
    const poll = fetchBackgroundJob('job-1'); await loadJobDetail('job-1')
    pending.resolve(job('complete'))
    await expect(poll).resolves.toMatchObject({ status: 'complete' })
    expect(getJobStoreState().currentDetail?.status).toBe('complete')
  })

  it('a newer server event prevents a pre-event list from rolling it back', async () => {
    mergeJobItems([job()]); const pending = deferred<BackgroundJobListResult>()
    vi.mocked(api.listBackgroundJobs).mockReturnValueOnce(pending.promise).mockResolvedValue(listing(job('complete')))
    const list = loadJobList(); mergeJobEvent('job-1', { status: 'complete' })
    pending.resolve(listing(job())); await list; await loadJobList()
    expect(getJobStoreState().jobs[0].status).toBe('complete')
  })

  it('event progress cannot replace the server result or its evidence', () => {
    const confirmed = { ...job('complete'), result: '服务端已验证结果' }
    mergeJobItems([confirmed]); mergeJobEvent('job-1', { status: 'complete', result: '事件进度摘要' })
    expect(getJobStoreState().jobs[0].result).toBe('服务端已验证结果')
  })

  it('the chat receipt event uses the newer server read instead of the original queued receipt', async () => {
    vi.mocked(api.createBackgroundJob).mockResolvedValue({ ok: true, job: job() })
    vi.mocked(api.listBackgroundJobs).mockResolvedValue(listing(job('complete')))
    const { event } = await createBackgroundJobEvent('synthetic-session', { title: '合成', prompt: '合成' })
    expect(event).toMatchObject({ type: 'job.event', status: 'complete' })
    expect(getJobStoreState().jobs[0].status).toBe('complete')
  })
})
