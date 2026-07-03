# Archer Desktop 交互原语库（L4）

> 阶段 5（L4.1）产出。本文档是 8 个交互原语的 props 契约 + 视觉规范 + 旧组件迁移关系权威。
> 架构契约：[[Archer 稳定性框架]] §七（8 个原语 + 实现步骤 + 验收）。
> 关联：[[api-contract]] §failureHintEvent（ErrorRecovery 的 failureType 来源）。

## 文档目的

Archer 的特色元素（确认卡 / 工作回执 / Trace 面板 / 权限提示 / 附件上传 / 空状态 / 加载状态 / 错误恢复）现在散落在各页面，每个页面长得略不一样。L4 把它们正式化为 8 个原语组件，统一 props 契约 + 视觉规范，让特色**更稳定地存在**，而不是慢慢被各页面改散。

本文档是 **L4.1 的唯一产出**：只定契约，不写代码、不迁页面。L4.2-L4.9 按 §七实现步骤依次实现组件，L4.10-L4.14 再迁移页面。

---

## 通用约定

### Archer Ring 五色品牌（来源 `tokens.css`）

| Token | 色值 | 用途 |
|---|---|---|
| `--cyan` | `#4dd9d4` | 主色（流云青），success / primary action |
| `--blue` | `#1e7be8` | info / 链接 / 进行中 |
| `--amber` | `#f5c842` | warning / 等待确认 |
| `--orange` | `#f5612a` | high risk / 警告 |
| `--red` | `#e8212a` | danger / 错误 / critical |

### 字体

- 品牌/标题：`Comfortaa`（`--brand-font`）
- 正文：`LXGW WenKai`（`--body-font`）
- 代码/路径：`ui-monospace, SFMono-Regular, Menlo, monospace`

### 尺寸与圆角

- 卡片圆角：`12px`（主卡片）/ `8px`（内部子块）
- 内边距：`12px 16px`（标准卡）/ `8px 12px`（紧凑）
- 圆点/badge：`16px` 高
- 原语默认宽度：100%（由父容器决定），不自带最大宽度

### 状态色映射（统一）

| 状态 | Token | 含义 |
|---|---|---|
| success | `--cyan` | 完成 / 通过 |
| info | `--blue` | 进行中 / 提示 |
| warning | `--amber` | 等待用户操作 |
| high | `--orange` | 高风险 / 需注意 |
| danger | `--red` | 错误 / 拒绝 / critical |

### 不可变约束

1. **Archer Ring 五色品牌不动**（§十）—— 原语视觉必须基于上表五色，不引入第六色
2. **不重写 traceDiagnostics / runtimeStore / chatEventDispatcher** —— 原语只消费它们的输出
3. **不引入新依赖** —— 用现有 lucide-react 图标 + tokens.css，不引动画库
4. **原语不持有领域状态** —— 数据由父组件传入，原语只负责渲染 + 回调

---

## 1. `<ConfirmationCard />`

### 用途

工具执行前的确认卡。展示工作意图（workIntent）、风险等级、回滚计划，让用户决定 approve / reject。是 Archer 最有辨识度的元素之一。

### Props 签名

```typescript
import type { RiskLevel, WorkIntent } from '../types'

export type ConfirmationCardProps = {
  /** 工作意图（必填，来自 tool_event.draft.workIntent） */
  workIntent: WorkIntent
  /** 工具事件 id（用于回调追踪） */
  toolEventId: string
  /** 风险等级，决定卡片左边色条颜色（默认 'medium'） */
  risk?: RiskLevel  // default 'medium'
  /** 工具显示名（如 "Obsidian 写入" / "Shell 执行"），来自 tool_event.draft.displayName */
  toolDisplayName?: string
  /** 操作目标预览（path / url / command 任一） */
  targetPreview?: {
    path?: string
    url?: string
    command?: string
  }
  /** 是否禁用按钮（异步 approve/reject 进行中） */
  busy?: boolean  // default false
  /** 用户批准 */
  onApprove: (toolEventId: string) => void
  /** 用户拒绝 */
  onReject: (toolEventId: string) => void
  /** 可选：展开/收起 diff 预览（obsidian_write 专属） */
  onShowDiff?: () => void
}
```

