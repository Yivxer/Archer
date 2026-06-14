# P5.2 Memory Compaction — 设计文档

日期：2026-06-13  
状态：阶段二（实现完成）

## 问题

- 长期记忆只增不减，`active` 记忆持续膨胀
- `freshness_check()` 仅标记 stale，不会合并或归档冗余条目
- 无「整理后摘要」，旧细节丢失后无法追溯

## 目标

在阈值触发时**主动归档**低价值 active 记忆，并写入一条 compaction 摘要记忆。

## 非目标

- 不删除记忆（仅 `status=archived` 软归档）
- 不自动接受 pending
- 不替换 `core/compressor.py`（对话历史压缩，职责不同）

## 触发条件（任一满足）

| 条件 | 默认阈值 |
|------|----------|
| active 记忆数 | ≥ 200 |
| pending 待确认数 | ≥ 30 |

可通过环境变量覆盖：`ARCHER_MEMORY_COMPACT_ACTIVE`、`ARCHER_MEMORY_COMPACT_PENDING`。

## 流程

```
maybe_compact_memories()
  → should_compact()?
  → list_compaction_candidates()
  → heuristic 打分（保护 identity/preference/decision/高 depth）
  → archive() 低分批次（默认最多 15 条）
  → LLM 生成摘要（失败则模板 fallback）
  → save() 写入 source=compaction 的 insight 摘要
  → 返回 CompactionResult → SSE tool event「已整理记忆」
```

## 集成点

- `terminal/api/_tools.py`：每轮 chat 流结束前调用（与 extract 并行职责分离）
- `core/orchestrator.py`：`maybe_run_memory_compaction_after_turn()` 薄封装
- Desktop ChatPage：`memory.compact` tool event 显示「已整理记忆」

## 验收

- [x] `tests/test_memory_compaction.py` 通过
- [x] 记忆/编排回归绿
- [x] ChatPage 可见整理提示（`memory.compact` tool event）
