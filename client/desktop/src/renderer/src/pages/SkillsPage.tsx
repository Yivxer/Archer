import React from 'react'
import { Badge } from '../components/common'
import { toggleSkill } from '../adapters/localArcher'
import type { ArcherAdapter } from '../types'

export function SkillsPage({ data, onRefresh }: { data: ArcherAdapter; onRefresh: () => Promise<void> }) {
  const [busyName, setBusyName] = React.useState<string | null>(null)
  const [message, setMessage] = React.useState('')

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
      <div className="skills-grid">
        {data.skills.map((skill) => (
          <article className="skill-card" key={skill.name}>
            <div className="section-head compact">
              <div>
                <h2>{skill.name}</h2>
                <p>{skill.description}</p>
              </div>
              <Badge
                tone={
                  skill.risk === 'critical' || skill.risk === 'high'
                    ? 'danger'
                    : skill.risk === 'medium'
                      ? 'warning'
                      : 'accent'
                }
              >
                {riskText(skill.risk)}
              </Badge>
            </div>
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
    </div>
  )
}

function riskText(risk: ArcherAdapter['skills'][number]['risk']): string {
  if (risk === 'critical') return '极高风险'
  if (risk === 'high') return '高风险'
  if (risk === 'medium') return '中风险'
  return '低风险'
}
