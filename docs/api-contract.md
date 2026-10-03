# Archer Desktop API 契约

本地 HTTP API，默认 `http://127.0.0.1:8765`。实现：`terminal/api/fastapi_app.py`（FastAPI + uvicorn）；路由逻辑：`terminal/api/_routes.py`。

启动示例：

```bash
cd ~/Projects/Archer
.venv/bin/python terminal/archer_api.py --port 8765 --token <你的口令>
```

Legacy：`--legacy` 使用 `BaseHTTPRequestHandler`。

---

## 认证

| 项 | 值 |
|----|-----|
| 方式 | Bearer Token |
| Header | `Authorization: Bearer <desktop_api_token>` |
| 启动参数 | `--token <desktop_api_token>` |
| 公开路径 | `GET /health`、`GET /ready`（无需 token） |

未授权响应：

```json
HTTP 401
{ "error": "unauthorized", "message": "desktop API token is required" }
```

WebSocket：`/ws/chat?token=<token>` 或 `Authorization: Bearer …`。

---

## 通用约定

- **Content-Type**：`application/json`（POST）
- **CORS**：允许 Desktop dev（`localhost:5173`）与 packaged `null` origin
- **请求体上限**：128KB（`/chat/stream` 除外，由流式处理）
- **限流**（按客户端 IP）：
  - 普通端点：令牌桶 30 / 2 req/s
  - `/chat/stream`：6 / 0.5 req/s
- **错误体**：

```json
{
  "error": "<code>",
  "message": "<human readable>",
  "timestamp": "2026-06-13T12:00:00+00:00"   // 部分 429 响应
}
```

| HTTP | error | 含义 |
|------|-------|------|
| 400 | `validation_error` | 参数非法 / ValueError |
| 401 | `unauthorized` | token 缺失或不匹配 |
| 404 | `not_found` | 路径或资源不存在 |
| 413 | `payload_too_large` | 请求体 > 128KB |
| 429 | `rate_limited` | 触发限流 |
| 500 | `server_error` | 未捕获异常 |

---

## 核心端点

### `GET /health`

无需认证。

**响应 200**

```json
{ "ok": true }
```

### `GET /ready`

Readiness check. Public endpoint.

```json
{ "ok": true, "ready": true, "runtime": "fastapi" }
```

---

### `GET /status`

**响应 200**

```json
{
  "adapter": "local",
  "model": "deepseek-chat",
  "modelProfile": "lite",
  "expertId": "default",
  "expertLabel": "基础 Archer",
  "mode": "auto",
  "memoryCount": 42,
  "pendingMemoryCount": 3,
  "skillCount": 28,
  "accountName": "",
  "isLoggedIn": false,
  "archerId": "",
  "tokenUsage": {
    "sessionTotal": { "promptTokens": 0, "completionTokens": 0, "totalTokens": 0 },
    "lastCall": { "promptTokens": 0, "completionTokens": 0, "totalTokens": 0 },
    "limit": 1000000,
    "percentUsed": 0.0
  }
}
```

---

### `POST /chat`

非流式单轮回复（测试/简单客户端）。

**请求**

```json
{
  "messages": [
    { "role": "user", "content": "你好" }
  ]
}
```

**响应 200**

```json
{
  "role": "assistant",
  "text": "…"
}
```

---

### `POST /chat/stream`

SSE 流式聊天（Desktop 主路径）。

**请求**

```json
{
  "messages": [ { "role": "user", "content": "…" } ],
  "memoryMode": "conservative",
  "obsidianMode": "summary",
  "fileRefs": [
    { "path": "/abs/path/to/file.md", "name": "file.md" }
  ]
}
```

| 字段 | 值 | 说明 |
|------|-----|------|
| `memoryMode` | `off` / `conservative` / `full` | 记忆注入强度 |
| `obsidianMode` | `off` / `summary` / `full` | 笔记上下文 |
| `fileRefs` | array | 可选本地文件引用 |

**响应**：`text/event-stream`，每行 `data: {JSON}\n\n`

常见 event `type`：

| type | 说明 |
|------|------|
| `orchestrationEvent` | 意图 / mode / 技能匹配 |
| `planEvent` | 多步任务计划 |
| `toolEvent` | 工具执行进度（name, status, risk, summary, detail） |
| `ready` | 即将输出 token |
| `token` | 文本增量 `{ "text": "…" }` |
| `error` | 流内错误 `{ "detail": "…" }` |
| `done` | 本轮结束 |

流结束后后台触发记忆提炼（`_bg_extract_api`）。

---

### `GET /jobs` · `POST /jobs`

后台任务（持久化 `memory/background_jobs.json`）。

**POST /jobs 请求**

