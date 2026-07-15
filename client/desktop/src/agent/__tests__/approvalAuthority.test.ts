import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('approval runtime authority', () => {
  it('uses runtime events instead of a parallel Desktop approval queue', () => {
    const runtimeSource = readFileSync(resolve('src/agent/runtimeStore.ts'), 'utf8')
    const agentExports = readFileSync(resolve('src/agent/index.ts'), 'utf8')

    expect(runtimeSource).toContain("event.type === 'tool.request'")
    expect(runtimeSource).toContain("event.type === 'approval.result'")
    expect(agentExports).not.toContain('createApprovalQueue')
    expect(existsSync(resolve('src/agent/approvalQueue.ts'))).toBe(false)
  })
})
