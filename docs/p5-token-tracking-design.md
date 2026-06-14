# P5.10 Token 用量追踪 — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 存储

| 层 | 方式 |
|----|------|
| 运行时 | `core/token_usage.py` 内存累计 + 最近一次 call 明细 |
| CLI State | `terminal/state.py` 只读暴露 `session_token_usage` |
| 会话文件 | `memory/sessions/*.json` 新格式 `{ "messages": [...], "tokenUsage": {...} }`；旧 list 格式仍可读 |

## `/status` 字段（Desktop API + CLI）

- `tokenUsage.sessionTotal` / `sessionPrompt` / `sessionCompletion`
- `tokenUsage.lastCallTotal` / `lastCallPrompt` / `lastCallCompletion`
- `tokenUsage.callCount` / `limit` / `percentUsed`

## 记录点

- `core/llm.py`：`stream_chat(track_usage=True)`、`call_with_tools()` 后 `record_call_usage()`
- 新 CLI 会话启动时 `reset_session_usage()`
- `Session.save()` / API `_save_session()` 写入 `tokenUsage`

## Desktop

- ChatPage composer 上方显示 `sessionTotal / limit`
- 每轮聊天后 `onRefresh()` 已会重拉 `/status`

## 验收

- [x] `tests/test_token_tracking.py`
