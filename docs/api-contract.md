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
