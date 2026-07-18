import React from 'react'
import { ConfirmationCard } from '../../components/ConfirmationCard'
import { PermissionPrompt } from '../../components/PermissionPrompt'
import type { ToolEvent, WorkIntent } from '../../types'
import { isObsidianMarkdownPath } from './fileRefHelpers'

export function toolKind(event: ToolEvent): 'shell' | 'github' | 'file' | 'publish' {
  if (event.name === 'shell' || event.name === 'shell.execute') return 'shell'
  if (event.name === 'github' || event.name === 'github_ops') return 'github'
  if (event.name === 'hugo_blog') return 'publish'
  return 'file'
}

export function toolTitle(event: ToolEvent): string {
  if (event.name === 'memory.compact') return '已整理记忆'
  if (event.name === 'shell' || event.name === 'shell.execute') return 'Shell 命令'
  if (event.name === 'github' || event.name === 'github_ops') return 'GitHub 操作'
  if (event.name === 'hugo_blog') return '博客发布'
  if (event.name === 'file.reference') return isObsidianMarkdownPath(String(event.draft?.path || '')) ? 'Obsidian 文稿引用' : '本地文件引用'
  if (event.name === 'obsidian_read') return 'Obsidian 读取'
  if (event.name === 'obsidian_write') return 'Obsidian 写入'
  if (event.name.includes('obsidian')) return 'Obsidian 文档'
  return event.name
}

export function toolCompactText(event: ToolEvent, kind: 'shell' | 'github' | 'file' | 'publish'): string {
  if (kind === 'shell') return event.draft?.command ? `$ ${event.draft.command}` : event.summary || event.name
  if (kind === 'github') return [event.draft?.action, event.draft?.repo, event.draft?.title].filter(Boolean).join(' · ') || event.summary || event.name
  if (kind === 'publish') return event.draft?.title || event.draft?.path || '博客发布'
  return event.draft?.title || event.draft?.path || event.summary || toolTitle(event)
}

export function toolDisplayName(kind: 'shell' | 'github' | 'file' | 'publish', event: ToolEvent): string {
  if (kind === 'shell') return 'Shell 执行'
  if (kind === 'github') return 'GitHub 操作'
  if (kind === 'publish') return '博客发布'
  if (event.name === 'file.reference') return '文件引用'
  if (event.name === 'obsidian_write' || event.name === 'obsidian.read') return 'Obsidian 写入'
  return '文件操作'
}

export function toolTargetPreview(event: ToolEvent): { path?: string; url?: string; command?: string } | undefined {
  if (event.draft?.path) return { path: event.draft.path }
  if (event.draft?.targetUrl) return { url: event.draft.targetUrl }
  if (event.draft?.command) return { command: event.draft.command }
  return undefined
}

export function toolTarget(event: ToolEvent, kind: 'shell' | 'github' | 'file'): string {
  if (kind === 'shell') return event.draft?.command || event.detail || 'Shell 命令'
  if (kind === 'github') return [event.draft?.repo, event.draft?.title].filter(Boolean).join(' · ') || event.detail || 'GitHub'
  if (event.name === 'file.reference') return event.draft?.title || event.draft?.path || event.detail || '本地文件'
  return event.draft?.path || event.detail || '本地文件'
}

export function riskLabel(risk: ToolEvent['risk']): string {
  if (risk === 'critical') return '极高'
  if (risk === 'high') return '高'
  if (risk === 'medium') return '中'
  return '低'
}

export function statusLabel(status: ToolEvent['status'], needsApproval: boolean): string {
  if (needsApproval) return '等待确认'
  if (status === 'running') return '执行中'
  if (status === 'waiting') return '等待中'
  if (status === 'complete') return '已完成'
  if (status === 'blocked') return '失败或已阻止'
  if (status === 'denied') return '已放弃'
  return status
}

export function jobStatusLabel(status: import('../../../../agent').JobEvent['status'], stale?: boolean): string {
  if (status === 'queued') return '等待中'
  if (status === 'running') return '执行中'
  if (status === 'waiting_approval') return '等待确认'
  if (status === 'complete') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'cancelled' && stale) return '已取消（无进展超时）'
  if (status === 'cancelled') return '已取消'
  return status
}

export function backgroundRouteReasonLabel(reason: string): string {
  if (reason === 'large request') return '内容较长，适合后台持续处理'
  if (reason === 'implementation-style request') return '这是实现/修改类任务，适合后台执行'
  return '适合后台执行'
}