### 视觉规范

- **左边色条**：4px 宽，颜色按 `risk`：low → `--cyan` / medium → `--amber` / high → `--orange` / critical → `--red`
- **卡片背景**：`var(--bg-2)` + 12px 圆角 + 1px border `var(--border)`
- **标题行**：`toolDisplayName` + risk badge（16px 高圆角徽章）
- **正文**：`workIntent.workflowName` + `workIntent.action` + `workIntent.targets[]`（每行 label: path/url）
- **步骤区**（可折叠）：`workIntent.steps[]` 有序列表
- **回滚计划**：灰色小字 `workIntent.rollbackPlan`，前缀「回滚计划：」
- **按钮区**：右下角「拒绝 / 批准」两个按钮，批准按钮主色 `--cyan`
- **busy 状态**：按钮 disabled + 显示 `<ThinkingDots />`

### 对应旧组件关系

| 旧位置 | 行号 | 迁移路径 |
|---|---|---|
| `pages/ChatPage.tsx` `ToolEventBody` 函数（处理 `event.draft.workIntent`） | 2139 | 抽出为 `<ConfirmationCard />`，ChatPage 改为 `<ConfirmationCard workIntent={event.draft.workIntent} ... />` |
| `pages/ChatPage.tsx` `chat-approval-dock` 相关逻辑（已删除） | — | 不再恢复，由 ConfirmationCard 替代 |

### 边界

- 不渲染执行结果（那是 `<WorkReceipt />` 的事）
- 不显示 traceId（那是 `<TracePanel />` 的事）
- 不处理权限等级（那是 `<PermissionPrompt />` 的事）；如果工具被 blocked，ConfirmationCard 不渲染，由 PermissionPrompt 渲染

---

## 2. `<WorkReceipt />`

### 用途

工具执行后的工作回执。展示「做了什么 / 来源 / 目标 / 验证方式 / 回滚方式」，是 Archer 区别于普通 ChatGPT 客户端的标志。

### Props 签名

```typescript
import type { WorkReceipt as WorkReceiptType } from '../types'

export type WorkReceiptProps = {
  /** 工作回执数据（必填，来自 tool_event.receipt） */
  receipt: WorkReceiptType
  /** 关联的 traceId（可选，用于跳转 TracePanel） */
  traceId?: string
  /** 是否显示「查看 trace」按钮（默认 true） */
  showTraceAction?: boolean  // default true
  /** 点击「查看 trace」回调 */
  onViewTrace?: (traceId: string) => void
}
```

### 视觉规范

- **卡片背景**：`var(--bg-2)` + 8px 圆角（比 ConfirmationCard 紧凑）
- **左边色条**：4px 宽，`--cyan`（success 色，回执 = 已完成）
- **标题**：`receipt.done`（粗体）
- **字段网格**（2 列）：
  - 来源 → `receipt.source`
  - 目标 → `receipt.target`
  - 验证 → `receipt.verification`
  - 回滚 → `receipt.rollback`（灰色小字）
- **trace 按钮**：右上角小图标按钮（`Activity` lucide icon，13px），点击触发 `onViewTrace`
- **无 traceId**：不显示 trace 按钮

### 对应旧组件关系

| 旧位置 | 行号 | 迁移路径 |
|---|---|---|
| `pages/ChatPage.tsx` `WorkReceiptBlock` 函数 | 2235 | 整体替换为 `<WorkReceipt receipt={event.receipt} traceId={...} onViewTrace={openTraceDiagnostics} />` |

### 边界

- 不渲染工作意图（那是 ConfirmationCard 的事）
- 不显示失败原因（失败时无 receipt，由 ErrorRecovery 渲染）
- 不自带展开/收起逻辑（父组件控制 mount/unmount）

---

## 3. `<TracePanel />`

### 用途

诊断信息展开面板。展示 traceId、runtime context、failure hint、最近事件流，帮助用户定位「为什么这一轮失败」。

### Props 签名

