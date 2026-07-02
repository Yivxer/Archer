import React from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import { AlertTriangle, Clipboard, Clock3, Search } from 'lucide-react'
import remarkGfm from 'remark-gfm'

export function ArcherRing({
  small = false,
  large = false,
  pulse = false,
  living = false
}: {
  small?: boolean
  large?: boolean
  pulse?: boolean
  living?: boolean
}) {
  const sizeClass = large ? 'large' : small ? 'small' : ''
  return (
    <span
      className={`archer-ring ${sizeClass} ${pulse ? 'pulse' : ''} ${living ? 'living' : ''}`.trim()}
      aria-hidden="true"
    >
      <span className="ring-base" />
      <span className="ring-shine" />
    </span>
  )
}

export function Badge({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>
}

export function FormField({
  label,
  value,
  onChange,
  readOnly = false,
  type = 'text',
  placeholder = '',
}: {
  label: string
  value: string
  onChange?: (value: string) => void
  readOnly?: boolean
  type?: string
  placeholder?: string
}) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        readOnly={readOnly}
        aria-readonly={readOnly}
        onChange={(event) => onChange?.(event.target.value)}
      />
    </label>
  )
}

export function SearchBox({
  placeholder,
  value,
  onChange
}: {
  placeholder: string
  value?: string
  onChange?: (value: string) => void
}) {
  return (
    <label className="search-box">
      <Search size={15} />
      <input placeholder={placeholder} value={value} onChange={(event) => onChange?.(event.target.value)} />
    </label>
  )
}

export function EmptyDetail({ icon: Icon, title, text }: { icon: React.ElementType; title: string; text: string }) {
  return (
    <div className="empty-detail">
      <Icon size={28} />
      <h2>{title}</h2>
      <p>{text}</p>
      <div className="empty-meta">
        <Clock3 size={15} />
        <span>等待连接</span>
      </div>
    </div>
  )
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = '确认',
  cancelLabel = '取消',
  tone = 'default',
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  tone?: 'default' | 'danger'
  onConfirm: () => void
  onCancel: () => void
}) {
  React.useEffect(() => {
    if (!open) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div className="confirm-overlay" role="presentation" onMouseDown={onCancel}>
      <section className={`confirm-dialog ${tone}`} role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <div className="confirm-mark">
          {tone === 'danger' ? <AlertTriangle size={17} /> : <ArcherRing small />}
        </div>
        <div className="confirm-copy">
          <h2>{title}</h2>
          <p>{message}</p>
        </div>
        <div className="confirm-actions">
          <button className="quiet-button" type="button" onClick={onCancel}>{cancelLabel}</button>
          <button className={`quiet-button strong ${tone === 'danger' ? 'danger-action' : ''}`} type="button" onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </section>
    </div>
  )
}

export function ThinkingDots() {
  return (
    <span className="thinking-indicator">
      <span className="thinking-ring" />
      <span className="thinking-text">
        思考中
        <span className="thinking-dots">
          <span className="dot" style={{ animationDelay: '0s' }}>.</span>
          <span className="dot" style={{ animationDelay: '0.18s' }}>.</span>
          <span className="dot" style={{ animationDelay: '0.36s' }}>.</span>
        </span>
      </span>
    </span>
  )
}

export function ThinkingMutter({ text }: { text: string }) {
  return (
    <span className="thinking-mutter" aria-live="polite">
      <span className="thinking-ring" />
      <span className="thinking-mutter-text">{text}</span>
    </span>
  )
}

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean; message: string }> {
  state = { hasError: false, message: '' }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, message: error.message }
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="error-boundary">
        <ArcherRing small />
        <h2>这个页面暂时没能正常显示</h2>
        <p>客户端界面遇到异常，但 Archer 进程仍在。可以返回对话，或重载窗口后继续。</p>
        {this.state.message && <code>{this.state.message}</code>}
        <button type="button" onClick={() => window.location.reload()}>
          重载窗口
        </button>
      </div>
    )
  }
}

export function MarkdownMessage({ text }: { text: string }) {
  return (
    <div className="markdown-message">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {text}
      </ReactMarkdown>
    </div>
  )
}

const markdownComponents: Components = {
  a({ href, children }) {
    return (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    )
  },
  strong({ children }) {
    return <strong className="md-strong">{children}</strong>
  },
  em({ children }) {
    return <em className="md-em">{children}</em>
  },
  hr() {
    return <hr className="md-hr" />
  },
  code({ children, className }) {
    const code = String(children ?? '').replace(/\n$/, '')
    const language = /language-(\w+)/.exec(className || '')?.[1] || ''
    const isBlock = Boolean(className) || code.includes('\n')

    if (!isBlock) {
      return <code className="inline-code">{children}</code>
    }

    return <CodeBlock code={code} language={language} />
  }
}

export function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = React.useState(false)

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }

  return (
    <figure className="code-block">
      <figcaption>
        <span>{language || 'code'}</span>
        <button type="button" onClick={copyCode}>
          <Clipboard size={12} />
          {copied ? '已复制' : '复制'}
        </button>
      </figcaption>
      <pre><code>{code}</code></pre>
    </figure>
  )
}
