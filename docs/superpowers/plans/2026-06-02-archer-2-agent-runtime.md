# Archer 2 Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Archer 2.0's TypeScript "nervous system" so chat, tools, approvals, background jobs, and UI state run through one typed runtime instead of scattered Python API + React state glue.

**Architecture:** Keep Python as the skill/worker layer for Obsidian, Hugo, memory, local files, embeddings, and existing scripts. Add a TypeScript runtime inside the desktop app that owns contracts, event streams, approvals, job state, and recovery, then gradually routes Python capabilities through typed adapters.

**Tech Stack:** TypeScript 5.9, Electron, React 19, Node streams, SSE, Vitest, Zod, existing Python skills and `terminal/archer_api.py`.

---

## Current Diagnosis

Archer's core weakness is not model ability. It is runtime continuity.

The current Desktop path is:

```text
React ChatPage
  -> localArcher.ts fetch/SSE
  -> Python terminal/archer_api.py
  -> terminal/api/_tools.py event builders
  -> PENDING_TOOL_DRAFTS in Python memory
  -> /tool-approvals
  -> React manually rewrites one card state
```

This creates the exact bugs seen in the blog upload flow:

- tool schemas exist but are not always surfaced as executable actions
- approval cards are disconnected from continued agent reasoning
- Python and TS duplicate event shapes by convention, not enforced types
- completed approvals update one card but do not become durable conversation events
- background subtask capability exists in terminal commands but is not productized in Desktop

Archer 2.0 should fix the nervous system first. Do not rewrite all skills.

## Target Boundary

TypeScript owns:

- `AgentEvent`
- `ToolRequest`
- `ApprovalDecision`
- `RuntimeSession`
- `BackgroundJob`
- event log
- retry/cancel/resume
- UI state derivation

Python owns:

- existing `skills/*.py`
- memory DB operations during the transition
- Obsidian/Hugo/local file operations
- embedding/vector/eval/offline tasks
- terminal compatibility

## File Structure

Create:

- `client/desktop/src/agent/contracts.ts`  
  Single source of truth for runtime events, messages, tools, approvals, and jobs.

- `client/desktop/src/agent/contractSchemas.ts`  
  Zod validators for all external data crossing API or worker boundaries.

- `client/desktop/src/agent/eventLog.ts`  
  Append-only in-memory event log with reducer-friendly query helpers.

- `client/desktop/src/agent/runtimeStore.ts`  
  Runtime state reducer for sessions, streaming text, tool events, approvals, and jobs.

- `client/desktop/src/agent/pythonBridge.ts`  
  Adapter that talks to current Python API while returning typed runtime events.

- `client/desktop/src/agent/approvalQueue.ts`  
  Approval state machine and helpers.

- `client/desktop/src/agent/jobRunner.ts`  
  Background job registry for subagent/workflow execution.

- `client/desktop/src/agent/index.ts`  
  Public exports for the runtime package.

- `client/desktop/src/agent/__tests__/contracts.test.ts`
- `client/desktop/src/agent/__tests__/eventLog.test.ts`
- `client/desktop/src/agent/__tests__/approvalQueue.test.ts`
- `client/desktop/src/agent/__tests__/pythonBridge.test.ts`
- `client/desktop/src/agent/__tests__/runtimeStore.test.ts`
- `client/desktop/src/agent/__tests__/jobRunner.test.ts`

Modify:

- `client/desktop/package.json`  
  Add `vitest` scripts and `zod` dependency.

- `client/desktop/src/renderer/src/types.ts`  
  Re-export or replace duplicated tool/event types from `agent/contracts.ts`.

- `client/desktop/src/renderer/src/adapters/localArcher.ts`  
  Convert raw SSE frames and approval responses through `pythonBridge.ts`.

- `client/desktop/src/renderer/src/pages/ChatPage.tsx`  
  Stop hand-mutating tool cards. Render derived runtime state.

- `terminal/api/_tools.py`  
  Keep compatibility, but emit stable event envelope names matching TS contracts.

- `terminal/api/_routes.py`  
  Return typed approval result payloads compatible with TS schemas.

- `tests/test_desktop_api.py`  
  Lock Python event envelope compatibility.

Do not modify:

- `skills/*.py` except when a specific adapter uncovers a real skill bug.
- `memory/store.py` during Phase 1.
- `terminal/archer.py` during Phase 1.

---

## Phase 0: Install Runtime Test Harness

### Task 1: Add TS Runtime Test Dependencies

**Files:**
- Modify: `client/desktop/package.json`
- Modify: `client/desktop/package-lock.json`

- [ ] **Step 1: Install dependencies**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm install zod
npm install -D vitest
```

Expected: `package.json` and `package-lock.json` update.

- [ ] **Step 2: Add scripts**

Modify `client/desktop/package.json` scripts to include:

```json
{
  "test": "vitest run",
  "test:watch": "vitest"
}
```

- [ ] **Step 3: Run build and empty test suite**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run build
npm run test
```

Expected: build passes. Test command passes or reports no test files before Task 2.

- [ ] **Step 4: Commit**

```bash
git add client/desktop/package.json client/desktop/package-lock.json
git commit -m "chore: add desktop runtime test harness"
```

---

## Phase 1: Contract First

### Task 2: Define Runtime Contracts

**Files:**
- Create: `client/desktop/src/agent/contracts.ts`
- Create: `client/desktop/src/agent/index.ts`
- Create: `client/desktop/src/agent/__tests__/contracts.test.ts`

- [ ] **Step 1: Write failing contract tests**