```typescript
import type { AgentEvent } from '../../../agent'
import type { TraceDiagnostics } from '../../../agent'

export type TracePanelProps = {
  /** 诊断数据（必填，来自 buildTraceDiagnostics） */
  diagnostics: TraceDiagnostics
  /** 是否默认展开 failureHint 区（默认 true，失败时优先看） */
  defaultExpandFailure?: boolean  // default true
  /** 关闭回调 */
  onClose: () => void
  /** 可选：重试回调（失败时显示「重试」按钮） */
  onRetry?: () => void
}
```

### 视觉规范

- **面板位置**：浮在聊天底部，宽度 100%，最大高度 40vh，可滚动
- **背景**：`var(--bg-2)` + 12px 圆角顶部 + 1px 顶部 border
- **顶部行**：traceId（mono 字体）+ 关闭按钮（`X` icon，13px）
- **runtime context 区**：`diagnostics.runtimeContext.runtimeContext` 字段，2 列 grid（task/phase/userIntent/lastResult/expectedNext）
- **failure hint 区**（可折叠，默认展开）：
  - keyword badge（颜色按 keyword：connection_failed → red / timeout → amber / permission → orange / empty_response → blue）
  - stage 小字
  - detail 正文
  - recoverable=true 时显示「重试」按钮
- **recent events 区**：`diagnostics.recentEvents[]` 时间线，每行 `type + summary`
- **empty 状态**：`diagnostics.empty === true` 显示「暂无诊断事件」

### 对应旧组件关系

| 旧位置 | 行号 | 迁移路径 |
|---|---|---|
| `pages/ChatPage.tsx` `TraceDiagnosticsPanel` 函数 | 1857 | 整体抽出为 `<TracePanel diagnostics={tracePanel} onClose={...} />`，保留 `buildTraceDiagnostics` 不动 |
| `lib/traceDiagnostics.ts` `buildTraceDiagnostics` | — | **不重写**，TracePanel 只消费其输出 |

### 边界

- 不重写 `buildTraceDiagnostics` / `TraceDiagnostics` 类型（已是稳定纯函数）
- 不自己 fetch events（由父组件传入 `diagnostics`）
- 不渲染 tool_event 详情（那是 ConfirmationCard/WorkReceipt 的事）

---

## 4. `<ErrorRecovery />`

### 用途

错误提示 + 恢复动作。与 L2 `chatEventDispatcher` 的失败类型联动，按 failureType 显示不同文案 + 恢复建议。

### Props 签名

```typescript
export type FailureType =
  | 'model_empty_response'
  | 'tool_executed_no_summary'
  | 'model_stream_timeout'
  | 'provider_connection_failed'
  | 'chat_busy'
  | 'context_trimmed'
  | 'tool_failed'
  | 'approval_rejected'
  | 'job_stale_cancelled'
  | 'approval_duplicated'

export type ErrorRecoveryProps = {
  /** 失败类型（必填，来自 dispatcher 输出或 failureHintEvent.keyword） */
  failureType: FailureType
  /** 关联 traceId（可选，用于跳转 TracePanel） */
  traceId?: string
  /** 自定义错误文案（覆盖默认文案，用于流内 error.detail） */
  detail?: string
  /** 是否可重试（默认按 failureType 推导，可显式覆盖） */
  recoverable?: boolean
  /** 重试回调（recoverable=true 时必须提供） */
  onRetry?: () => void
  /** 查看 trace 回调 */
  onViewTrace?: (traceId: string) => void
}
```

### 视觉规范

- **容器**：横排 `flex`，左边色条 4px（颜色按 failureType：connection/timeout → `--amber` / permission/rejected → `--orange` / empty/timeout → `--blue` / others → `--red`）
- **正文**：默认文案（见下表）或 `detail` 覆盖
- **右侧动作区**：
  - `recoverable=true`：「重试」按钮（主色 `--cyan`）
  - `traceId` 存在：「诊断」图标按钮（`Activity` icon）
- **紧凑高度**：36px（与 chat-error 一致）

### 默认文案表

