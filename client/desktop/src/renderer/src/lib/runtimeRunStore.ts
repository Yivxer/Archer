import {
  listRuntimeRuns,
  requestRuntimeCancellation,
  retryRuntimeVerification,
} from '../adapters/runtimeRunsAdapter'
import type { RuntimeRun } from '../types'
import { createExternalStore, useExternalStore, type LoadState } from './externalStore'

export type RuntimeRunStoreState = {
  runs: RuntimeRun[]
  loadState: LoadState
  error: string
}

const initialState: RuntimeRunStoreState = {
  runs: [],
  loadState: 'idle',
  error: '',
}

const store = createExternalStore<RuntimeRunStoreState>(initialState)
let loadInFlight: Promise<void> | null = null

export function getRuntimeRunStoreState(): RuntimeRunStoreState {
  return store.getState()
}

export async function loadRuntimeRuns(): Promise<void> {
  if (loadInFlight) return loadInFlight
  const run = (async () => {
    store.setState((state) => ({ ...state, loadState: 'loading', error: '' }))
    try {
      const result = await listRuntimeRuns()
      store.setState(() => ({
        runs: result.runs,
        loadState: 'ready',
        error: '',
      }))
    } catch (error) {
      store.setState((state) => ({
        ...state,
        loadState: 'error',
        error: error instanceof Error ? error.message : String(error),
      }))
    }
  })()
  loadInFlight = run
  try {
    await run
  } finally {
    if (loadInFlight === run) loadInFlight = null
  }
}

export async function retryRuntimeRun(runId: string): Promise<void> {
  try {
    await retryRuntimeVerification(runId)
    await loadRuntimeRuns()
  } catch (error) {
    store.setState((state) => ({
      ...state,
      error: error instanceof Error ? error.message : String(error),
    }))
    throw error
  }
}

export async function cancelRuntimeRun(runId: string): Promise<RuntimeRun> {
  try {
    const result = await requestRuntimeCancellation(runId)
    await loadRuntimeRuns()
    return result.run
  } catch (error) {
    store.setState((state) => ({
      ...state,
      error: error instanceof Error ? error.message : String(error),
    }))
    throw error
  }
}

export function useRuntimeRunStore<U>(
  selector: (state: RuntimeRunStoreState) => U,
): U {
  return useExternalStore(store, selector)
}