Create `client/desktop/src/agent/__tests__/contracts.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { AgentEvent, ToolRequestEvent, ApprovalResultEvent } from '../contracts'

describe('agent contracts', () => {
  it('represents a tool request event with stable approval fields', () => {
    const event: ToolRequestEvent = {
      type: 'tool.request',
      id: 'tool-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      toolName: 'hugo_blog',
      displayName: 'hugo_blog',
      risk: 'low',
      status: 'waiting_approval',
      args: { action: 'deploy' },
      summary: '确认部署枫弋札记',
      detail: 'action: deploy',
      requiresApproval: true,
      blocked: false,
    }
    expect(event.type).toBe('tool.request')
    expect(event.requiresApproval).toBe(true)
  })

  it('represents approval results as events, not UI-only mutations', () => {
    const event: ApprovalResultEvent = {
      type: 'approval.result',
      id: 'approval-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:01:00.000Z',
      requestId: 'tool-1',
      decision: 'approved',
      executed: true,
      ok: true,
      output: '部署成功',
      message: 'hugo deploy 已自动执行',
    }
    expect(event.executed).toBe(true)
  })

  it('keeps every event discriminated by type', () => {
    const event: AgentEvent = {
      type: 'text.delta',
      id: 'text-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:02:00.000Z',
      text: '完成。',
    }
    expect(event.type).toBe('text.delta')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/contracts.test.ts
```

Expected: FAIL because `../contracts` does not exist.

- [ ] **Step 3: Implement contracts**

Create `client/desktop/src/agent/contracts.ts`:

```ts
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type ToolStatus = 'running' | 'waiting_approval' | 'complete' | 'blocked' | 'denied'
export type ApprovalDecision = 'approved' | 'denied'
export type JobStatus = 'queued' | 'running' | 'waiting_approval' | 'complete' | 'failed' | 'cancelled'

export type AgentEventBase = {
  id: string
  sessionId: string
  createdAt: string
}

export type TextDeltaEvent = AgentEventBase & {
  type: 'text.delta'
  text: string
}

export type TextFinalEvent = AgentEventBase & {
  type: 'text.final'
  text: string
}

export type ToolRequestEvent = AgentEventBase & {
  type: 'tool.request'
  toolName: string
  displayName: string
  risk: RiskLevel
  status: ToolStatus
  args: Record<string, unknown>
  summary: string
  detail: string
  requiresApproval: boolean
  blocked: boolean
}

export type ToolResultEvent = AgentEventBase & {
  type: 'tool.result'
  requestId: string
  toolName: string
  status: Extract<ToolStatus, 'complete' | 'blocked' | 'denied'>
  ok: boolean
  output: string
  message: string
}

export type ApprovalResultEvent = AgentEventBase & {
  type: 'approval.result'
  requestId: string
  decision: ApprovalDecision
  executed: boolean
  ok: boolean
  output: string
  message: string
}

export type JobEvent = AgentEventBase & {
  type: 'job.event'
  jobId: string
  title: string
  status: JobStatus
  detail: string
  progress?: {
    done: number
    total: number
  }
}

export type ErrorEvent = AgentEventBase & {
  type: 'runtime.error'
  scope: 'stream' | 'approval' | 'job' | 'adapter'
  message: string
  recoverable: boolean
}

export type AgentEvent =
  | TextDeltaEvent
  | TextFinalEvent
  | ToolRequestEvent
  | ToolResultEvent
  | ApprovalResultEvent
  | JobEvent
  | ErrorEvent

export type RuntimeMessage = {
  id: string
  role: 'user' | 'assistant' | 'system'
  text: string
}

export type RuntimeSession = {
  id: string
  messages: RuntimeMessage[]
  events: AgentEvent[]
  status: 'idle' | 'streaming' | 'waiting_approval' | 'running_job' | 'error'
}
```

Create `client/desktop/src/agent/index.ts`:

```ts
export type {
  AgentEvent,
  AgentEventBase,
  ApprovalDecision,
  ApprovalResultEvent,
  ErrorEvent,
  JobEvent,
  JobStatus,
  RiskLevel,
  RuntimeMessage,
  RuntimeSession,
  TextDeltaEvent,
  TextFinalEvent,
  ToolRequestEvent,
  ToolResultEvent,
  ToolStatus,
} from './contracts'
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/contracts.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add client/desktop/src/agent client/desktop/package.json client/desktop/package-lock.json
git commit -m "feat: define desktop agent runtime contracts"
```

---

### Task 3: Add Runtime Contract Schemas

**Files:**
- Create: `client/desktop/src/agent/contractSchemas.ts`
- Create: `client/desktop/src/agent/__tests__/contractSchemas.test.ts`
- Modify: `client/desktop/src/agent/index.ts`

- [ ] **Step 1: Write failing schema tests**

Create `client/desktop/src/agent/__tests__/contractSchemas.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { agentEventSchema, parseAgentEvent } from '../contractSchemas'

describe('contract schemas', () => {
  it('accepts a valid tool request event', () => {
    const parsed = parseAgentEvent({
      type: 'tool.request',
      id: 'tool-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      toolName: 'hugo_blog',
      displayName: 'hugo_blog',
      risk: 'low',
      status: 'waiting_approval',
      args: { action: 'deploy' },
      summary: '确认部署枫弋札记',
      detail: 'action: deploy',
      requiresApproval: true,
      blocked: false,
    })
    expect(parsed.type).toBe('tool.request')
  })

  it('rejects unknown event types', () => {
    const result = agentEventSchema.safeParse({
      type: 'tool_event',
      id: 'bad',
    })
    expect(result.success).toBe(false)
  })

  it('rejects malformed approval results', () => {
    const result = agentEventSchema.safeParse({
      type: 'approval.result',
      id: 'approval-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      requestId: 'tool-1',
      decision: 'maybe',
      executed: true,
      ok: true,
      output: '',
      message: '',
    })
    expect(result.success).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/contractSchemas.test.ts
```