| failureType | 默认文案 | recoverable |
|---|---|---|
| model_empty_response | 模型没有回复，可以重试一次 | true |
| tool_executed_no_summary | 已执行操作，详见上方卡片 | false |
| model_stream_timeout | 回复超时，请重试 | true |
| provider_connection_failed | 模型服务连接失败 | true |
| chat_busy | Archer 正在处理上一轮 | false |
| context_trimmed | 上下文已压缩，可继续 | false |
| tool_failed | 工具执行失败 | true |
| approval_rejected | 已拒绝操作 | false |
| job_stale_cancelled | 后台任务已过期取消 | false |
| approval_duplicated | 重复的确认请求，已忽略 | false |

### 对应旧组件关系

| 旧位置 | 行号 | 迁移路径 |
|---|---|---|
| `pages/ChatPage.tsx` `chat-error with-action` div | 1659, 1840 | 替换为 `<ErrorRecovery failureType={...} traceId={...} onRetry={...} onViewTrace={openTraceDiagnostics} />` |
| `lib/chatEventDispatcher.ts` 失败类型推导 | — | **不重写**，ErrorRecovery 只消费其 failureType 输出 |

### 边界

- 不自己推导 failureType（由 dispatcher 或 failureHintEvent 提供）
- 不渲染 trace 详情（跳转到 TracePanel）
- 不显示 tool_event 详情（跳转到 WorkReceipt/ConfirmationCard）

---

## 5. `<PermissionPrompt />`

### 用途

权限等级提示。当工具被 blocked（权限不足、degraded 模式、高危操作未确认）时显示原因 + 等级。

### Props 签名

```typescript
export type PermissionLevel = 'read' | 'write' | 'deploy' | 'shell'

export type PermissionPromptProps = {
  /** 权限等级（必填） */
  level: PermissionLevel
  /** 被阻止的原因（必填，来自 tool_event.detail 或 dispatcher） */
  reason: string
  /** 被阻止的操作目标（path / url / command） */
  target?: {
    path?: string
    url?: string
    command?: string
  }
  /** 是否可申请提权（默认 false，degraded 模式下为 true） */
  canEscalate?: boolean  // default false
  /** 申请提权回调（打开 SettingsPage 连接设置） */
  onEscalate?: () => void
  /** 关闭/忽略回调 */
  onDismiss?: () => void
}
```

### 视觉规范

- **左边色条**：4px，颜色按 level：read → `--blue` / write → `--amber` / deploy → `--orange` / shell → `--red`
- **图标**：`Shield` / `ShieldAlert` lucide icon（16px）
- **标题**：「需要 {level} 权限」/ 「{level} 权限被阻止」
- **正文**：`reason` + `target` 路径（mono 字体）
- **动作区**：
  - `canEscalate=true`：「前往设置」按钮（打开 SettingsPage）
  - 「忽略」文字按钮

### 对应旧组件关系

| 旧位置 | 行号 | 迁移路径 |
|---|---|---|
| `pages/ChatPage.tsx` `ToolEventBody` 中 `event.status === 'blocked'` 分支 | 2139+ | 抽出 blocked 分支为 `<PermissionPrompt level={...} reason={event.detail} target={...} />` |
| `lib/connectionState.ts` degraded 状态屏蔽逻辑 | — | **不重写**，PermissionPrompt 只渲染提示，屏蔽逻辑仍在 connectionState |

### 边界

- 不自己判断权限等级（由父组件根据 connectionState + tool_event 决定）
- 不执行提权操作（只触发 `onEscalate` 回调）
- 不与 ConfirmationCard 同时出现（blocked 时无 ConfirmationCard，反之亦然）

---

## 6. `<AttachmentUpload />`

### 用途

附件后台上传 + 状态展示。fire-and-forget 上传，发送时才显示状态，不阻塞用户输入。

### Props 签名

