# P5.9 结构化日志与可观测性 — 设计文档

日期：2026-06-13  
状态：阶段三（聊天主链性能终态已产品化）

## 问题

当前 `print()` + 标准 `logging` 难以回答：一次对话各阶段耗时、LLM token 用量、工具成功率、记忆检索命中数。

## 方案

| 层 | 选型 | 作用 |
|----|------|------|
| 结构化日志 | `structlog` | 稳定 event 名 + JSON 字段，便于 grep/聚合 |
| Trace span | 轻量 `trace_span()` | 嵌套计时 + 属性，不引入完整 OpenTelemetry SDK |
| Metrics | span 属性 + 现有 `_last_usage` | P5.10 再产品化 `/status` 展示 |
| Turn performance | 持久化 `runtime.context phase=performance` | 每轮 TTFT、总耗时、上下文、工具、CPU 与进程 RSS 峰值 |

## 关键 span

| Span 名 | 位置 | 记录字段 |
|---------|------|----------|
| `llm.stream_chat` | `core/llm.py` | model, prompt_tokens, completion_tokens, duration_ms |
| `llm.call_with_tools` | `core/llm.py` | model, total_tokens, duration_ms |
| `tool.invoke` | `core/tool_loop.py` | tool_name, ok, duration_ms |
| `memory.retrieve` | `memory/retrieve.py` | intent, core_count, related_count, duration_ms |
| `context.build_system_prompt` | `core/context.py` | heavy, intent, prompt_chars, duration_ms |

## 关联 ID

聊天入口生成 trace id 后立即 `bind_trace_context(trace_id=...)`，后续 context/LLM/tool span 共享关联 ID；结束或客户端关闭时清理 contextvar。

## 聊天主链指标契约

- Python SSE 在 `done` 前发送 `performanceEvent`；Desktop bridge 将其规范化为现有 `runtime.context` 并写入事件日志，不增加新的 AgentEvent 类型。
- 固定数值字段：`ttftMs`、`totalDurationMs`、`contextBuildMs`、`toolDurationMs`、`cpuTimeMs`、`peakRssBytes`；固定状态字段仅为 `complete/failed`。
- 指标不携带用户文本、文件路径、URL、错误详情或凭据。`scripts/collect_metrics.py` 输出 min/p50/p95/max，并以 performance terminal 作为成功 Trace 的闭环证据。
- RSS 使用当前 Python 进程的 OS 级峰值，含义是“进程生命周期峰值”，不是单轮独占内存；先积累基线，再设置告警阈值，避免凭空制造噪声。

## 测试

`tests/test_observability.py`、`tests/test_turn_metrics.py`、`tests/test_metrics_collector.py`：span、终态事件、隐私边界、事件顺序、分位数与闭环统计。
