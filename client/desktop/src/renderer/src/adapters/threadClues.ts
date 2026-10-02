import { postJson } from './localArcher'

export type ThreadClueStatus = 'resolved' | 'closed' | 'dismissed' | 'expired'
export type ThreadClueResult = { ok: boolean; id: number; status: ThreadClueStatus; changed: boolean }

export async function transitionThreadClue(id: number, status: ThreadClueStatus): Promise<ThreadClueResult> {
  if (!Number.isSafeInteger(id) || id <= 0) throw new Error('无法定位这条观察线索')
  const result = await postJson<ThreadClueResult>(`/initiative-threads/${id}/status`, { status })
  if (!result.ok || result.id !== id || result.status !== status) throw new Error('线索状态未保存')
  return result
}
