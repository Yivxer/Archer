import type {
  RuntimeCancellationResult,
  RuntimeRecoveryItem,
  RuntimeRun,
  RuntimeRunListResult,
  TaskPlanJobBindingResult,
  TaskPlanJobObservationResult,
  TaskPlanLifecycleStatus,
  TaskPlanObservationResult,
  RuntimeVerificationRetryResult,
} from '../types'
import { getJson, postJson } from './localArcher'

export type PythonRuntimeRun = {
  id: string
  objective: string
  source: string
  state: RuntimeRun['state']
  current_step_id?: string | null
  created_at: string
  updated_at: string
}

export type PythonRuntimeRecoveryItem = {
  run_id: string
  original_state: RuntimeRun['state']
  classification: RuntimeRecoveryItem['classification']
  reason: string
  adapter?: string | null
  checkpoint_id?: string | null
  attempted: boolean
  resulting_state?: RuntimeRun['state'] | null
  verification_status?: RuntimeRecoveryItem['verificationStatus'] | null
}

export function normalizeRuntimeRecoveryItem(
  item: PythonRuntimeRecoveryItem,
): RuntimeRecoveryItem {
  return {
    runId: item.run_id,
    originalState: item.original_state,
    classification: item.classification,
    reason: item.reason,
    adapter: item.adapter || undefined,
    checkpointId: item.checkpoint_id || undefined,
    attempted: item.attempted,
    resultingState: item.resulting_state || undefined,
    verificationStatus: item.verification_status || undefined,
  }
}

export function normalizeRuntimeRun(
  run: PythonRuntimeRun,
  recovery?: RuntimeRecoveryItem,
): RuntimeRun {
  return {
    id: run.id,
    objective: run.objective,
    source: run.source,
    state: run.state,
    currentStepId: run.current_step_id || undefined,
    recovery,
    createdAt: run.created_at,
    updatedAt: run.updated_at,
  }
}

export async function listRuntimeRuns(): Promise<RuntimeRunListResult> {
  const result = await getJson<
    Omit<RuntimeRunListResult, 'runs' | 'recovery'> & {
      runs: PythonRuntimeRun[]
      recovery: {
        counts: RuntimeRunListResult['recovery']['counts']
        items: PythonRuntimeRecoveryItem[]
      }
    }
  >('/runtime/runs')
  const recoveryItems = result.recovery.items.map(normalizeRuntimeRecoveryItem)
  const recoveryByRunId = new Map(
    recoveryItems.map((item) => [item.runId, item]),
  )
  return {
    ...result,
    runs: result.runs.map((run) => normalizeRuntimeRun(
      run,
      recoveryByRunId.get(run.id),
    )),
    recovery: {
      ...result.recovery,
      items: recoveryItems,
    },
  }
}

export async function retryRuntimeVerification(
  runId: string,
): Promise<RuntimeVerificationRetryResult> {
  const result = await postJson<
    Omit<RuntimeVerificationRetryResult, 'run'> & { run: PythonRuntimeRun }
  >(`/runtime/runs/${encodeURIComponent(runId)}/resume`, {})
  return { ...result, run: normalizeRuntimeRun(result.run) }
}

export async function requestRuntimeCancellation(
  runId: string,
): Promise<RuntimeCancellationResult> {
  const result = await postJson<
    Omit<RuntimeCancellationResult, 'run'> & { run: PythonRuntimeRun }
  >(`/runtime/runs/${encodeURIComponent(runId)}/cancel`, {})
  return { ...result, run: normalizeRuntimeRun(result.run) }
}

export async function observeTaskPlanShadow(
  runId: string,
  input: {
    planId: string
    traceId: string
    status: TaskPlanLifecycleStatus
    observedAt: string
  },
): Promise<TaskPlanObservationResult> {
  const result = await postJson<
    Omit<TaskPlanObservationResult, 'run'> & { run: PythonRuntimeRun }
  >(`/runtime/task-plan-shadows/${encodeURIComponent(runId)}/observe`, input)
  return { ...result, run: normalizeRuntimeRun(result.run) }
}

export async function bindTaskPlanShadowJob(
  runId: string,
  input: {
    planId: string
    jobId: string
    jobKind: string
    boundAt: string
  },
): Promise<TaskPlanJobBindingResult> {
  const result = await postJson<
    Omit<TaskPlanJobBindingResult, 'run'> & { run: PythonRuntimeRun }
  >(`/runtime/task-plan-shadows/${encodeURIComponent(runId)}/jobs/bind`, input)
  return { ...result, run: normalizeRuntimeRun(result.run) }
}

export async function observeTaskPlanShadowJob(
  runId: string,
  jobId: string,
  input: {
    status: TaskPlanJobObservationResult['observation']['legacy_status']
    jobUpdatedAt: string
    observedAt: string
    evidenceSummary?: TaskPlanJobObservationResult['observation']['evidence_summary']
  },
): Promise<TaskPlanJobObservationResult> {
  return postJson<TaskPlanJobObservationResult>(
    `/runtime/task-plan-shadows/${encodeURIComponent(runId)}/jobs/${encodeURIComponent(jobId)}/observe`,
    input,
  )
}
