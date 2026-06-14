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
| 公开路径 | `GET /health`（无需 token） |

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

---

### `GET /status`

**响应 200**

```json
{
  "adapter": "local",
  "model": "deepseek-chat",
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

## 其他 GET 端点

| 路径 | 说明 |
|------|------|
| `/sessions` | 最近会话摘要列表 |
| `/sessions/{id}` | 会话消息 + tokenUsage |
| `/skills` | 技能列表（name, description, risk, enabled） |
| `/modes` | 对话姿态（current, modes[]） |
| `/settings` | Desktop 可编辑配置快照 |
| `/schedules` | 定时任务列表 + jsonPath |
| `/soul-files` | SOUL / MEMORY 等文件内容 |
| `/soul-profile` | 结构化灵魂画像摘要 |
| `/proactive-touch` |  proactive 扫描项 |
| `/reviews?period=weekly` | 周期回顾 |
| `/journal-review?days=30` | 日记回顾 |

---

## 其他 POST 端点

| 路径 | 说明 |
|------|------|
| `/sessions` | 保存新会话 `{ messages }` |
| `/sessions/{id}/append` | 追加消息 |
| `/modes/current` | `{ "mode": "coach" \| "auto" \| … }` |
| `/settings/validate` | 校验 draft，不写盘 |
| `/settings/save` | 写入 archer.toml 允许字段 |
| `/skills/toggle` | `{ "name", "enabled" }` |
| `/soul/import` | `{ "soulData": { … } }` |
| `/tool-approvals` | `{ "eventId", "decision": "approved"\|"denied" }` |
| `/schedules` | 添加 `{ skillName, interval, label?, catchup? }` |
| `/schedules/{id}/remove` | 删除 |
| `/schedules/{id}/enable` | 启用 |
| `/schedules/{id}/disable` | 禁用 |
| `/schedules/{id}/run` | 立即执行 |

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
