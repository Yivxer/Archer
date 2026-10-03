import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cancelBackgroundJob, createBackgroundJob, fetchBackgroundJob, listBackgroundJobs } from '../jobAdapter'

beforeEach(() => {
  vi.stubGlobal('localStorage', { getItem: () => 'synthetic-token' })
  vi.stubGlobal('window', {})
})
afterEach(() => vi.unstubAllGlobals())

it('uses the shared authentication and real GET envelope / POST receipt contracts', async () => {
  const job = { id: 'synthetic/id', status: 'cancelled' }
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url).pathname
    if (!init?.method) return new Response(JSON.stringify({ contractVersion: 1, data: path === '/jobs' ? { ok: true, jobs: [job] } : { ok: true, job } }))
    return new Response(JSON.stringify({ contractVersion: 1, ok: true, job, message: '已取消' }))
  })
  vi.stubGlobal('fetch', fetcher)
  expect(await listBackgroundJobs()).toMatchObject({ ok: true, jobs: [job] })
  expect(await fetchBackgroundJob(job.id)).toEqual(job)
  expect(await createBackgroundJob({ title: '合成任务', prompt: '合成输入', autoStart: false })).toMatchObject({ ok: true, job })
  expect(await cancelBackgroundJob(job.id)).toMatchObject({ ok: true, job, message: '已取消' })
  expect(String(fetcher.mock.calls[3][0])).toContain('/jobs/synthetic%2Fid/cancel')
  expect(new Headers(fetcher.mock.calls[3][1]?.headers).get('Authorization')).toBe('Bearer synthetic-token')
  expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body))).toMatchObject({ autoStart: false })
})

it('missing details remain errors rather than ready with an undefined job', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ contractVersion: 1, data: { ok: false } }))))
  await expect(fetchBackgroundJob('missing')).rejects.toThrow('任务详情未读取成功')
})