```json
{
  "title": "分析日志",
  "kind": "analysis",
  "prompt": "总结最近错误",
  "autoStart": true,
  "timeoutSeconds": 300,
  "parentJobId": "job-abc123"
}
```

**响应 200**

```json
{
  "ok": true,
  "job": {
    "id": "job-a1b2c3d4",
    "title": "…",
    "kind": "analysis",
    "prompt": "…",
    "status": "queued",
    "result": "",
    "createdAt": "2026-06-13T10:00:00",
    "updatedAt": "2026-06-13T10:00:00",
    "timeoutSeconds": 300
  }
}
```

**GET /jobs/{id}** → `{ "ok": true, "job": { …, "children": [ … ] } }`

**POST 动作**

| 路径 | 说明 |
|------|------|
| `/jobs/{id}/cancel` | 取消 |
| `/jobs/{id}/retry` | 失败重试 |
| `/jobs/{id}/approve` | 批准待确认工具 |
| `/jobs/{id}/spawn` |  spawn 子任务 |

`status`：`queued` | `running` | `waiting_approval` | `complete` | `failed` | `cancelled`

---

### `GET /memory` · 记忆 CRUD

**GET /memory** — 列表（pending 在前）

Query：`include_rejected=true` 含已拒绝 pending。

**条目字段**

```json
{
  "id": 1,
  "status": "pending",
  "type": "insight",
  "content": "…",
  "confidence": "0.85",
  "source": "extract",
  "depth": 3,
  "blockType": "insight",
  "label": "",
  "suggestReason": "…"
}
```

**POST**

| 路径 | Body | 说明 |
|------|------|------|
| `/memory/pending/{id}/accept` | `{}` | 接受 → 写入 memories |
| `/memory/pending/{id}/reject` | `{}` | 拒绝 |
| `/memory/pending/batch/accept` | `{}` | 批量接受 |
| `/memory/pending/batch/reject` | `{}` | 批量拒绝 |
| `/memory/update` | `{ "id", "content" }` | 更新正文 |
| `/memory/evolve` | `{ "id", "content", "type?", "importance?", "depth?" }` | 演化写入 |

**GET 扩展**

| 路径 | 说明 |
|------|------|
| `/memory/stats` | 计数、分组、矛盾、过期 |
| `/memory/groups` | 按 Memory Block 分组详情 |

---

## SSE 事件契约（L2.1）

`POST /chat/stream` 与 `WS /ws/chat` 共用同一份 SSE 事件流。本节为完整事件类型清单 + 顺序契约；前端 `chatEventDispatcher.ts`（L2.2）依据本契约消费事件。

### 事件类型清单（13 种）

| `type` | 载荷字段 | 后端来源 | 客户端处理 |
|---|---|---|---|
| `orchestrationEvent` | `orchestrationEvent: {intent, subIntent, mode, depth, labels[], needsMemory, needsJob}` | `_tools.py` 主路径起始 | 进 trace log，不渲染聊天 |
| `planEvent` | `planEvent: {title, status, detail, steps[], prompt?}` | 多步任务时 | 进 trace log + 显示 plan 卡 |
| `runtimeContextEvent` | `runtimeContextEvent: {task, phase, userIntent, lastResult, expectedNext, matchedSkills?}` | 主路径起始 | 进 trace log |
| `statusEvent` | `statusEvent: {intentType, intentLabel, matchedSkills[], isBackground, memoryScope[]}` | 主路径起始 | 进 trace log |
| `initiativeEvent` | `initiativeEvent: {kind, title, message, shadow, delivered, decisionTrace}` | Part 8 shadow 投递 | 进 trace log + 转发父组件，**不渲染到聊天**（L2.5 边界） |
| `tool_event` | `toolEvent: {id, name, displayName, status, risk, summary, detail, args, requiresApproval, blocked, ...}` | 工具执行 | 渲染工具卡 + 进 trace log |
| `ready` | `{ready: true}` | 模型开始生成 | 标记进入 streaming 状态 |
| `token` | `{text: "..."}` | 流式文本增量 | 拼接显示 |
| `vault_sources` | `{sources: [...]}` | Obsidian focus 模式 | 渲染上下文提示（当前前端忽略） |
| `failureHintEvent` | `failureHintEvent: {keyword, stage, recoverable, detail, id, traceId}` | 失败兜底 | dispatcher 决定 UI 表现（见下节） |
| `error` | `{detail: "..."}` | 流内异常 | 流终止，不再继续 |
| `done` | `{done: true}` | 流结束 | 关闭流 |
| `heartbeat` | `{}` | 保活 | 客户端忽略 |

### 顺序契约

