export const SKILL_PERMISSIONS = ['read-only', 'write-local', 'write-vault', 'deploy-remote'] as const
export const SKILL_APPROVALS = ['required', 'not_required', 'conditional'] as const
export const SKILL_RISKS = ['low', 'medium', 'high', 'critical'] as const

export type SkillPermission = (typeof SKILL_PERMISSIONS)[number] | 'unknown'
export type SkillApproval = (typeof SKILL_APPROVALS)[number] | 'unknown'
export type SkillRisk = (typeof SKILL_RISKS)[number] | 'unknown'
export type SkillPermissionBasis = 'fixed' | 'ceiling' | 'unknown'

export type SkillRecentApproval = {
  state: 'recorded' | 'none' | 'unavailable'
  count: number
  latest: {
    decision: 'approved' | 'denied' | 'unknown'
    executed: boolean
    permissionLevel: SkillPermission
  } | null
}

export type SkillCatalogCard = {
  name: string
  description: string
  risk: SkillRisk
  enabled: boolean
  permissionLevel: SkillPermission
  permissionBasis: SkillPermissionBasis
  approval: SkillApproval
  inputSummary: string
  outputSummary: string
  recentApproval: SkillRecentApproval
}

const PERMISSION_LABELS: Record<SkillPermission, string> = {
  'read-only': '只读',
  'write-local': '本地写入',
  'write-vault': '库写入',
  'deploy-remote': '远程部署',
  unknown: '权限未知',
}

function asRecord(value: object): Record<string, unknown> {
  return value as Record<string, unknown>
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T | 'unknown' {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value) ? value as T : 'unknown'
}

function projectRecent(value: unknown): SkillRecentApproval {
  if (!value || typeof value !== 'object') {
    return { state: 'unavailable', count: 0, latest: null }
  }
  const raw = asRecord(value)
  const state = raw.state === 'recorded' || raw.state === 'none' || raw.state === 'unavailable'
    ? raw.state
    : 'unavailable'
  const count = typeof raw.count === 'number' && raw.count > 0 ? Math.floor(raw.count) : 0
  const latestRaw = raw.latest
  if (state !== 'recorded' || !latestRaw || typeof latestRaw !== 'object') {
    return { state: state === 'recorded' ? 'none' : state, count: 0, latest: null }
  }
  const latest = asRecord(latestRaw)
  const decision = latest.decision === 'approved' || latest.decision === 'denied' ? latest.decision : 'unknown'
  return {
    state: 'recorded',
    count: Math.max(count, 1),
    latest: {
      decision,
      executed: latest.executed === true,
      permissionLevel: oneOf(latest.permissionLevel, SKILL_PERMISSIONS),
    },
  }
}

export function projectSkillCard(raw: object): SkillCatalogCard {
  const row = asRecord(raw)
  const permissionLevel = oneOf(row.permissionLevel, SKILL_PERMISSIONS)
  const permissionBasis = row.permissionBasis === 'fixed' || row.permissionBasis === 'ceiling'
    ? row.permissionBasis
    : 'unknown'
  return {
    name: typeof row.name === 'string' && row.name.trim() ? row.name : '未命名技能',
    description: typeof row.description === 'string' ? row.description : '',
    risk: oneOf(row.risk, SKILL_RISKS),
    enabled: row.enabled !== false,
    permissionLevel,
    permissionBasis: permissionLevel === 'unknown' ? 'unknown' : permissionBasis,
    approval: oneOf(row.approval, SKILL_APPROVALS),
    inputSummary: typeof row.inputSummary === 'string' && row.inputSummary.trim()
      ? row.inputSummary
      : '未从注册源解析到输入声明',
    outputSummary: typeof row.outputSummary === 'string' && row.outputSummary.trim()
      ? row.outputSummary
      : '未声明结构化输出',
    recentApproval: projectRecent(row.recentApproval),
  }
}

export function projectSkillCards(skills: readonly object[]): SkillCatalogCard[] {
  return skills.map((skill) => projectSkillCard(skill))
}

export function permissionText(skill: SkillCatalogCard): string {
  if (skill.permissionLevel === 'unknown') return '权限未知'
  const label = PERMISSION_LABELS[skill.permissionLevel]
  return skill.permissionBasis === 'ceiling' ? `权限最高到${label}` : `权限 ${label}`
}

export function approvalText(skill: SkillCatalogCard): string {
  if (skill.approval === 'required') return '需要审批'
  if (skill.approval === 'not_required') return '当前策略不要求审批'
  if (skill.approval === 'conditional') return '是否审批视参数而定'
  return '审批未知'
}

export function riskText(risk: SkillRisk): string {
  if (risk === 'critical') return '极高风险'
  if (risk === 'high') return '高风险'
  if (risk === 'medium') return '中风险'
  if (risk === 'low') return '低风险'
  return '风险未知'
}

export function recentApprovalText(skill: SkillCatalogCard): string {
  const recent = skill.recentApproval
  if (recent.state === 'unavailable') return '最近审批：暂时读不到记录'
  if (recent.state !== 'recorded' || !recent.latest) return '最近审批：窗口内没有记录'
  const decision = recent.latest.decision === 'approved'
    ? '已批准'
    : recent.latest.decision === 'denied'
      ? '已拒绝'
      : '决策未知'
  const executed = recent.latest.executed ? '已执行' : '未执行'
  const level = recent.latest.permissionLevel === 'unknown'
    ? '权限未知'
    : PERMISSION_LABELS[recent.latest.permissionLevel]
  return `最近审批：${decision}，${executed}，记录权限 ${level}（窗口内 ${recent.count} 条）`
}