```typescript
import type { FileRef } from '../types'

export type AttachmentUploadProps = {
  /** 当前附件列表（必填，来自 ChatPage fileRefs state） */
  files: FileRef[]
  /** 渲染变体：'composer'（输入框上方 chip）/ 'message'（消息内回看） */
  variant: 'composer' | 'message'
  /** 单个附件重试回调（attachStatus='failed' 时显示重试按钮） */
  onRetry?: (path: string) => void
  /** 移除附件回调（仅 'composer' 变体） */
  onRemove?: (path: string) => void
}
```

### 视觉规范

- **composer 变体**（输入框上方）：
  - 容器：`file-ref-row` 横排 flex，gap 8px
  - chip：高 32px，宽 240px（含预览图时） / 自适应（纯文件名时）
  - 预览图：32x24，圆角 4px
  - 状态色点：8px 圆点，ready → `--cyan` / reading → `--blue`（pulse）/ ok → `--cyan` / failed → `--red`
  - 失败时：显示「重试」小按钮
- **message 变体**（消息内回看）：
  - 容器：`message-file-ref-row`，更紧凑
  - chip：高 24px，无重试/移除按钮（只读回看）
  - 状态色点同上

### 对应旧组件关系

| 旧位置 | 行号 | 迁移路径 |
|---|---|---|
| `pages/ChatPage.tsx` `file-ref-row` + `file-ref-chip`（composer 变体） | 1348 | 抽出为 `<AttachmentUpload variant="composer" files={fileRefs} onRemove={...} onRetry={...} />` |
| `pages/ChatPage.tsx` `message-file-ref-row` + `message-file-ref-chip`（message 变体） | 1715 | 抽出为 `<AttachmentUpload variant="message" files={message.fileRefs} />` |

### 边界

- 不自己管理 fileRefs state（由父组件传入）
- 不实现上传逻辑（上传在 `adapters/localArcher.ts`，原语只渲染状态）
- 不处理截图捕获（那是 composer 菜单的事，不是附件原语）

---

## 7. `<EmptyState />`

### 用途

统一空状态文案。各页面「没有数据」时的友好提示，避免每个页面自己拼。

### Props 签名

```typescript
import type { ReactNode } from 'react'

export type EmptyStateProps = {
  /** 标题（必填，如「暂无记忆」） */
  title: string
  /** 提示文案（可选，如「连接本地 API 后会读取」） */
  hint?: string
  /** 行动按钮（可选，ReactNode 让父组件控制样式） */
  action?: ReactNode
  /** 图标（可选，lucide icon 组件，默认 `Inbox`） */
  icon?: React.ElementType  // default Inbox
  /** 紧凑模式（行内，不占满屏，用于侧边栏小区域） */
  compact?: boolean  // default false
}
```

### 视觉规范

- **标准模式**（`compact=false`）：
  - 容器：垂直居中，padding 48px 24px
  - 图标：32px，颜色 `var(--text-tertiary)`
  - 标题：16px，`var(--text-secondary)`
  - hint：13px，`var(--text-tertiary)`
  - action：主色按钮，margin-top 16px
- **紧凑模式**（`compact=true`）：
  - 容器：`empty-inline`，padding 12px，左对齐
  - 图标：13px（与文字同高）
  - 标题 + hint 同行

### 对应旧组件关系

| 旧位置 | 行号 | 迁移路径 |
|---|---|---|
| `pages/TasksPage.tsx` `empty-inline` div | 170 | 替换为 `<EmptyState compact title={loadState === 'error' ? '任务读取失败' : '暂无后台任务'} />` |
| `pages/TodayPage.tsx` `today-empty` div | 258 | 替换为 `<EmptyState compact title="暂无可展示的主动候选" />` |
| `pages/ChatPage.tsx` `trace-empty` p | 1872 | 替换为 `<EmptyState compact title="暂无诊断事件" />` |
| `pages/MemoryPage.tsx` / `ReviewPage.tsx` / `SoulPage.tsx` 各自空状态 | — | L4.11-L4.14 迁移时统一替换 |

### 边界

- 不处理错误状态文案（错误用 ErrorRecovery，EmptyState 只处理「无数据」）
- 不自己定义文案（由父组件传入 title/hint）

---

## 8. `<LoadingState />`

### 用途