1. **元信息先于 token**：`orchestrationEvent` / `planEvent` / `runtimeContextEvent` / `statusEvent` / `initiativeEvent` 在主路径开始时一次性发出，必须先于 `token`
2. **`ready` 必须先于 `token`**：`ready` 表示模型已开始生成
3. **`tool_event` 与 `token` 可交错**：模型先调工具再总结时，`tool_event` → `token` 顺序；工具执行中可继续流式输出
4. **`failureHintEvent` 必须先于 `error`/`done`**：失败时先发 `failureHintEvent`，再发 `error`（流内错误）或直接 `done`（兜底）
5. **`done` 必须是最后一个事件**：客户端收到 `done` 后关闭流，之后不应再有事件
6. **`heartbeat` 可在任意位置出现**：客户端应忽略
7. **`vault_sources` 必须先于 `token`**：在 Obsidian focus 模式下注入

### 客户端处理职责

- `pythonStreamPayloadToAgentEvents()`（`client/desktop/src/agent/pythonBridge.ts`）把 7 种 `*Event` 字段转成 `AgentEvent` 联合类型，由 `onAgentEvent` 回调消费
- `tool_event` / `token` / `ready` / `done` / `error` 不经 agent 化，直接由 `streamLocalChat`（`adapters/localArcher.ts`）回调处理
- `vault_sources` / `heartbeat` 当前被前端忽略
- `chatEventDispatcher.ts`（L2.2）负责把 `AgentEvent` 映射到 UI action，覆盖 `failure.hint` + 派生失败（`tool_failed` / `approval_rejected` / `job_stale_cancelled` / `approval_duplicated`）

### 派生失败类型（非 failure.hint keyword，由 dispatcher 从其他事件推导）

| 派生类型 | 来源事件 | 推导条件 |
|---|---|---|
| `tool_failed` | `tool.result` | `status === 'complete' && !ok`，或 `status === 'blocked'` |
| `approval_rejected` | `approval.result` | `decision === 'denied'` |
| `job_stale_cancelled` | `job.event` | `status === 'cancelled' && stale === true` |
| `approval_duplicated` | `tool.request` | 同 `requestId` 重复出现 ≥ 2 次（dispatcher 维护已见 requestId 集合） |

---

## failureHintEvent（失败提示事件）

聊天流（SSE / WebSocket）在失败或异常结束时，通过 `failureHintEvent` 事件向客户端传达结构化失败原因。客户端依据 `keyword` 决定展示文案与恢复建议，不再只显示"模型无回复"。

### 事件结构

```json
{
  "type": "failureHintEvent",
  "failureHintEvent": {
    "id": "failure-hint-<8hex>",
    "traceId": "trace-<12hex>",
    "keyword": "<keyword>",
    "stage": "<stage>",
    "recoverable": true,
    "detail": "<最多 300 字符的错误细节>"
  }
}
```

### keyword 完整枚举

| keyword | 含义 | recoverable | 触发场景 |
|---|---|---|---|
| `provider_connection_failed` | LLM provider 连接/鉴权/限流失败 | true | `_connection_hint` / `_status_hint` 抛出的 RuntimeError，stage 为 `model_stream` / `llm` / `call_with_tools` |
| `command_timeout` | 命令执行超时或连接失败 | true | `timeout` / `connect` 关键词，非 LLM stage |
| `write_permission` | 文件/目录写入权限被拒绝 | false | `permission` / `denied` 关键词 |
| `dependency_missing` | 依赖文件/命令/库未找到 | true | `not found` / `no such file` / `missing` 关键词 |
| `syntax_mismatch` | 语法/解析错误（JSON、配置等） | true | `syntax` / `parse` / `json` 关键词 |
| `runtime_failure` | 运行时异常（兜底） | true | 未匹配上述任何关键词 |
| `model_empty_response` | 模型请求成功但无文本返回 | true | 主 stream 完成但 `ai_reply.strip()` 为空（B1.1） |
| `tool_executed_no_summary` | 工具已执行但模型无总结 | true | 主 stream 为空且本轮有工具事件（B1.1） |

### stage 常见值

| stage | 来源 |
|---|---|
| `model_stream` | 主模型流式响应失败 |
| `llm` / `call_with_tools` | LLM 调用失败 |
| `shell_execute` | Shell 命令执行失败 |
| `hugo_workflow` | Hugo 博客部署工作流失败 |
| `initiative_shadow.<operation>` | Part 8 shadow initiative 操作失败 |

### 客户端处理约定

- 客户端应依据 `keyword` 显示简短中文文案，保留 `traceId` 供诊断追踪
- `recoverable=true` 时提示"可重试"，`recoverable=false` 时提示"需检查配置/权限"
- `provider_connection_failed` 连续 3 次后端会触发 B6.1 熔断，自动切回 default profile（lite）