Expected: FAIL because `contractSchemas.ts` does not exist.

- [ ] **Step 3: Implement schemas**

Create `client/desktop/src/agent/contractSchemas.ts`:

```ts
import { z } from 'zod'
import type { AgentEvent } from './contracts'

const base = z.object({
  id: z.string().min(1),
  sessionId: z.string().min(1),
  createdAt: z.string().min(1),
})

const riskLevelSchema = z.enum(['low', 'medium', 'high', 'critical'])
const toolStatusSchema = z.enum(['running', 'waiting_approval', 'complete', 'blocked', 'denied'])
const jobStatusSchema = z.enum(['queued', 'running', 'waiting_approval', 'complete', 'failed', 'cancelled'])

export const textDeltaEventSchema = base.extend({
  type: z.literal('text.delta'),
  text: z.string(),
})

export const textFinalEventSchema = base.extend({
  type: z.literal('text.final'),
  text: z.string(),
})

export const toolRequestEventSchema = base.extend({
  type: z.literal('tool.request'),
  toolName: z.string().min(1),
  displayName: z.string().min(1),
  risk: riskLevelSchema,
  status: toolStatusSchema,
  args: z.record(z.string(), z.unknown()),
  summary: z.string(),
  detail: z.string(),
  requiresApproval: z.boolean(),
  blocked: z.boolean(),
})

export const toolResultEventSchema = base.extend({
  type: z.literal('tool.result'),
  requestId: z.string().min(1),
  toolName: z.string().min(1),
  status: z.enum(['complete', 'blocked', 'denied']),
  ok: z.boolean(),
  output: z.string(),
  message: z.string(),
})

export const approvalResultEventSchema = base.extend({
  type: z.literal('approval.result'),
  requestId: z.string().min(1),
  decision: z.enum(['approved', 'denied']),
  executed: z.boolean(),
  ok: z.boolean(),
  output: z.string(),
  message: z.string(),
})

export const jobEventSchema = base.extend({
  type: z.literal('job.event'),
  jobId: z.string().min(1),
  title: z.string(),
  status: jobStatusSchema,
  detail: z.string(),
  progress: z.object({
    done: z.number().int().nonnegative(),
    total: z.number().int().nonnegative(),
  }).optional(),
})

export const errorEventSchema = base.extend({
  type: z.literal('runtime.error'),
  scope: z.enum(['stream', 'approval', 'job', 'adapter']),
  message: z.string(),
  recoverable: z.boolean(),
})

export const agentEventSchema = z.discriminatedUnion('type', [
  textDeltaEventSchema,
  textFinalEventSchema,
  toolRequestEventSchema,
  toolResultEventSchema,
  approvalResultEventSchema,
  jobEventSchema,
  errorEventSchema,
])

export function parseAgentEvent(value: unknown): AgentEvent {
  return agentEventSchema.parse(value)
}
```

Modify `client/desktop/src/agent/index.ts`:

```ts
export { agentEventSchema, parseAgentEvent } from './contractSchemas'
export type {
  AgentEvent,
  AgentEventBase,
  ApprovalDecision,
  ApprovalResultEvent,
  ErrorEvent,
  JobEvent,
  JobStatus,
  RiskLevel,
  RuntimeMessage,
  RuntimeSession,
  TextDeltaEvent,
  TextFinalEvent,
  ToolRequestEvent,
  ToolResultEvent,
  ToolStatus,
} from './contracts'
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/contractSchemas.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add client/desktop/src/agent client/desktop/package.json client/desktop/package-lock.json
git commit -m "feat: validate agent runtime contracts"
```

---

## Phase 2: Event Log and Approval Queue

### Task 4: Add Append-Only Event Log

**Files:**
- Create: `client/desktop/src/agent/eventLog.ts`
- Create: `client/desktop/src/agent/__tests__/eventLog.test.ts`
- Modify: `client/desktop/src/agent/index.ts`

- [ ] **Step 1: Write failing tests**

Create `client/desktop/src/agent/__tests__/eventLog.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { createEventLog } from '../eventLog'
import type { AgentEvent } from '../contracts'

function event(id: string, type: AgentEvent['type']): AgentEvent {
  if (type === 'text.delta') {
    return { type, id, sessionId: 's1', createdAt: id, text: id }
  }
  return {
    type: 'runtime.error',
    id,
    sessionId: 's1',
    createdAt: id,
    scope: 'adapter',
    message: id,
    recoverable: true,
  }
}

describe('event log', () => {
  it('appends events in order', () => {
    const log = createEventLog()
    log.append(event('1', 'text.delta'))
    log.append(event('2', 'text.delta'))
    expect(log.all().map((item) => item.id)).toEqual(['1', '2'])
  })

  it('deduplicates repeated event ids', () => {
    const log = createEventLog()
    log.append(event('1', 'text.delta'))
    log.append(event('1', 'text.delta'))
    expect(log.all()).toHaveLength(1)
  })

  it('filters events by session', () => {
    const log = createEventLog()
    log.append(event('1', 'text.delta'))
    log.append({ ...event('2', 'text.delta'), sessionId: 's2' })
    expect(log.forSession('s1')).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/eventLog.test.ts
```

Expected: FAIL because `eventLog.ts` does not exist.

- [ ] **Step 3: Implement event log**

Create `client/desktop/src/agent/eventLog.ts`:

```ts
import type { AgentEvent } from './contracts'

export type EventLog = {
  append: (event: AgentEvent) => void
  appendMany: (events: AgentEvent[]) => void
  all: () => AgentEvent[]
  forSession: (sessionId: string) => AgentEvent[]
  get: (eventId: string) => AgentEvent | undefined
  clear: () => void
}

export function createEventLog(initial: AgentEvent[] = []): EventLog {
  const events: AgentEvent[] = []
  const seen = new Set<string>()

  function append(event: AgentEvent): void {
    if (seen.has(event.id)) return
    seen.add(event.id)
    events.push(event)
  }

  for (const event of initial) append(event)

  return {
    append,
    appendMany(nextEvents) {
      for (const event of nextEvents) append(event)
    },
    all() {
      return [...events]
    },
    forSession(sessionId) {
      return events.filter((event) => event.sessionId === sessionId)
    },
    get(eventId) {
      return events.find((event) => event.id === eventId)
    },
    clear() {
      events.length = 0
      seen.clear()
    },
  }
}
```

Modify `client/desktop/src/agent/index.ts`:

```ts
export { agentEventSchema, parseAgentEvent } from './contractSchemas'
export { createEventLog } from './eventLog'
export type { EventLog } from './eventLog'
export type {
  AgentEvent,
  AgentEventBase,
  ApprovalDecision,
  ApprovalResultEvent,
  ErrorEvent,
  JobEvent,
  JobStatus,
  RiskLevel,
  RuntimeMessage,
  RuntimeSession,
  TextDeltaEvent,
  TextFinalEvent,
  ToolRequestEvent,
  ToolResultEvent,
  ToolStatus,
} from './contracts'
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/eventLog.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add client/desktop/src/agent
git commit -m "feat: add desktop agent event log"
```

---

### Task 5: Add Approval Queue State Machine

**Files:**
- Create: `client/desktop/src/agent/approvalQueue.ts`
- Create: `client/desktop/src/agent/__tests__/approvalQueue.test.ts`
- Modify: `client/desktop/src/agent/index.ts`

- [ ] **Step 1: Write failing tests**

Create `client/desktop/src/agent/__tests__/approvalQueue.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { createApprovalQueue } from '../approvalQueue'
import type { ToolRequestEvent } from '../contracts'

function request(id = 'tool-1'): ToolRequestEvent {
  return {
    type: 'tool.request',
    id,
    sessionId: 'session-1',
    createdAt: '2026-06-02T10:00:00.000Z',
    toolName: 'hugo_blog',
    displayName: 'hugo_blog',
    risk: 'low',
    status: 'waiting_approval',
    args: { action: 'deploy' },
    summary: '确认部署枫弋札记',
    detail: 'action: deploy',
    requiresApproval: true,
    blocked: false,
  }
}

describe('approval queue', () => {
  it('adds waiting tool requests', () => {
    const queue = createApprovalQueue()
    queue.add(request())
    expect(queue.pending()).toHaveLength(1)
  })

  it('records approved decisions once', () => {
    const queue = createApprovalQueue()
    queue.add(request())
    expect(queue.decide('tool-1', 'approved')).toEqual({ ok: true })
    expect(queue.decide('tool-1', 'denied')).toEqual({ ok: false, reason: 'already_decided' })
  })

  it('removes completed approvals from pending list', () => {
    const queue = createApprovalQueue()
    queue.add(request())
    queue.decide('tool-1', 'approved')
    expect(queue.pending()).toHaveLength(0)
    expect(queue.decisionFor('tool-1')).toBe('approved')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/approvalQueue.test.ts
```

Expected: FAIL because `approvalQueue.ts` does not exist.

- [ ] **Step 3: Implement approval queue**

Create `client/desktop/src/agent/approvalQueue.ts`:

```ts
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
```

Modify `client/desktop/src/agent/index.ts`:

```ts
export { createApprovalQueue } from './approvalQueue'
export type { ApprovalQueue } from './approvalQueue'
export { agentEventSchema, parseAgentEvent } from './contractSchemas'
export { createEventLog } from './eventLog'
export type { EventLog } from './eventLog'
export type {
  AgentEvent,
  AgentEventBase,
  ApprovalDecision,
  ApprovalResultEvent,
  ErrorEvent,
  JobEvent,
  JobStatus,
  RiskLevel,
  RuntimeMessage,
  RuntimeSession,
  TextDeltaEvent,
  TextFinalEvent,
  ToolRequestEvent,
  ToolResultEvent,
  ToolStatus,
} from './contracts'
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/approvalQueue.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add client/desktop/src/agent
git commit -m "feat: add desktop approval queue"
```

---

## Phase 3: Python Bridge

### Task 6: Convert Python SSE Tool Events to Runtime Events

**Files:**
- Create: `client/desktop/src/agent/pythonBridge.ts`
- Create: `client/desktop/src/agent/__tests__/pythonBridge.test.ts`
- Modify: `client/desktop/src/agent/index.ts`

- [ ] **Step 1: Write failing tests**

Create `client/desktop/src/agent/__tests__/pythonBridge.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { pythonToolEventToAgentEvent, pythonApprovalToAgentEvent } from '../pythonBridge'

describe('python bridge', () => {
  it('converts Python toolEvent to a tool.request event', () => {
    const event = pythonToolEventToAgentEvent('session-1', {
      id: 'hugo-blog-1',
      name: 'hugo_blog',
      status: 'waiting',
      risk: 'low',
      summary: '确认部署枫弋札记',
      detail: 'action: deploy',
      requiresApproval: true,
      draft: {
        skillName: 'hugo_blog',
        displayName: 'hugo_blog',
        args: { action: 'deploy' },
        blocked: false,
      },
    })
    expect(event.type).toBe('tool.request')
    if (event.type === 'tool.request') {
      expect(event.status).toBe('waiting_approval')
      expect(event.args).toEqual({ action: 'deploy' })
    }
  })

  it('converts approval response to approval.result event', () => {
    const event = pythonApprovalToAgentEvent('session-1', {
      ok: true,
      eventId: 'hugo-blog-1',
      decision: 'approved',
      executed: true,
      output: '部署成功',
      message: 'hugo deploy 已自动执行',
    })
    expect(event.type).toBe('approval.result')
    expect(event.executed).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/pythonBridge.test.ts
```

