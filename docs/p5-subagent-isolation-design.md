# P5.4 Subagents 上下文隔离 — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 问题

- Desktop 子任务（`parentJobId`）与 Work subtask 共享主对话的 memory 检索与全量技能
- 子任务结果可能反向污染主会话上下文
- 副作用工具在后台子任务中无审批链路

## 目标

子任务在**独立精简 context** 中运行：最小 persona + 只读工具集 + 并发上限。

## 隔离策略

| 维度 | 主对话 | 子任务 |
|------|--------|--------|
| System prompt | 完整 Soul/Memory/编排 | `build_subagent_system_prompt()` 精简版 |
| Memory 检索 | 可注入 | **跳过** |
| 工具集 | skill_router 全量 | `SUBTASK_ALLOW_LIST` |
| 副作用工具 | 审批流 | **默认 DENY**（`SUBTASK_DENY_LIST`） |
| 并发 | — | 最多 3 个 active 子 job |

## 默认允许工具

`web_search`, `web_fetch`, `file_ops`(read/list), `file_search`, `obsidian_read`, `obsidian_search`, `code_search`, `pdf_reader`, `rss_reader`, `weather`

## 集成点

- `core/subagent_context.py` — prompt + skill filter
- `core/policy.py` — `SUBTASK_DENY_LIST`, `check_subtask()`
- `core/subtask_runner.py` — 精简 prompt + allow list + `subtask_mode` policy
- `terminal/api/_routes.py` — 子 job 隔离执行 + 并发控制
- Desktop TasksPage — 子任务独立状态卡片

## 验收

- [x] `tests/test_subagent_isolation.py`
- [x] spawn/job 回归绿
