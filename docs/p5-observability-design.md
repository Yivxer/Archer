# P5.9 结构化日志与可观测性 — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 问题

当前 `print()` + 标准 `logging` 难以回答：一次对话各阶段耗时、LLM token 用量、工具成功率、记忆检索命中数。

## 方案

| 层 | 选型 | 作用 |
|----|------|------|
| 结构化日志 | `structlog` | 稳定 event 名 + JSON 字段，便于 grep/聚合 |
| Trace span | 轻量 `trace_span()` | 嵌套计时 + 属性，不引入完整 OpenTelemetry SDK |
| Metrics | span 属性 + 现有 `_last_usage` | P5.10 再产品化 `/status` 展示 |

## 关键 span

| Span 名 | 位置 | 记录字段 |
|---------|------|----------|
| `llm.stream_chat` | `core/llm.py` | model, prompt_tokens, completion_tokens, duration_ms |
| `llm.call_with_tools` | `core/llm.py` | model, total_tokens, duration_ms |
| `tool.invoke` | `core/tool_loop.py` | tool_name, ok, duration_ms |
| `memory.retrieve` | `memory/retrieve.py` | intent, core_count, related_count, duration_ms |
| `context.build_system_prompt` | `core/context.py` | heavy, intent, prompt_chars, duration_ms |

## 关联 ID

`bind_trace_context(trace_id=...)` 绑定到 structlog contextvars；Desktop session id 可在 orchestrator 层后续传入。

## 测试

`tests/test_observability.py`：span 创建、嵌套、属性合并、recorder 隔离。
