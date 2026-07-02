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

  it('marks stale cancelled jobs with a timeout detail', () => {
    const event = jobSnapshotToAgentEvent('session-1', {
      id: 'job-1',
      title: '后台分析',
      status: 'cancelled',
      result: '',
      error: 'job stale: no progress for 900s',
      stale: true,
      createdAt: '2026-06-02T10:00:00.000Z',
      updatedAt: '2026-06-02T10:15:00.000Z',
    })

    expect(event.status).toBe('cancelled')
    expect(event.stale).toBe(true)
    expect(event.detail).toBe('任务长时间没有进展，已自动取消。job stale: no progress for 900s')
  })
})