Expected: FAIL because `pythonBridge.ts` does not exist.

- [ ] **Step 3: Implement bridge**

Create `client/desktop/src/agent/pythonBridge.ts`:

```ts
import type { AgentEvent, ApprovalDecision, RiskLevel, ToolStatus } from './contracts'

type PythonToolEvent = {
  id: string
  name: string
  status: 'running' | 'waiting' | 'complete' | 'blocked' | 'denied'
  risk: RiskLevel
  summary: string
  detail: string
  requiresApproval?: boolean
  draft?: {
    skillName?: string
    displayName?: string
    args?: Record<string, unknown>
    blocked?: boolean
    [key: string]: unknown
  }
}

type PythonApprovalResult = {
  ok: boolean
  eventId: string
  decision: ApprovalDecision
  executed: boolean
  output?: string
  message: string
}

function nowIso(): string {
  return new Date().toISOString()
}

function mapToolStatus(status: PythonToolEvent['status'], requiresApproval: boolean): ToolStatus {
  if (requiresApproval && status === 'waiting') return 'waiting_approval'
  if (status === 'waiting') return 'running'
  return status
}

export function pythonToolEventToAgentEvent(sessionId: string, event: PythonToolEvent): AgentEvent {
  const requiresApproval = Boolean(event.requiresApproval)
  const draft = event.draft || {}
  return {
    type: 'tool.request',
    id: event.id,
    sessionId,
    createdAt: nowIso(),
    toolName: String(draft.skillName || event.name),
    displayName: String(draft.displayName || event.name),
    risk: event.risk,
    status: mapToolStatus(event.status, requiresApproval),
    args: draft.args || {},
    summary: event.summary,
    detail: event.detail,
    requiresApproval,
    blocked: Boolean(draft.blocked || event.status === 'blocked'),
  }
}

export function pythonApprovalToAgentEvent(sessionId: string, result: PythonApprovalResult): AgentEvent {
  return {
    type: 'approval.result',
    id: `approval-${result.eventId}`,
    sessionId,
    createdAt: nowIso(),
    requestId: result.eventId,
    decision: result.decision,
    executed: result.executed,
    ok: result.ok,
    output: result.output || '',
    message: result.message,
  }
}
```

Modify `client/desktop/src/agent/index.ts`:

```ts
export { createApprovalQueue } from './approvalQueue'
export type { ApprovalQueue } from './approvalQueue'
export { agentEventSchema, parseAgentEvent } from './contractSchemas'
export { createEventLog } from './eventLog'
export type { EventLog } from './eventLog'
export { pythonApprovalToAgentEvent, pythonToolEventToAgentEvent } from './pythonBridge'
export type {
  AgentEvent,
  AgentEventBase,
  ApprovalDecision,
  ApprovalResultEvent,
  ErrorEvent,
  JobEvent,
  JobStatus,
  RiskLevel,
  RuntimeMessage,
  RuntimeSession,
  TextDeltaEvent,
  TextFinalEvent,
  ToolRequestEvent,
  ToolResultEvent,
  ToolStatus,
} from './contracts'
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/pythonBridge.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add client/desktop/src/agent
git commit -m "feat: bridge python tool events into runtime events"
```

---

## Phase 4: Runtime Store

### Task 7: Add Runtime Reducer

**Files:**
- Create: `client/desktop/src/agent/runtimeStore.ts`
- Create: `client/desktop/src/agent/__tests__/runtimeStore.test.ts`
- Modify: `client/desktop/src/agent/index.ts`

- [ ] **Step 1: Write failing tests**

Create `client/desktop/src/agent/__tests__/runtimeStore.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { createInitialRuntimeState, reduceRuntimeEvent } from '../runtimeStore'
import type { AgentEvent } from '../contracts'

describe('runtime store reducer', () => {
  it('appends assistant text deltas', () => {
    const state = createInitialRuntimeState('session-1')
    const event: AgentEvent = {
      type: 'text.delta',
      id: 'text-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      text: '你好',
    }
    const next = reduceRuntimeEvent(state, event)
    expect(next.streamingText).toBe('你好')
  })

  it('marks session as waiting when approval is required', () => {
    const state = createInitialRuntimeState('session-1')
    const next = reduceRuntimeEvent(state, {
      type: 'tool.request',
      id: 'tool-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      toolName: 'hugo_blog',
      displayName: 'hugo_blog',
      risk: 'low',
      status: 'waiting_approval',
      args: { action: 'deploy' },
      summary: '确认部署枫弋札记',
      detail: '',
      requiresApproval: true,
      blocked: false,
    })
    expect(next.status).toBe('waiting_approval')
    expect(next.pendingApprovals).toHaveLength(1)
  })

  it('removes pending approval after approval result', () => {
    const state = reduceRuntimeEvent(createInitialRuntimeState('session-1'), {
      type: 'tool.request',
      id: 'tool-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:00:00.000Z',
      toolName: 'hugo_blog',
      displayName: 'hugo_blog',
      risk: 'low',
      status: 'waiting_approval',
      args: {},
      summary: '',
      detail: '',
      requiresApproval: true,
      blocked: false,
    })
    const next = reduceRuntimeEvent(state, {
      type: 'approval.result',
      id: 'approval-tool-1',
      sessionId: 'session-1',
      createdAt: '2026-06-02T10:01:00.000Z',
      requestId: 'tool-1',
      decision: 'approved',
      executed: true,
      ok: true,
      output: 'ok',
      message: 'done',
    })
    expect(next.pendingApprovals).toHaveLength(0)
    expect(next.toolResults['tool-1']?.message).toBe('done')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/runtimeStore.test.ts
```