统一加载状态文案。各页面/区块「正在加载」时的提示，避免「读取中」「加载中」「正在拉取」各自表述。

### Props 签名

```typescript
export type LoadingStage = 'connecting' | 'fetching' | 'thinking' | 'applying'

export type LoadingStateProps = {
  /** 加载阶段（决定默认文案） */
  stage?: LoadingStage  // default 'fetching'
  /** 自定义文案（覆盖 stage 默认文案） */
  hint?: string
  /** 是否显示 ThinkingDots 动画（默认 true） */
  showDots?: boolean  // default true
  /** 紧凑模式（行内） */
  compact?: boolean  // default false
}
```

### 视觉规范

- **标准模式**：
  - 容器：垂直居中，padding 32px
  - ThinkingDots：3 个 6px 圆点 pulse 动画（`--cyan`）
  - 文案：13px，`var(--text-tertiary)`
- **紧凑模式**：
  - 容器：行内，gap 8px
  - ThinkingDots：3 个 4px 圆点
  - 文案：12px

### stage 默认文案表

| stage | 默认文案 |
|---|---|
| connecting | 正在连接 Archer... |
| fetching | 正在读取... |
| thinking | Archer 正在想... |
| applying | 正在应用... |

### 对应旧组件关系

| 旧位置 | 行号 | 迁移路径 |
|---|---|---|
| `pages/ChatPage.tsx` `ThinkingDots` + `ThinkingMutter` 使用 | 多处 | ThinkingDots 保留（原语内部用），ThinkingMutter 文案改用 `<LoadingState stage="thinking" hint={mutter} />` |
| `pages/ChatPage.tsx` session 加载状态 | — | 替换为 `<LoadingState stage="fetching" hint="正在读取会话" />` |
| 各页面 `loadState === 'loading'` 分支 | — | L4.10-L4.14 迁移时统一替换 |

### 边界

- 不替代 ThinkingDots 组件（LoadingState 内部使用 ThinkingDots）
- 不处理错误状态（加载失败用 ErrorRecovery）
- 不自己决定何时显示（由父组件根据 loadState 控制 mount/unmount）

---

## 实现顺序（与 §七一致）

1. **第一批**（最有辨识度）：`<ConfirmationCard />` + `<WorkReceipt />`
2. **第二批**（与 L2 联动）：`<TracePanel />` + `<ErrorRecovery />`
3. **第三批**（辅助）：`<PermissionPrompt />` + `<AttachmentUpload />` + `<EmptyState />` + `<LoadingState />`
4. **迁移**：L4.10-L4.14 按页面迁移（ChatPage → MemoryPage → TasksPage → ReviewPage → SoulPage），旧散落实现删除

---

## L4.1 验收清单

- [x] 8 个原语 props 签名定义完成（含可选/默认值/回调签名）
- [x] 每个原语有视觉规范（尺寸/颜色/状态）
- [x] 每个原语有对应旧组件关系（位置 + 迁移路径）
- [x] 通用约定（Archer Ring 五色 + 字体 + 尺寸 + 状态色映射）
- [x] 不做的事边界明确（每个原语「边界」段）
- [x] 与 §七架构契约一致（8 个原语 + 实现顺序 + 验收）
- [x] 与 L2 dispatcher 联动明确（ErrorRecovery failureType 来自 dispatcher）
- [x] 与 L3 store 关系明确（原语不持有领域状态，数据由父组件传入）

## 后续 L4.2-L4.14 实现约束

1. **每个原语实现后**：写单元测试（props 渲染 + 回调触发 + 边界 case）
2. **每个页面迁移后**：跑 `npx tsc --noEmit` + `npx vitest run` 确保无回归
3. **不重写**：`traceDiagnostics.ts` / `chatEventDispatcher.ts` / `connectionState.ts` / `runtimeStore.ts` 已稳定的层不动
4. **样式来源**：原语用 `tokens.css` 变量 + `styles/base.css` 既有 class，不新建 css 文件（除非原语专属样式超过 30 行）
5. **Archer Ring 五色品牌**：每个原语至少一处使用五色之一（色条 / badge / 图标色），保持视觉辨识度