---

## 其他 GET 端点

| 路径 | 说明 |
|------|------|
| `/sessions` | 最近会话摘要列表 |
| `/sessions/{id}` | 会话消息 + tokenUsage |
| `/skills` | 技能列表（name, description, risk, enabled） |
| `/modes` | 对话姿态（current, modes[]） |
| `/experts` | 专家工作台（current, experts[]） |
| `/settings` | Desktop 可编辑配置快照 |
| `/schedules` | 定时任务列表 + jsonPath |
| `/soul-files` | SOUL / MEMORY 等文件内容 |
| `/soul-profile` | 结构化灵魂画像摘要 |
| `/hypotheses` | Soul Insight hypotheses 列表 |
| `/proactive-touch` |  proactive 扫描项 |
| `/reviews?period=weekly` | 周期回顾 |
| `/journal-review?days=30` | 日记回顾 |
| `/sensors/status` | 当前传感器状态；包含 Obsidian focus |
| `/vault/current-focus` | 当前 Obsidian focus；可带 `?detect=1` 使用 mtime fallback |

---

## 其他 POST 端点

| 路径 | 说明 |
|------|------|
| `/sessions` | 保存新会话 `{ messages, expertId?, expertLabel? }` |
| `/sessions/{id}/append` | 追加消息 |
| `/modes/current` | `{ "mode": "coach" \| "auto" \| … }` |
| `/experts/current` | `{ "expert": "developer" \| "default" \| … }`；校验 id，写入 `current_expert`（不自动切换模型档位） |
| `/settings/validate` | 校验 draft，不写盘 |
| `/settings/save` | 写入 archer.toml 允许字段 |
| `/skills/toggle` | `{ "name", "enabled" }` |
| `/soul/import` | `{ "soulData": { … } }` |
| `/hypotheses` | 手动创建 hypothesis `{ title, statement, confidence?, validateAfterDays?, sessionId? }` |
| `/hypotheses/import-obsidian` | 从配置的 Obsidian vault 导入显式 `假设：` / `Hypothesis:` 日记标记 |
| `/sensors/obsidian/focus` | Obsidian 插件上报当前笔记 focus；要求 Bearer token，路径必须位于 `[obsidian].vault_path` |
| `/tool-approvals` | `{ "eventId", "decision": "approved"\|"denied" }` |
| `/schedules` | 添加 `{ skillName, interval, label?, catchup? }` |
| `/schedules/{id}/remove` | 删除 |
| `/schedules/{id}/enable` | 启用 |
| `/schedules/{id}/disable` | 禁用 |
| `/schedules/{id}/run` | 立即执行 |

---

### `POST /sensors/obsidian/focus`

Obsidian 传感器入口，用于把当前打开的笔记作为只读上下文同步给 Desktop 聊天流。

```json
{
  "file_path": "/abs/path/to/vault/note.md",
  "relativePath": "folder/note.md",
  "title": "note",
  "selected_text": "optional selected text",
  "visible_headings": ["Heading"],
  "tags": ["writing"],
  "content_preview": "short excerpt"
}
```

响应成功后，`/chat/stream` 在 `obsidianMode != "off"` 时会注入该 focus，并发出 `vault.context` / `vault_sources` 事件。

---

### `GET /settings` 模型档位字段

`/settings` 返回的模型配置包含三档：

```json
{
  "activeProfile": "lite",
  "activeExpert": "default",
  "experts": [
    { "id": "default", "label": "基础 Archer", "note": "灵魂陪伴，不担任特定工作角色", "modelProfile": "lite", "skillCount": 0, "configured": true },
    { "id": "developer", "label": "开发工程师", "note": "查代码、排错、看结构、委派实现", "modelProfile": "pro", "skillCount": 6, "configured": false }
  ],
  "modelProfiles": [
    { "id": "lite", "label": "Lite", "provider": "DeepSeek", "baseUrl": "https://api.deepseek.com/v1", "model": "deepseek-chat", "configured": true },
    { "id": "pro", "label": "Pro", "provider": "Kimi", "baseUrl": "", "model": "", "configured": false },
    { "id": "max", "label": "Max", "provider": "GLM", "baseUrl": "", "model": "", "configured": false }
  ]
}
```

`activeProfile` 只允许 `lite` / `pro` / `max`。`pro` 和 `max` 先作为预留档位，等 API key 与模型名确定后再补全。

---

### `GET /experts`

**响应 200**

