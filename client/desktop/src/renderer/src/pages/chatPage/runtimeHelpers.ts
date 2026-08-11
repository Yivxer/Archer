import { restoreRuntimeStateFromEvents } from '../../../../agent'
import type { ApprovalResultEvent, EventLog, JobEvent, ToolRequestEvent } from '../../../../agent'
import type { BackgroundJob, ToolEvent } from '../../types'
import type { WorkspaceJobSummary } from '../../components/WorkspaceContextPanel'

export function restoreRuntimeState(sessionId: string, eventLog: EventLog | null) {
  return restoreRuntimeStateFromEvents(sessionId, eventLog?.all() ?? [])
}

export function rebindNewRuntimeSession(
  eventLog: EventLog | null,
  previousSessionId: string,
  currentSessionId: string,
): void {
  if (
    previousSessionId === 'desktop-session'
    && currentSessionId !== previousSessionId
  ) {
    eventLog?.moveSession(previousSessionId, currentSessionId)
  }
}

export function mergeWorkspaceJobs(runtimeJobs: JobEvent[], workspaceJobs: BackgroundJob[]): WorkspaceJobSummary[] {
  const merged = new Map<string, WorkspaceJobSummary>()
  for (const job of workspaceJobs) {
    merged.set(job.id, {
      id: job.id,
      title: job.title,
      status: job.status,
      kind: job.kind,
      preview: job.result || job.error || job.prompt,
      createdAt: job.createdAt,
    })
  }
  for (const job of runtimeJobs) {
    merged.set(job.jobId, {
      id: job.jobId,
      title: job.title,
      status: job.status,
      kind: 'runtime',
      preview: job.detail,
      createdAt: job.createdAt,
    })
  }
  return Array.from(merged.values()).sort((a, b) => b.createdAt.localeCompare(a.createdAt))
}

/** Convert a runtime ToolRequestEvent to display-friendly ToolEvent for ToolEventCard rendering */
export function isHiddenToolEvent(name: string): boolean {
  return ['obsidian_search', 'obsidian_read', 'memory.retrieve', 'memory-retrieve', 'file.reference'].includes(name)
}

export function isCompletedHugoToolEvent(event: ToolEvent): boolean {
  return event.name === 'hugo_blog' && event.status === 'complete'
}

export function toolEventFromRuntimeRequest(req: ToolRequestEvent): ToolEvent {
  return {
    id: req.id,
    name: req.toolName,
    status: req.requiresApproval ? 'waiting' : (req.blocked ? 'blocked' : 'complete'),
    risk: req.risk,
    summary: req.summary,
    detail: req.detail,
    requiresApproval: req.requiresApproval,
    draft: {
      skillName: req.toolName,
      displayName: req.displayName,
      args: req.args,
      blocked: req.blocked,
      ...req.draft,
    },
  }
}

export function toolEventWithRuntimeResult(event: ToolEvent, result?: ApprovalResultEvent): ToolEvent {
  if (!result) return event
  const output = result.output
    ? `output: ${result.output.slice(0, 500)}${result.output.length > 500 ? '…(已截断)' : ''}`
    : result.message
  return {
    ...event,
    status: result.decision === 'denied' ? 'denied' : result.executed ? 'complete' : 'blocked',
    summary: result.message || event.summary,
    detail: output,
    requiresApproval: false,
    receipt: result.receipt,
  }
}
