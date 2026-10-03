import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, expect, it, vi } from 'vitest'
import { TasksPage } from './TasksPage'
import { getJobStoreState, loadJobDetail, loadJobList, mergeJobItems, resetJobStore } from '../lib/jobStore'
import * as api from '../adapters/jobAdapter'
import type { BackgroundJob } from '../types'

vi.mock('../adapters/jobAdapter', () => ({ listBackgroundJobs: vi.fn(), fetchBackgroundJob: vi.fn() }))
const job: BackgroundJob = { id: 'synthetic-task', title: '合成后台任务', kind: 'chat', prompt: '合成输入', status: 'failed', result: '', error: '合成失败', createdAt: '2026-10-03', updatedAt: '2026-10-03' }
const render = (connected = true) => renderToStaticMarkup(<TasksPage connected={connected} />)

beforeEach(() => { resetJobStore(); vi.resetAllMocks() })

it('keeps readable tasks and disables mutations when the list refresh fails', async () => {
  mergeJobItems([job]); vi.mocked(api.fetchBackgroundJob).mockResolvedValue(job)
  await loadJobDetail(job.id)
  vi.mocked(api.listBackgroundJobs).mockRejectedValue(new Error('synthetic unavailable'))
  await loadJobList()
  const html = render()
  expect(html).toContain('合成后台任务')
  expect(html).toContain('任务列表刷新失败')
  expect(html).toMatch(/disabled=""[^>]*>重试/)
  expect(getJobStoreState().jobs).toHaveLength(1)
})

it('enables actions only with a successful list and matching detail', async () => {
  mergeJobItems([job])
  expect(render()).toMatch(/disabled=""[^>]*>重试/)
  vi.mocked(api.fetchBackgroundJob).mockResolvedValue(job)
  await loadJobDetail(job.id)
  expect(render()).not.toMatch(/disabled=""[^>]*>重试/)
})

it('shows the connection state and distinguishes loading from an empty success', () => {
  expect(render(false)).toContain('等待连接')
  expect(render()).toContain('正在读取任务')
  mergeJobItems([])
  expect(render()).toContain('暂无后台任务')
})