```json
{
  "current": "default",
  "experts": [
    {
      "id": "default",
      "label": "基础 Archer",
      "note": "灵魂陪伴，不担任特定工作角色",
      "modelProfile": "lite",
      "skillCount": 0,
      "configured": true,
      "starters": [
        { "label": "先听我说", "prompt": "我先说一段，你不用急着给方案。" }
      ]
    }
  ]
}
```

`skillCount` 为 allowlist 大小；`default` 为 0 表示不限制技能池。`configured` 表示该专家可用。`starters` 为首页快捷开场（每专家 4 条）。`custom` / `source` 标识自定义或插件专家。

`GET /settings` 的 `experts[]` 与 `GET /experts` 使用同一 catalog 结构（含 starters）。

### `POST /experts/current`

**请求**

```json
{ "expert": "developer" }
```

**响应 200**

```json
{
  "ok": true,
  "current": "developer",
  "label": "开发工程师",
  "modelProfile": "pro",
  "previous": "default"
}
```

未知 id 或目标模型档位未配置时返回 **400** `{ "ok": false, "error": "…" }`。

---

## WebSocket

### `WS /ws/chat`

载荷同 `POST /chat/stream`；服务端逐帧发送与 SSE 相同的 JSON event（非 `data:` 前缀）。

---

## 实现索引

| 模块 | 职责 |
|------|------|
| `terminal/api/fastapi_app.py` | HTTP/WS 入口、认证中间件 |
| `terminal/api/_routes.py` | 路由分发与领域逻辑 |
| `terminal/api/_tools.py` | 流式 chat、工具 event、意图/编排 |
| `terminal/api/_security.py` | 限流、恒定时间比较 |
| `terminal/api/_config.py` | 配置路径、消息清洗 |

OpenAPI：FastAPI 运行时访问 `/docs`、`/redoc`。

---

## L3 领域 store 契约（L3.1）

5 个领域 store + threadStore（L3.8 后续补）。所有 store 采用**外部 store + useSyncExternalStore** 模式（与 `runtimeStore.ts` 一致），单例对象 + selector hook。

### 通用 store 接口

每个 store 实现：

```ts
type ExternalStore<T> = {
  getState(): T
  subscribe(listener: () => void): () => void
  setState(producer: (draft: T) => T): void  // 不可变更新
}

function useXxxStore<U>(selector: (state: T) => U): U {
  return useSyncExternalStore(store.subscribe, () => selector(store.getState()))
}
```

规则：
1. 页面不直接 fetch，只 dispatch action 或读取 store
2. store 是单一真值，页面只读订阅
3. action 成功后由 store 自己 refresh 真值，页面不手动 invalidate
4. 跨 store 联动（L3.7）：Soul 导入/结晶后只强制刷新 Memory 领域；记忆动作完成后订阅者直接读取 store。

### memoryStore（L3.2）

**真值来源**：`/memory` + `/memory/stats` + `/memory/groups` + 审阅动作

**State shape**：
```ts
type MemoryStoreState = {
  items: MemoryItem[]           // /memory?include_rejected=true
  stats: MemoryStats | null     // /memory/stats
  groups: MemoryGroup[]         // /memory/groups
  loadState: 'idle' | 'loading' | 'ready' | 'error'
  error: string
  // 审阅动作进行中的 id 集合
  busyIds: Set<number>
}
```

**Actions**：
| Action | 调用 API | 副作用 |
|--------|---------|--------|
| `loadAllMemory({ force? })` | GET /memory + /memory/stats + /memory/groups（并发） | 三项全部成功后一次发布；普通并发加载合并，强制刷新使旧响应失效 |
| `resolvePendingMemoryAction(id, accepted)` | POST /memory/pending/{id}/{accept\|reject} | 成功后强制刷新三项；接受的记忆仍保留在服务端权威列表 |
| `batchResolvePendingMemoryAction(accepted)` | POST /memory/pending/batch/{accept\|reject} | 成功后强制刷新三项 |
| `updateMemoryAction(id, content)` | POST /memory/update | 成功后强制刷新三项，分类文本同步更新 |
| `evolveMemoryAction(id, content, ...)` | POST /memory/evolve | 成功后强制刷新三项 |

**失败边界**：读取失败保留最近完整快照，发布 error；旧请求成功/失败均不能覆盖新状态。POST 成功与后续刷新失败分别呈现，避免误报写入失败；单条动作结束后清除 busy id。重置使在途读取失效。

**订阅者**：MemoryPage、ReviewPage、导航计数、ProfilePanel、SettingsPage。MemoryPage 只接收连接状态，启动/重连由 main 加载；页面刷新不触发整体 adapter。