Expected: FAIL because `runtimeStore.ts` does not exist.

- [ ] **Step 3: Implement reducer**

Create `client/desktop/src/agent/runtimeStore.ts`:

```ts
import type { AgentEvent, ApprovalResultEvent, JobEvent, RuntimeSession, ToolRequestEvent } from './contracts'

export type RuntimeState = RuntimeSession & {
  streamingText: string
  pendingApprovals: ToolRequestEvent[]
  toolResults: Record<string, ApprovalResultEvent>
  jobs: Record<string, JobEvent>
}

export function createInitialRuntimeState(sessionId: string): RuntimeState {
  return {
    id: sessionId,
    messages: [],
    events: [],
    status: 'idle',
    streamingText: '',
    pendingApprovals: [],
    toolResults: {},
    jobs: {},
  }
}

export function reduceRuntimeEvent(state: RuntimeState, event: AgentEvent): RuntimeState {
  const events = state.events.some((item) => item.id === event.id)
    ? state.events
    : [...state.events, event]

  if (event.type === 'text.delta') {
    return {
      ...state,
      events,
      status: 'streaming',
      streamingText: state.streamingText + event.text,
    }
  }

  if (event.type === 'text.final') {
    return {
      ...state,
      events,
      status: 'idle',
      streamingText: '',
      messages: [
        ...state.messages,
        { id: event.id, role: 'assistant', text: event.text },
      ],
    }
  }

  if (event.type === 'tool.request') {
    const nextPending = event.requiresApproval && !event.blocked
      ? [...state.pendingApprovals.filter((item) => item.id !== event.id), event]
      : state.pendingApprovals
    return {
      ...state,
      events,
      status: nextPending.length ? 'waiting_approval' : state.status,
      pendingApprovals: nextPending,
    }
  }

  if (event.type === 'approval.result') {
    const pendingApprovals = state.pendingApprovals.filter((item) => item.id !== event.requestId)
    return {
      ...state,
      events,
      status: pendingApprovals.length ? 'waiting_approval' : 'idle',
      pendingApprovals,
      toolResults: {
        ...state.toolResults,
        [event.requestId]: event,
      },
    }
  }

  if (event.type === 'job.event') {
    return {
      ...state,
      events,
      status: event.status === 'running' ? 'running_job' : state.status,
      jobs: {
        ...state.jobs,
        [event.jobId]: event,
      },
    }
  }

  if (event.type === 'runtime.error') {
    return {
      ...state,
      events,
      status: 'error',
    }
  }

  return { ...state, events }
}
```

Modify `client/desktop/src/agent/index.ts`:

```ts
export { createApprovalQueue } from './approvalQueue'
export type { ApprovalQueue } from './approvalQueue'
export { agentEventSchema, parseAgentEvent } from './contractSchemas'
export { createEventLog } from './eventLog'
export type { EventLog } from './eventLog'
export { pythonApprovalToAgentEvent, pythonToolEventToAgentEvent } from './pythonBridge'
export { createInitialRuntimeState, reduceRuntimeEvent } from './runtimeStore'
export type { RuntimeState } from './runtimeStore'
export type {
  AgentEvent,
  AgentEventBase,
  ApprovalDecision,
  ApprovalResultEvent,
  ErrorEvent,
  JobEvent,
  JobStatus,
  RiskLevel,
  RuntimeMessage,
  RuntimeSession,
  TextDeltaEvent,
  TextFinalEvent,
  ToolRequestEvent,
  ToolResultEvent,
  ToolStatus,
} from './contracts'
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/runtimeStore.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add client/desktop/src/agent
git commit -m "feat: add desktop agent runtime reducer"
```

---

## Phase 5: Desktop Integration

### Task 8: Route Local Archer SSE Through Python Bridge

**Files:**
- Modify: `client/desktop/src/renderer/src/adapters/localArcher.ts`
- Modify: `client/desktop/src/renderer/src/types.ts`
- Test: `client/desktop/src/agent/__tests__/pythonBridge.test.ts`

- [ ] **Step 1: Replace duplicate tool event conversion**

In `client/desktop/src/renderer/src/adapters/localArcher.ts`, import:

```ts
import { pythonToolEventToAgentEvent } from '../../../agent'
```

Keep the existing `streamLocalChat()` signature during this task. Add a second optional callback:

```ts
onAgentEvent?: (event: import('../../../agent').AgentEvent) => void
```

When parsing an SSE frame with `payload.toolEvent`, call:

```ts
if (payload.toolEvent) {
  onToolEvent?.(payload.toolEvent)
  onAgentEvent?.(pythonToolEventToAgentEvent('desktop-session', payload.toolEvent))
}
```

This keeps the current UI working while allowing the new runtime to observe typed events.

