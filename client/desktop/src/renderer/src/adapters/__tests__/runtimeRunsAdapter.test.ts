import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  postJson: vi.fn(),
}))

vi.mock('../localArcher', () => ({
  getJson: vi.fn(),
  postJson: mocks.postJson,
}))

import {
  bindTaskPlanShadowJob,
  normalizeRuntimeRecoveryItem,
  normalizeRuntimeRun,
  observeTaskPlanShadowJob,
  observeTaskPlanShadow,
} from '../runtimeRunsAdapter'

describe('runtimeRunsAdapter', () => {
  beforeEach(() => {
    mocks.postJson.mockReset()
  })

  it('projects Python recovery evidence onto the Runtime Run', () => {
    const recovery = normalizeRuntimeRecoveryItem({
      run_id: 'run-1',
      original_state: 'uncertain',
      classification: 'invalid',
      reason: 'cursor_version_unsupported',
      adapter: null,
      checkpoint_id: 'checkpoint-1',
      attempted: false,
      resulting_state: null,
      verification_status: null,
    })
    const run = normalizeRuntimeRun({
      id: 'run-1',
      objective: '恢复既有产物',
      source: 'desktop.obsidian_write',
      state: 'uncertain',
      current_step_id: 'step-1',
      created_at: '2026-07-25T12:00:00+08:00',
      updated_at: '2026-07-25T12:01:00+08:00',
    }, recovery)

    expect(run.recovery).toEqual({
      runId: 'run-1',
      originalState: 'uncertain',
      classification: 'invalid',
      reason: 'cursor_version_unsupported',
      adapter: undefined,
      checkpointId: 'checkpoint-1',
      attempted: false,
      resultingState: undefined,
      verificationStatus: undefined,
    })
    expect(run.currentStepId).toBe('step-1')
  })

  it('posts legacy lifecycle observations to the shadow-only API', async () => {
    mocks.postJson.mockResolvedValue({
      ok: true,
      runContractVersion: 1,
      run: {
        id: 'run-plan-1',
        objective: '旧计划',
        source: 'shadow.task_plan',
        state: 'waiting_user',
        created_at: '2026-07-25T11:00:00+08:00',
        updated_at: '2026-07-25T11:00:00+08:00',
      },
      observation: {
        id: 'observation-1',
        run_id: 'run-plan-1',
        plan_id: 'plan-1',
        trace_id: 'trace-plan-1',
        legacy_status: 'accepted',
        handoff: 'legacy_job_unmigrated',
        runtime_execution_claimed: false,
        observed_at: '2026-07-25T11:01:00+08:00',
      },
    })

    const result = await observeTaskPlanShadow('run-plan-1', {
      planId: 'plan-1',
      traceId: 'trace-plan-1',
      status: 'accepted',
      observedAt: '2026-07-25T11:01:00+08:00',
    })

    expect(mocks.postJson).toHaveBeenCalledWith(
      '/runtime/task-plan-shadows/run-plan-1/observe',
      {
        planId: 'plan-1',
        traceId: 'trace-plan-1',
        status: 'accepted',
        observedAt: '2026-07-25T11:01:00+08:00',
      },
    )
    expect(result.run.source).toBe('shadow.task_plan')
    expect(result.observation.runtime_execution_claimed).toBe(false)
  })

  it('posts legacy Job binding and status evidence to shadow-only APIs', async () => {
    mocks.postJson
      .mockResolvedValueOnce({
        ok: true,
        runContractVersion: 1,
        run: {
          id: 'run-plan-1',
          objective: '旧计划',
          source: 'shadow.task_plan',
          state: 'waiting_user',
          created_at: '2026-07-25T11:00:00+08:00',
          updated_at: '2026-07-25T11:00:00+08:00',
        },
        binding: {
          id: 'binding-1',
          run_id: 'run-plan-1',
          plan_id: 'plan-1',
          legacy_job_id: 'job-1',
          job_kind: 'chat',
          runtime_execution_claimed: false,
          bound_at: '2026-07-25T11:02:00+08:00',
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        runContractVersion: 1,
        observation: {
          id: 'job-observation-1',
          binding_id: 'binding-1',
          run_id: 'run-plan-1',
          legacy_job_id: 'job-1',
          legacy_status: 'running',
          job_updated_at: '2026-07-25T11:02:01+08:00',
          observed_at: '2026-07-25T11:02:02+08:00',
          verification_receipt_id: 'job-verification-1',
          evidence_summary: {
            artifactId: 'job-result-1',
            verificationId: 'job-verification-1',
            verificationStatus: 'verified',
            outcomeVerificationId: 'job-outcome-1',
            outcomeStatus: 'uncertain',
            outcomeVerifier: 'legacy_job.outcome.v1',
            outcomeReason: 'no_deterministic_verifier_for_kind',
          },
          runtime_state_changed: false,
        },
      })

    const binding = await bindTaskPlanShadowJob('run-plan-1', {
      planId: 'plan-1',
      jobId: 'job-1',
      jobKind: 'chat',
      boundAt: '2026-07-25T11:02:00+08:00',
    })
    const observation = await observeTaskPlanShadowJob(
      'run-plan-1',
      'job-1',
      {
        status: 'running',
        jobUpdatedAt: '2026-07-25T11:02:01+08:00',
        observedAt: '2026-07-25T11:02:02+08:00',
        evidenceSummary: {
          artifactId: 'job-result-1',
          verificationId: 'job-verification-1',
          verificationStatus: 'verified',
          outcomeVerificationId: 'job-outcome-1',
          outcomeStatus: 'uncertain',
          outcomeVerifier: 'legacy_job.outcome.v1',
          outcomeReason: 'no_deterministic_verifier_for_kind',
        },
      },
    )

    expect(mocks.postJson).toHaveBeenNthCalledWith(
      1,
      '/runtime/task-plan-shadows/run-plan-1/jobs/bind',
      {
        planId: 'plan-1',
        jobId: 'job-1',
        jobKind: 'chat',
        boundAt: '2026-07-25T11:02:00+08:00',
      },
    )
    expect(mocks.postJson).toHaveBeenNthCalledWith(
      2,
      '/runtime/task-plan-shadows/run-plan-1/jobs/job-1/observe',
      {
        status: 'running',
        jobUpdatedAt: '2026-07-25T11:02:01+08:00',
        observedAt: '2026-07-25T11:02:02+08:00',
        evidenceSummary: {
          artifactId: 'job-result-1',
          verificationId: 'job-verification-1',
          verificationStatus: 'verified',
          outcomeVerificationId: 'job-outcome-1',
          outcomeStatus: 'uncertain',
          outcomeVerifier: 'legacy_job.outcome.v1',
          outcomeReason: 'no_deterministic_verifier_for_kind',
        },
      },
    )
    expect(binding.run.state).toBe('waiting_user')
    expect(binding.binding.runtime_execution_claimed).toBe(false)
    expect(observation.observation.runtime_state_changed).toBe(false)
  })
})