**领域边界**：`memoryAdapter` 复用共享 HTTP/token/契约处理；ArcherAdapter 不再含 memory，loadLocalArcher 不读取记忆列表，storeSync 不注入或回投影 Memory。REST `/status` 的计数字段保留兼容，界面记忆计数使用 store。单条确认从原来的 POST + stats GET 变为 POST + 三个 GET，编辑从 POST 变为 POST + 三个 GET；无新增模型调用。

### soulStore（L3.3）

**真值来源**：`/soul-profile` + `/soul-files` + `/vault/reflection/recent` + 导入动作

**State shape**：
```ts
type SoulStoreState = {
  profile: SoulProfileSummary | null   // /soul-profile
  files: SoulFiles                      // /soul-files
  reflections: VaultReflection[]        // /vault/reflection/recent?limit=10
  loadState: 'idle' | 'loading' | 'ready' | 'error'
  error: string
  importing: boolean
  importMessage: string
}
```

**Actions**：
| Action | 调用 API | 副作用 |
|--------|---------|--------|
| `loadAllSoul(options?)` | GET /soul-profile + /soul-files + /vault/reflection/recent?limit=10 | 原子替换；并发普通加载复用请求，force 加载淘汰旧响应 |
| `importSoulAction(soulData)` | POST /soul/import | 成功后 force 刷新 Soul 域，发出 memory 侧作用事件 |
| `triggerReflectionAction(payload)` | POST /vault/reflection | 成功后 force 刷新 Soul 域，发出 memory 侧作用事件；ok=false 不发成功事件 |
| `exportPortableDataAction()` | POST /exports/portable | 沿用 JSON + Markdown 导出格式 |

**订阅者**：SoulPage、ReviewPage、VaultReflectionsPanel

2026-10-02，1.0.30：HTTP 操作集中于 `adapters/soulAdapter.ts`，复用既有认证、超时和 REST 解包。`ArcherAdapter` / `loadLocalArcher` / `storeSync` 已删除 Soul profile/files 字段与双向投影；连接/重连成功后独立加载 Soul，页面不从旧快照回退。失败保留上次完整数据并标记 error，初次失败不冒充空档案；reset 和较新的 force 加载使旧成功/错误响应失效。

SoulPage 的 hypotheses、journalReview、periodReviews 仍是其他领域传入的显式 props，本次未迁移这些领域。import POST 成功但后续读取失败时，保留成功导入回执并单独显示读取错误；memory 事件仍有效，不提示重新执行已成功的写入。

### sessionStore（L3.4）

2026-10-03，1.0.32：`conversationAdapter.ts` 集中会话/线程 HTTP 操作，复用原认证、超时与 REST 格式。GET 保持既有解包，POST 保留原平铺回执。整体 `ArcherAdapter`、mock/offline、loadLocalArcher、storeSync 不再承载 sessions/threads。

**真值来源**：`/sessions`、`/sessions/{id}`、`/sessions/search` 和保存/续写/删除回执。

- `loadSessionList({ force? })` 实际读取服务端；普通并发合并，force/reset 淘汰旧成功与失败响应，失败保留最近列表。列表、详情、搜索分别持有错误信息。
- `loadSessionDetail(id)` 与 `searchSessions(query)` 只接纳最新请求；删除后淘汰先前详情/搜索响应，避免恢复已删除内容。
- `saveSessionMessages(messages, meta)` / `appendSessionMessages(id, messages)` 写入后定向刷新 session 和 thread 列表。POST 成功与刷新失败分开，刷新失败不提示重发已成功保存的消息。
- `deleteSession(id)` 尊重服务端 ok，成功后移除已删列表/详情/搜索内容并刷新两域；拒绝不自行删除。用户入口保持删除确认。
- `mergeSessionItems` 仅用于提交已经读取的服务端列表和合成测试，不再是旧 adapter 注入入口。
- 侧栏、ProjectsPage、ReviewPage 直接订阅 sessionStore；ChatPage 保存走 store action。活动聊天消息仍保留组件内状态，不把临时消息推为线程权威摘要。

Review 的“在新会话继续这个话题”沿用现有 POST `/sessions` 的 `threadId` 元数据。选择时不写会话，首次实际发送后生成同线程的新 session；普通“恢复”仍续写原 session。没有复制旧对话、合成用户决定或自动标记 J8 样本通过。

### jobStore（L3.5）

**真值来源**：`/jobs` + `/jobs/{id}` + cancel/retry/approve/spawn 动作

**State shape**：
```ts
type JobStoreState = {
  jobs: BackgroundJob[]                       // /jobs（列表）
  currentDetail: BackgroundJob | null         // /jobs/{id}（选中详情，含 children）
  loadState: 'idle' | 'loading' | 'ready' | 'error'
  detailState: 'idle' | 'loading' | 'ready' | 'error'
  error: string
  busyIds: Set<string>                        // 动作进行中（cancel/retry/spawn）
}
```