- [ ] **Step 2: Run typecheck**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run build
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add client/desktop/src/renderer/src/adapters/localArcher.ts client/desktop/src/renderer/src/types.ts
git commit -m "feat: expose typed runtime events from desktop SSE"
```

---

### Task 9: Refactor Approval Handling to Runtime Events

**Files:**
- Modify: `client/desktop/src/renderer/src/adapters/localArcher.ts`
- Modify: `client/desktop/src/renderer/src/pages/ChatPage.tsx`
- Test: `client/desktop/src/agent/__tests__/runtimeStore.test.ts`

- [ ] **Step 1: Convert approval responses**

In `localArcher.ts`, import:

```ts
import { pythonApprovalToAgentEvent } from '../../../agent'
```

Add a new function:

```ts
export async function submitToolApprovalEvent(
  sessionId: string,
  eventId: string,
  decision: 'approved' | 'denied'
) {
  const result = await submitToolApproval(eventId, decision)
  return {
    result,
    event: pythonApprovalToAgentEvent(sessionId, result),
  }
}
```

- [ ] **Step 2: Update ChatPage without removing old cards**

In `ChatPage.tsx`, keep existing `toolEvents` state. Add:

```ts
import { createInitialRuntimeState, reduceRuntimeEvent } from '../../../agent'
```

Add state:

```ts
const [runtimeState, setRuntimeState] = React.useState(() => createInitialRuntimeState(activeSession?.id || 'desktop-session'))
```

When `streamLocalChat` emits an agent event:

```ts
(agentEvent) => {
  setRuntimeState((current) => reduceRuntimeEvent(current, agentEvent))
}
```

When approval completes:

```ts
setRuntimeState((current) => reduceRuntimeEvent(current, result.event))
```

Do not remove current card rendering in this task. This is a shadow integration.

- [ ] **Step 3: Run build**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run build
```

Expected: PASS.

- [ ] **Step 4: Manual smoke**

Start API and app:

```bash
cd /Users/Yivxer/Projects/Archer
.venv/bin/python terminal/archer_api.py --port 8765 --token dev-token
```

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
ARCHER_DESKTOP_TOKEN=dev-token npm run dev
```

Ask: `部署枫弋札记`

Expected:

- confirmation card appears
- clicking approval executes Python approval endpoint
- old UI card still updates
- no console type/runtime errors

- [ ] **Step 5: Commit**

```bash
git add client/desktop/src/renderer/src/adapters/localArcher.ts client/desktop/src/renderer/src/pages/ChatPage.tsx
git commit -m "feat: shadow runtime approval state in desktop chat"
```

---

## Phase 6: Background Jobs

### Task 10: Add Desktop Job Runner

**Files:**
- Create: `client/desktop/src/agent/jobRunner.ts`
- Create: `client/desktop/src/agent/__tests__/jobRunner.test.ts`
- Modify: `client/desktop/src/agent/index.ts`

- [ ] **Step 1: Write failing tests**

Create `client/desktop/src/agent/__tests__/jobRunner.test.ts`:

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/jobRunner.test.ts
```

Expected: FAIL because `jobRunner.ts` does not exist.

- [ ] **Step 3: Implement job runner**

Create `client/desktop/src/agent/jobRunner.ts`:

```ts
import type { JobEvent } from './contracts'

type JobDefinition = {
  title: string
  run: () => Promise<string>
}

type QueuedJob = JobDefinition & {
  id: string
}

type JobRunnerOptions = {
  sessionId?: string
  emit: (event: JobEvent) => void
}

function nowIso(): string {
  return new Date().toISOString()
}

function makeJobEvent(sessionId: string, job: QueuedJob, status: JobEvent['status'], detail: string): JobEvent {
  return {
    type: 'job.event',
    id: `${job.id}-${status}-${Date.now()}`,
    sessionId,
    createdAt: nowIso(),
    jobId: job.id,
    title: job.title,
    status,
    detail,
  }
}

export function createJobRunner(options: JobRunnerOptions) {
  const queue: QueuedJob[] = []
  const sessionId = options.sessionId || 'desktop-session'
  let counter = 0

  return {
    enqueue(definition: JobDefinition): string {
      counter += 1
      const job = { ...definition, id: `job-${counter}` }
      queue.push(job)
      options.emit(makeJobEvent(sessionId, job, 'queued', '等待后台执行'))
      return job.id
    },
    async runNext(): Promise<void> {
      const job = queue.shift()
      if (!job) return
      options.emit(makeJobEvent(sessionId, job, 'running', '后台执行中'))
      try {
        const result = await job.run()
        options.emit(makeJobEvent(sessionId, job, 'complete', result))
      } catch (error) {
        options.emit(makeJobEvent(sessionId, job, 'failed', error instanceof Error ? error.message : 'unknown error'))
      }
    },
    pendingCount(): number {
      return queue.length
    },
  }
}
```

Modify `client/desktop/src/agent/index.ts`:

```ts
export { createApprovalQueue } from './approvalQueue'
export type { ApprovalQueue } from './approvalQueue'
export { agentEventSchema, parseAgentEvent } from './contractSchemas'
export { createEventLog } from './eventLog'
export type { EventLog } from './eventLog'
export { createJobRunner } from './jobRunner'
export { pythonApprovalToAgentEvent, pythonToolEventToAgentEvent } from './pythonBridge'
export { createInitialRuntimeState, reduceRuntimeEvent } from './runtimeStore'
export type { RuntimeState } from './runtimeStore'
export type {
  AgentEvent,
  AgentEventBase,
  ApprovalDecision,
  ApprovalResultEvent,
  ErrorEvent,
  JobEvent,
  JobStatus,
  RiskLevel,
  RuntimeMessage,
  RuntimeSession,
  TextDeltaEvent,
  TextFinalEvent,
  ToolRequestEvent,
  ToolResultEvent,
  ToolStatus,
} from './contracts'
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test -- src/agent/__tests__/jobRunner.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add client/desktop/src/agent
git commit -m "feat: add desktop background job runner"
```

---

## Phase 7: Productize Subagents

### Task 11: Add Python Background Job API Shim

**Files:**
- Modify: `terminal/api/_routes.py`
- Modify: `terminal/api/_tools.py`
- Test: `tests/test_desktop_api.py`

- [ ] **Step 1: Add Python API tests**

Append to `tests/test_desktop_api.py`:

```python
def test_background_job_create_returns_job_id(monkeypatch):
    from archer_api import payload_post

    status, payload = payload_post("/jobs", {
        "title": "后台分析",
        "kind": "analysis",
        "prompt": "分析当前 Archer 2.0 runtime 计划",
    })

    assert status == 200
    assert payload["ok"] is True
    assert payload["job"]["id"].startswith("job-")
    assert payload["job"]["status"] == "queued"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/Yivxer/Projects/Archer
.venv/bin/python -m pytest -q tests/test_desktop_api.py::test_background_job_create_returns_job_id
```

Expected: FAIL because `/jobs` is not implemented.

- [ ] **Step 3: Add minimal job endpoint**

In `terminal/api/_routes.py`, add module-level state:

```python
BACKGROUND_JOBS: dict[str, dict] = {}
```

Add:

```python
def _create_job(payload: dict) -> dict:
    from uuid import uuid4
    title = str(payload.get("title", "")).strip()
    kind = str(payload.get("kind", "")).strip() or "analysis"
    prompt = str(payload.get("prompt", "")).strip()
    if not title or not prompt:
        raise ValueError("title and prompt are required")
    job_id = f"job-{uuid4().hex[:8]}"
    job = {
        "id": job_id,
        "title": title,
        "kind": kind,
        "prompt": prompt,
        "status": "queued",
        "result": "",
    }
    BACKGROUND_JOBS[job_id] = job
    return {"ok": True, "job": job}
```

In `payload_post()`:

```python
if path == "/jobs":
    return 200, _create_job(payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /Users/Yivxer/Projects/Archer
.venv/bin/python -m pytest -q tests/test_desktop_api.py::test_background_job_create_returns_job_id
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add terminal/api/_routes.py tests/test_desktop_api.py
git commit -m "feat: add desktop background job API shim"
```

---

## Phase 8: Cutover

### Task 12: Replace ChatPage Tool State with Runtime-Derived State

**Files:**
- Modify: `client/desktop/src/renderer/src/pages/ChatPage.tsx`
- Modify: `client/desktop/src/renderer/src/types.ts`
- Test: `client/desktop/src/agent/__tests__/runtimeStore.test.ts`

- [ ] **Step 1: Remove separate `toolDecisions` state**

In `ChatPage.tsx`, remove:

```ts
const [toolDecisions, setToolDecisions] = React.useState<Record<string, 'approved' | 'denied'>>({})
```

Derive decisions from:

```ts
const toolDecisions = React.useMemo(() => {
  const decisions: Record<string, 'approved' | 'denied'> = {}
  for (const event of runtimeState.events) {
    if (event.type === 'approval.result') decisions[event.requestId] = event.decision
  }
  return decisions
}, [runtimeState.events])
```

- [ ] **Step 2: Derive pending cards from runtime events**

Replace manual `toolEvents` mutation after approval with runtime event reduction:

```ts
setRuntimeState((current) => reduceRuntimeEvent(current, approvalEvent))
```

Keep `toolEvents` only as a compatibility display list until all Python frames emit typed events.

- [ ] **Step 3: Run build**

Run:

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run build
```

Expected: PASS.

- [ ] **Step 4: Manual smoke**

Ask in desktop:

```text
部署枫弋札记
```

Expected:

- one approval card appears
- approving it changes runtime state to idle after result
- UI shows blog-specific result text
- no duplicate card remains waiting

- [ ] **Step 5: Commit**

```bash
git add client/desktop/src/renderer/src/pages/ChatPage.tsx client/desktop/src/renderer/src/types.ts
git commit -m "refactor: derive desktop tool state from agent runtime"
```

---

## Phase 9: Verification and Guardrails

### Task 13: Add Cross-Layer Runtime Validation

**Files:**
- Modify: `scripts/validate.sh`
- Modify: `tests/test_desktop_api.py`

- [ ] **Step 1: Add validation commands**

In `scripts/validate.sh`, ensure these commands run:

```bash
cd /Users/Yivxer/Projects/Archer
.venv/bin/python -m pytest -q tests/test_desktop_api.py tests/test_api_tool_service.py tests/test_skill_router.py

cd /Users/Yivxer/Projects/Archer/client/desktop
npm run test
npm run build
```

- [ ] **Step 2: Run validation**

Run:

```bash
cd /Users/Yivxer/Projects/Archer
bash scripts/validate.sh
```

Expected: Python tests, TS tests, and desktop build all pass.

- [ ] **Step 3: Commit**

```bash
git add scripts/validate.sh tests/test_desktop_api.py
git commit -m "test: validate agent runtime across python and desktop"
```

---

## Release Gate for Archer 2.0

Archer 2.0 is not ready until all of these are true:

- [ ] `部署枫弋札记` creates one approval card and executes deploy after approval.
- [ ] `帮我写一篇文章并发布到枫弋札记` creates a draft, confirms, writes, deploys, and reports result.
- [ ] A denied approval becomes a durable `approval.result` event, not just a temporary UI flag.
- [ ] Closing and reopening the chat can restore events for the current session.
- [ ] Background job can be queued from Desktop and reports queued/running/complete/failed states.
- [ ] Python tests pass.
- [ ] TS runtime tests pass.
- [ ] Desktop build passes.

## Migration Rule

Do not migrate a Python skill to TypeScript unless one of these is true:

- the skill is mostly UI/runtime orchestration
- the skill is called on every chat turn
- the skill's schema is duplicated in TS and Python
- the skill controls approval, streaming, jobs, or session state

Keep these in Python for now:

- `hugo_blog`
- `obsidian_*`
- `memory/*`
- embedding/vector retrieval
- file and shell operations
- offline workflows

Move these toward TypeScript first:

- tool event routing
- approval queue
- chat/session reducer
- background jobs
- plugin/runtime contracts
- Desktop-visible workflow orchestration

