import React from 'react'
import { Badge } from '../components/common'
import { toggleSkill } from '../adapters/localArcher'
import {
  approvalText,
  permissionText,
  projectSkillCards,
  recentApprovalText,
  riskText,
  type SkillCatalogCard,
} from '../lib/skillCatalog'
import type { ArcherAdapter } from '../types'

export function SkillsPage({ data, onRefresh }: { data: ArcherAdapter; onRefresh: () => Promise<void> }) {
  const [busyName, setBusyName] = React.useState<string | null>(null)
  const [message, setMessage] = React.useState('')
  const skills = projectSkillCards(data.skills)

  async function handleToggle(name: string, currentEnabled: boolean) {
    if (data.status.adapter !== 'local') return
    setBusyName(name)
    setMessage('')
    try {
      await toggleSkill(name, !currentEnabled)
      await onRefresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '切换失败')
    } finally {
      setBusyName(null)
    }
  }

  return (
    <div className="skills-page">
      {message && <div className="memory-state">{message}</div>}
      {skills.length === 0 ? (
        <div className="memory-state">没有已注册技能</div>
      ) : (
        <div className="skills-grid">
          {skills.map((skill) => (
            <article className="skill-card" key={skill.name}>
              <div className="section-head compact">
                <div>
                  <h2>{skill.name}</h2>
                  <p>{skill.description}</p>
                </div>
                <Badge tone={riskTone(skill)}>{riskText(skill.risk)}</Badge>
              </div>
              <dl className="skill-facts">
                <div className={factClass(skill.permissionLevel === 'unknown')}>
                  <dt>权限</dt>
                  <dd>{permissionText(skill)}</dd>
                </div>
                <div className={factClass(skill.approval === 'unknown')}>
                  <dt>审批</dt>
                  <dd>{approvalText(skill)}</dd>
                </div>
                <div>
                  <dt>输入</dt>
                  <dd>{skill.inputSummary}</dd>
                </div>
                <div>
                  <dt>输出</dt>
                  <dd>{skill.outputSummary}</dd>
                </div>
                <div className={factClass(skill.recentApproval.state === 'unavailable')}>
                  <dt>最近</dt>
                  <dd>{recentApprovalText(skill)}</dd>
                </div>
              </dl>
              <div className="skill-footer">
                <span>{data.status.adapter === 'local' ? '来自本地 API' : '预览数据'}</span>
                {data.status.adapter === 'local' ? (
                  <button
                    className={`quiet-button ${skill.enabled ? '' : 'skill-disabled-btn'}`}
                    type="button"
                    disabled={busyName === skill.name}
                    onClick={() => handleToggle(skill.name, skill.enabled)}
                  >
                    {busyName === skill.name ? '切换中' : skill.enabled ? '已启用' : '已禁用'}
                  </button>
                ) : (
                  <strong className={`skill-state ${skill.enabled ? 'enabled' : 'disabled'}`}>
                    {skill.enabled ? '可用' : '不可用'}
                  </strong>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}

function riskTone(skill: SkillCatalogCard): string {
  if (skill.risk === 'critical' || skill.risk === 'high') return 'danger'
  if (skill.risk === 'medium' || skill.risk === 'unknown') return 'warning'
  return 'accent'
}

function factClass(unknown: boolean): string {
  return unknown ? 'skill-fact skill-fact-unknown' : 'skill-fact'
}