**Actions**：
| Action | 调用 API | 副作用 |
|--------|---------|--------|
| `loadList()` | GET /jobs | 替换 jobs |
| `loadDetail(id)` | GET /jobs/{id} | 替换 currentDetail |
| `create(payload)` | POST /jobs | 返回 BackgroundJob + refresh jobs |
| `cancel(id)` | POST /jobs/{id}/cancel | 替换对应 job |
| `retry(id)` | POST /jobs/{id}/retry | 替换对应 job + 600ms 后 refresh |
| `approve(id, eventId, decision)` | POST /jobs/{id}/approve | 替换对应 job |
| `spawn(id, children)` | POST /jobs/{id}/spawn | 替换对应 job |
| `mergeFromRuntime(jobEvents)` | （由 runtimeStore SSE 注入） | 合并 JobEvent → BackgroundJob |

**订阅者**：TasksPage、ChatPage 回执、Workspace

**注意**：runtimeStore 的 `state.jobs` 是 `JobEvent`（SSE 事件），jobStore 的 `state.jobs` 是 `BackgroundJob`（API 拉取）。两者并存，jobStore 是页面消费的真值；runtimeStore 的 JobEvent 用于 trace log。

### initiativeStore（L3.6，受控 Part 8 投影）

**真值来源**：`/initiative-shadow` + report/long-term-report/delivery-gate/review-packet/exposure-report 子端点 + SSE 增量

**State shape**：
```ts
type InitiativeStoreState = {
  review: InitiativeShadowReview | null   // 合并 5 端点
  loadState: 'idle' | 'loading' | 'ready' | 'error'
  error: string
}
```

**Actions**（只读 + mutation，不暴露写 shadow 的 action）：
| Action | 调用 API | 副作用 |
|--------|---------|--------|
| `loadAll()` | GET /initiative-shadow?limit=5 + 5 子端点（并发） | 替换 review |
| `claimReviewCandidate()` | POST /initiative-shadow/review-candidate `{surface:"chat_workspace"}` | 原子认领当天唯一 Workspace shadow 候选；不投递 |
| `submitFeedback(id, feedback, surface?)` | POST /initiative-shadow/{id}/feedback | refresh review.items；可选记录界面来源 |
| `setPresence(state, surface?)` | POST /initiative-shadow/presence | refresh review.presenceState；记录 mute/unmute 计数 |
| `exposureReport` | GET /initiative-shadow/exposure-report?surface=chat_workspace&days=14 | 曝光、反馈转化、认可、太频繁、静音的脱敏聚合 |
| `setDeliveryOptIn(enabled)` | POST /initiative-shadow/opt-in | refresh review.optIn + deliveryGate；关闭时取消未发送的 `initiative.thread_resume` Outbox 项 |
| `transitionThreadClueAction(id, status)` | POST /initiative-threads/{id}/status | 仅 Part 8 数字线索 ID；status 为 resolved/closed/dismissed/expired；归档关联候选、取消待发送 Outbox，清除当前候选投影；不关闭普通会话或记录认可 |
| 显式过期维护 | POST /initiative-threads/expire `{maxIdleDays:30}` | 1–365 整数天，依据 last_seen_at；返回 expiredIds。不会在启动或扫描时自动批量过期用户线索 |

线索状态响应为 `{ok,id,status,closedAt,changed}`，重复同终态返回 changed=false；无效状态/ID 为 400、缺失线索为 404、终态冲突为 409。沿用认证及 contractVersion 封装，无 schema 迁移。线索与 conversation thread/capsule 使用独立命名空间；候选 lifecycle trace 记录前后状态和时间，来源证据与历史投递保留。归档后的候选不再进入新认领、重试或聊天展示；发送过程的更新也拒绝已归档候选。
| `mergeSseEvent(event)` | （无 API，由 SSE initiative.event 注入） | 合并到 review.items |

**订阅者**：TodayPage、ReviewPage、main.tsx（SSE 合并）

**Part 8 边界**：唯一 live slice 是 `thread_resume`。只有观察门槛、人工复核就绪和显式 opt-in 同时通过，且 presence 为 idle、当日尚未投递时，后端才通过 `initiative.thread_resume` Durable Outbox 标记为 Archer 应用内已投递。它不写入聊天，不触发系统通知或外部渠道；其他 Part 8 模块继续冻结。

Workspace 的 shadow review card 与 live slice 分离：schema v4 的 `initiative_shadow_interactions` 只保存候选 ID、surface、事件、日期和时间，不保存聊天正文。`surface + exposure_date` 的唯一约束保证每日最多一条；曝光始终保持 `delivered=false`，反馈后当天不轮播下一条。

