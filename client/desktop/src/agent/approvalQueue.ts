import type { ApprovalDecision, ToolRequestEvent } from './contracts'

export type ApprovalQueue = {
  add: (request: ToolRequestEvent) => void
  pending: () => ToolRequestEvent[]
  decide: (requestId: string, decision: ApprovalDecision) => { ok: true } | { ok: false; reason: 'not_found' | 'already_decided' }
  decisionFor: (requestId: string) => ApprovalDecision | undefined
}

export function createApprovalQueue(): ApprovalQueue {
  const requests = new Map<string, ToolRequestEvent>()
  const decisions = new Map<string, ApprovalDecision>()

  return {
    add(request) {
      if (!request.requiresApproval || request.blocked) return
      if (decisions.has(request.id)) return
      requests.set(request.id, request)
    },
    pending() {
      return [...requests.values()].filter((request) => !decisions.has(request.id))
    },
    decide(requestId, decision) {
      if (decisions.has(requestId)) return { ok: false, reason: 'already_decided' }
      if (!requests.has(requestId)) return { ok: false, reason: 'not_found' }
      decisions.set(requestId, decision)
      requests.delete(requestId)
      return { ok: true }
    },
    decisionFor(requestId) {
      return decisions.get(requestId)
    },
  }
}
