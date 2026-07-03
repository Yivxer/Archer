/**
 * L4.6 — <PermissionPrompt /> 组件测试。
 *
 * 测试策略：
 *   - 用 react-dom/server 静态渲染 + 字符串断言
 *   - 覆盖：4 级色条、图标、标题文案、reason、target 渲染、
 *     canEscalate + onEscalate 提权按钮、onDismiss 忽略按钮、data-* 属性
 */

import { describe, expect, it } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { PermissionPrompt, type PermissionLevel } from '../PermissionPrompt'

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
}

// ── 4 级色条 ────────────────────────────────────────────────

describe('PermissionPrompt — L4.6 4 级色条', () => {
  const levels: Array<{ level: PermissionLevel; tone: string; label: string }> = [
    { level: 'read', tone: 'blue', label: '读取' },
    { level: 'write', tone: 'amber', label: '写入' },
    { level: 'deploy', tone: 'orange', label: '部署' },
    { level: 'shell', tone: 'red', label: '命令' },
  ]

  for (const { level, tone, label } of levels) {
    it(`${level} → ${tone} 色条 + 「${label}权限被阻止」标题`, () => {
      const html = render(
        <PermissionPrompt level={level} reason="权限不足" />,
      )
      expect(html).toContain(`permission-prompt-tone-${tone}`)
      expect(html).toContain(`${label}权限被阻止`)
    })
  }
})

// ── 基础渲染 ────────────────────────────────────────────────

describe('PermissionPrompt — 基础渲染', () => {
  it('渲染 permission-prompt 容器 + aria-label', () => {
    const html = render(<PermissionPrompt level="read" reason="x" />)
    expect(html).toContain('class="permission-prompt')
    expect(html).toContain('aria-label="权限提示"')
  })

  it('渲染左边色条', () => {
    const html = render(<PermissionPrompt level="read" reason="x" />)
    expect(html).toContain('permission-prompt-stripe')
  })

  it('data-level 注入', () => {
    const html = render(<PermissionPrompt level="shell" reason="x" />)
    expect(html).toContain('data-level="shell"')
  })

  it('渲染 reason 文案', () => {
    const html = render(
      <PermissionPrompt level="write" reason="vault 路径无写权限" />,
    )
    expect(html).toContain('vault 路径无写权限')
    expect(html).toContain('permission-prompt-reason')
  })
})

// ── 图标 ────────────────────────────────────────────────────

describe('PermissionPrompt — 图标选择', () => {
  it('read → Shield 图标', () => {
    const html = render(<PermissionPrompt level="read" reason="x" />)
    // Shield 图标存在（lucide-react 会渲染 svg）
    expect(html).toContain('permission-prompt-icon')
  })

  it('shell → ShieldAlert 图标', () => {
    const html = render(<PermissionPrompt level="shell" reason="x" />)
    expect(html).toContain('permission-prompt-icon')
  })

  it('deploy → ShieldAlert 图标', () => {
    const html = render(<PermissionPrompt level="deploy" reason="x" />)
    expect(html).toContain('permission-prompt-icon')
  })
})

// ── target 渲染 ────────────────────────────────────────────

describe('PermissionPrompt — target 渲染', () => {
  it('target.path 提供时渲染 path', () => {
    const html = render(
      <PermissionPrompt
        level="write"
        reason="x"
        target={{ path: '/vault/notes.md' }}
      />,
    )
    expect(html).toContain('permission-prompt-target-path')
    expect(html).toContain('/vault/notes.md')
  })

  it('target.url 提供时渲染 url', () => {
    const html = render(
      <PermissionPrompt
        level="deploy"
        reason="x"
        target={{ url: 'https://example.com' }}
      />,
    )
    expect(html).toContain('permission-prompt-target-url')
    expect(html).toContain('https://example.com')
  })

  it('target.command 提供时渲染 command', () => {
    const html = render(
      <PermissionPrompt
        level="shell"
        reason="x"
        target={{ command: 'rm -rf /' }}
      />,
    )
    expect(html).toContain('permission-prompt-target-command')
    expect(html).toContain('rm -rf /')
  })

  it('target 缺失时不渲染 target 区', () => {
    const html = render(<PermissionPrompt level="read" reason="x" />)
    expect(html).not.toContain('permission-prompt-target')
  })

  it('target 全空对象时不渲染 target 区', () => {
    const html = render(
      <PermissionPrompt level="read" reason="x" target={{}} />,
    )
    expect(html).not.toContain('permission-prompt-target')
  })

  it('多字段优先 path', () => {
    const html = render(
      <PermissionPrompt
        level="write"
        reason="x"
        target={{ path: '/p', url: 'https://u', command: 'c' }}
      />,
    )
    expect(html).toContain('permission-prompt-target-path')
    expect(html).toContain('/p')
    expect(html).not.toContain('https://u')
    expect(html).not.toContain('>c<')
  })
})

// ── canEscalate + onEscalate 提权按钮 ──────────────────────

describe('PermissionPrompt — 提权按钮', () => {
  it('canEscalate=true + onEscalate 提供 → 渲染提权按钮', () => {
    const html = render(
      <PermissionPrompt
        level="shell"
        reason="x"
        canEscalate
        onEscalate={() => {}}
      />,
    )
    expect(html).toContain('permission-prompt-escalate')
    expect(html).toContain('aria-label="前往设置"')
    expect(html).toContain('前往设置')
  })

  it('canEscalate 默认 false → 不渲染提权按钮', () => {
    const html = render(
      <PermissionPrompt level="shell" reason="x" onEscalate={() => {}} />,
    )
    expect(html).not.toContain('permission-prompt-escalate')
  })

  it('canEscalate=true 但 onEscalate 缺失 → 不渲染提权按钮', () => {
    const html = render(
      <PermissionPrompt level="shell" reason="x" canEscalate />,
    )
    expect(html).not.toContain('permission-prompt-escalate')
  })

  it('canEscalate=false 显式 + onEscalate 提供 → 不渲染提权按钮', () => {
    const html = render(
      <PermissionPrompt
        level="shell"
        reason="x"
        canEscalate={false}
        onEscalate={() => {}}
      />,
    )
    expect(html).not.toContain('permission-prompt-escalate')
  })
})

// ── onDismiss 忽略按钮 ─────────────────────────────────────

describe('PermissionPrompt — 忽略按钮', () => {
  it('onDismiss 提供 → 渲染忽略按钮', () => {
    const html = render(
      <PermissionPrompt level="read" reason="x" onDismiss={() => {}} />,
    )
    expect(html).toContain('permission-prompt-dismiss')
    expect(html).toContain('aria-label="忽略"')
  })

  it('onDismiss 缺失 → 不渲染忽略按钮', () => {
    const html = render(<PermissionPrompt level="read" reason="x" />)
    expect(html).not.toContain('permission-prompt-dismiss')
  })
})

// ── 组合场景 ────────────────────────────────────────────────

describe('PermissionPrompt — 组合场景', () => {
  it('全部 props 提供：渲染完整结构', () => {
    const html = render(
      <PermissionPrompt
        level="shell"
        reason="高危命令需提权"
        target={{ command: 'sudo rm -rf /' }}
        canEscalate
        onEscalate={() => {}}
        onDismiss={() => {}}
      />,
    )
    expect(html).toContain('permission-prompt-tone-red')
    expect(html).toContain('命令权限被阻止')
    expect(html).toContain('高危命令需提权')
    expect(html).toContain('sudo rm -rf /')
    expect(html).toContain('permission-prompt-escalate')
    expect(html).toContain('permission-prompt-dismiss')
  })
})