### 跨 store 联动（L3.7，事件总线）

store 间通过 `lib/storeEventBus.ts` 解耦：store action 成功后 `emitStoreEvent`，订阅方（main.tsx 或其他 store）决定是否 refresh。store 间不直接调用，main.tsx 作为协调者监听事件后触发 `loadLocalArcher` refresh。

**事件类型清单**：

| 事件 type | 来源 action | payload | 订阅方动作 |
|---|---|---|---|
| `memory:resolved` | `memoryStore.resolvePendingMemoryAction` | `{ id, accepted }` | 页面直接订阅 memoryStore，无整体 refresh |
| `memory:batch-resolved` | `memoryStore.batchResolvePendingMemoryAction` | `{ accepted, count? }` | 页面直接订阅 memoryStore |
| `memory:evolved` | `memoryStore.evolveMemoryAction` | `{ id }` | 页面直接订阅 memoryStore |
| `soul:imported` | `soulStore.importSoulAction` | `{ imported }` | main.tsx 定向加载 memoryStore ，计数由 store 订阅，不重载整体 adapter |
| `soul:reflection-triggered` | `soulStore.triggerReflectionAction` | `{}` | main.tsx 定向加载 memoryStore ，计数由 store 订阅，不重载整体 adapter |
| `job:created` | `jobStore.createJob` | `{ jobId }` | main.tsx refresh（job 可能产生新会话） |
| `job:cancelled` | `jobStore.cancelJob` | `{ jobId }` | — |
| `job:retried` | `jobStore.retryJob` | `{ jobId }` | — |
| `job:approved` | `jobStore.approveJob` | `{ jobId, decision }` | — |
| `job:spawned` | `jobStore.spawnChildren` | `{ parentJobId, childCount }` | — |

**设计原则**：
1. store 间不直接调用（低耦合）
2. main.tsx 作为协调者，监听事件后触发 `loadLocalArcher` refresh
3. store 的 action 不需要知道谁在监听
4. 异常隔离：单个监听者抛错不影响其他监听者（`emitStoreEvent` 内部 try/catch + console.warn）

### threadStore（L3.8，ConversationThread 连续性契约）

**真值来源**：`conversationAdapter` 读取 `/threads` 和线程动作的服务端回执；失败保留最近列表，普通并发合并，force/reset 淘汰旧读取。

**State shape**：
```ts
type ThreadStoreState = {
  items: ConversationThread[]
  currentThreadId: string | null
  loadState: 'idle' | 'loading' | 'ready' | 'error'
  error: string
}
```

**Actions**：
| Action | 调用 API | 副作用 |
|--------|---------|--------|
| `loadThreadList({ force? })` | GET /threads | 读取服务端列表，失败保留内容 |
| `mergeThreadItems(items)` | （提交已确认的服务端列表） | 替换 items + 保留 currentThreadId（若仍存在）+ 标记 ready |
| `setCurrentThread(id\|null)` | （无） | 设置/清空当前活跃 thread |
| `createThread(messages, title?)` | POST /threads | upsert items + 设为 current |
| `updateThread(id, patch)` | POST /threads/{id} | upsert items（持久化 summary/title/projectId/archived） |
| `linkSessionToThread(threadId, sessionId)` | POST /threads/{id}/sessions | upsert items（thread.sessionIds 追加） |
| `getCurrentThread()` | （selector） | 返回当前活跃 thread 或 null |

**连续性契约**（Archer 稳定性框架.md §ConversationThread 连续性契约）：
1. 首页第一次发送成功后，后端创建 thread，前端立即把它设为当前 active thread
2. 用户不点"新建对话"时，连续追问都 append 到同一 session/thread
3. 侧边栏任务列表渲染 thread，而不是平铺 session
4. 项目归属优先按 `threadIds`，旧 `sessionIds` 只做兼容
5. 发消息前注入当前 thread summary；该 summary 不写入 session 正文，避免污染历史记录
6. 旧 session 无 threadId 时允许 fallback 聚合，但不能把 fallback 当成正式迁移

**与 main.tsx 的关系**（2026-10-03）：
- main、ProjectsPage、ChatPage 直接订阅 threadStore；删除旧整体快照和 `upsertSavedSessionSnapshot` / `upsertThreadFromSave` 回投影。
- 新会话的线程创建或关联由现有服务端 POST 完成，随后读取 `/threads`。不再把助手最后一条回复拼成“最近结论”，保留服务端的 capsule/version/停点。
- Session/Thread 是两个独立投影，各自呈现读取状态；一域读取失败时显示错误，不宣称跨两个端点的事务快照。
