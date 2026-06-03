import { describe, expect, it } from 'vitest'
import { createJobRunner } from '../jobRunner'

describe('job runner', () => {
  it('queues and runs a job', async () => {
    const events: string[] = []
    const runner = createJobRunner({
      emit(event) {
        events.push(event.status)
      },
    })
    const jobId = runner.enqueue({
      title: '后台分析',
      run: async () => 'done',
    })
    await runner.runNext()
    expect(jobId).toMatch(/^job-/)
    expect(events).toEqual(['queued', 'running', 'complete'])
  })

  it('marks a failing job as failed', async () => {
    const events: string[] = []
    const runner = createJobRunner({
      emit(event) {
        events.push(event.status)
      },
    })
    runner.enqueue({
      title: '失败任务',
      run: async () => {
        throw new Error('boom')
      },
    })
    await runner.runNext()
    expect(events).toEqual(['queued', 'running', 'failed'])
  })
})
