import { describe, expect, it } from 'vitest'
import { jobSnapshotToAgentEvent } from '../jobBridge'

describe('job bridge', () => {
  it('maps a queued backend job to a runtime job event', () => {
    const event = jobSnapshotToAgentEvent('session-1', {
      id: 'job-1',
      title: '后台分析',
      status: 'queued',
      result: '',
      createdAt: '2026-06-02T10:00:00.000Z',
      updatedAt: '2026-06-02T10:00:00.000Z',
    })

    expect(event.type).toBe('job.event')
    expect(event.jobId).toBe('job-1')
    expect(event.status).toBe('queued')
    expect(event.detail).toBe('等待后台执行')
  })

  it('uses the job result as detail when complete', () => {
    const event = jobSnapshotToAgentEvent('session-1', {
      id: 'job-1',
      title: '后台分析',
      status: 'complete',
      result: '分析完成',
      createdAt: '2026-06-02T10:00:00.000Z',
      updatedAt: '2026-06-02T10:01:00.000Z',
    })

    expect(event.status).toBe('complete')
    expect(event.detail).toBe('分析完成')
    expect(event.id).toContain('job-job-1-complete-')
  })

  it('uses the error as detail when failed', () => {
    const event = jobSnapshotToAgentEvent('session-1', {
      id: 'job-1',
      title: '后台分析',
      status: 'failed',
      result: '',
      error: 'boom',
      createdAt: '2026-06-02T10:00:00.000Z',
      updatedAt: '2026-06-02T10:01:00.000Z',
    })

    expect(event.status).toBe('failed')
    expect(event.detail).toBe('boom')
  })
})
