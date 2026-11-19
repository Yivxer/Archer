import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../adapters/localArcher', () => ({ toggleSkill: vi.fn() }))

import { SkillsPage } from './SkillsPage'
import type { ArcherAdapter } from '../types'

function page(skills: object[], adapter: 'local' | 'preview' = 'local') {
  const data = {
    status: { adapter },
    skills,
  } as unknown as ArcherAdapter
  return renderToStaticMarkup(<SkillsPage data={data} onRefresh={async () => undefined} />)
}

describe('SkillsPage catalog projection', () => {
  it('shows the registered contract and a redacted approval record', () => {
    const html = page([{
      name: 'github_ops',
      description: '通过 gh CLI 操作 GitHub',
      risk: 'high',
      enabled: true,
      permissionLevel: 'deploy-remote',
      permissionBasis: 'ceiling',
      approval: 'required',
      inputSummary: '必填 action',
      outputSummary: '未声明结构化输出',
      recentApproval: {
        state: 'recorded',
        count: 1,
        latest: {
          decision: 'denied',
          executed: false,
          permissionLevel: 'deploy-remote',
          policyReason: 'SECRET_REASON',
          message: 'SECRET_BODY',
          args: { command: 'SECRET_COMMAND' },
        },
      },
    }])
    expect(html).toContain('github_ops')
    expect(html).toContain('权限最高到远程部署')
    expect(html).toContain('需要审批')
    expect(html).toContain('必填 action')
    expect(html).toContain('未声明结构化输出')
    expect(html).toContain('最近审批：已拒绝，未执行，记录权限 远程部署（窗口内 1 条）')
    expect(html).not.toContain('SECRET_REASON')
    expect(html).not.toContain('SECRET_BODY')
    expect(html).not.toContain('SECRET_COMMAND')
  })

  it('does not present missing permission or approval as safe', () => {
    const html = page([{
      name: 'preview_skill',
      description: '预览里没有契约字段',
      risk: 'low',
      enabled: true,
      requiresApproval: false,
      permissionLevel: 'read-only-looking',
    }], 'preview')
    expect(html).toContain('权限未知')
    expect(html).toContain('审批未知')
    expect(html).toContain('最近审批：暂时读不到记录')
    expect(html).not.toContain('只读')
    expect(html).not.toContain('不要求审批')
    expect(html).not.toContain('无须审批')
    expect(html).toContain('低风险')
  })

  it('keeps an unknown risk off the low-risk label', () => {
    const html = page([{
      name: 'site_check',
      description: '检查站点',
      risk: 'unexpected',
      enabled: false,
      permissionLevel: 'read-only',
      permissionBasis: 'fixed',
      approval: 'not_required',
      inputSummary: '必填 url',
      outputSummary: '未声明结构化输出',
      recentApproval: { state: 'none', count: 0, latest: null },
    }])
    expect(html).toContain('风险未知')
    expect(html).not.toContain('低风险')
    expect(html).toContain('权限 只读')
    expect(html).toContain('当前策略不要求审批')
    expect(html).toContain('最近审批：窗口内没有记录')
    expect(html).toContain('已禁用')
  })
})