export function ToolEventBody({
  event,
  kind,
  needsApproval,
  onDecide,
}: {
  event: ToolEvent
  kind: 'shell' | 'github' | 'file' | 'publish'
  needsApproval: boolean
  onDecide: (decision: 'approved' | 'denied') => void
}) {
  const output = event.detail.startsWith('output: ') ? event.detail.slice(8) : ''
  const workIntent = event.draft?.workIntent
  if (workIntent) {
    if (needsApproval) {
      return (
        <ConfirmationCard
          workIntent={workIntent}
          toolEventId={event.id}
          risk={event.risk}
          toolDisplayName={toolDisplayName(kind, event)}
          targetPreview={toolTargetPreview(event)}
          onApprove={() => onDecide('approved')}
          onReject={() => onDecide('denied')}
        />
      )
    }
    return <WorkIntentBlock intent={workIntent} fallbackDetail={event.detail} />
  }

  if (kind === 'shell') {
    return (
      <div className="tool-terminal-block">
        {event.draft?.command && <code>$ {event.draft.command}</code>}
        <pre>{output || event.detail}</pre>
      </div>
    )
  }

  if (kind === 'github') {
    return (
      <div className="tool-path-block">
        <strong>{[event.draft?.action, event.draft?.repo, event.draft?.title].filter(Boolean).join(' · ') || event.name}</strong>
        {event.detail && <span>{event.detail}</span>}
      </div>
    )
  }

  if (kind === 'publish') {
    return (
      <div className="tool-path-block">
        <strong>{event.draft?.title || event.draft?.path || '博客文章'}</strong>
        {event.detail && <span>{event.detail}</span>}
      </div>
    )
  }

  if (event.name === 'file.reference') {
    if (event.status === 'blocked') {
      return (
        <PermissionPrompt
          level="read"
          reason={event.detail || '文件引用被阻止'}
          target={event.draft?.path ? { path: event.draft.path } : undefined}
        />
      )
    }
    return (
      <div className="tool-path-block">
        <strong>{event.draft?.title || event.draft?.path || event.detail || event.name}</strong>
        {event.draft?.path && <span>{event.draft.path}</span>}
        {event.draft?.injectedChars !== undefined && (
          <span>
            已注入 {event.draft.injectedChars} 字符
            {event.draft.truncated ? ' · 已截断' : ''}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="tool-path-block">
      <strong>{event.draft?.path || event.detail || event.name}</strong>
      {event.draft?.contentPreview && <span>{event.draft.contentPreview}</span>}
      {!event.draft?.contentPreview && event.detail && <span>{event.detail}</span>}
      {event.draft?.beforeText !== undefined && event.draft?.afterText !== undefined && (
        <div className="obsidian-diff-preview">
          {event.draft.previewExists && event.draft.beforeText ? (
            <div className="diff-side diff-before">
              <em>写入前</em>
              <pre>{event.draft.beforeText}</pre>
            </div>
          ) : (
            <div className="diff-side diff-empty">
              <em>笔记不存在，将新建</em>
            </div>
          )}
          <div className="diff-side diff-after">
            <em>写入后（{event.draft.previewMode || 'append'}）</em>
            <pre>{event.draft.afterText}</pre>
          </div>
        </div>
      )}
    </div>
  )
}

export function WorkIntentBlock({ intent, fallbackDetail }: { intent: WorkIntent; fallbackDetail: string }) {
  const targets = Array.isArray(intent.targets) ? intent.targets : []
  const steps = Array.isArray(intent.steps) ? intent.steps : []
  return (
    <div className="tool-path-block">
      <strong>{[intent.workflowName, intent.action].filter(Boolean).join(' · ') || '工作确认'}</strong>
      {targets.map((target, index) => (
        <span key={`${target.label || 'target'}-${index}`}>
          {[target.label, target.path || target.url].filter(Boolean).join('：')}
        </span>
      ))}
      {steps.length > 0 && <span>预计步骤：{steps.join(' → ')}</span>}
      {intent.verifyPlan && <span>验证：{intent.verifyPlan}</span>}
      {intent.rollbackPlan && <span>回滚：{intent.rollbackPlan}</span>}
      {!targets.length && fallbackDetail && <span>{fallbackDetail}</span>}
    </div>
  )
}
