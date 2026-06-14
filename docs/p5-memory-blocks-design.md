# P5.1 Memory Blocks — 设计文档

日期：2026-06-13  
状态：阶段一（设计方案）

## 问题

当前 `memories` 表已有 `type`（13+ 种 A4 类型）和 `depth`（1–5），但：

- 缺少 **block 维度**：无法区分「用户档案块 / Agent persona 块 / 偏好块」等结构化槽位
- 检索以 FTS + importance 为主，`retrieve.for_context()` 不能按 block 精确筛选
- Desktop MemoryPage 只能按 type 粗筛，无法呈现 Letta 式 block 视图

## 目标

引入 `block_type` + 可选 `label`，让存储、检索、提炼、UI 都能按 block 工作，而不破坏现有 `type` / `depth` / pending 审阅链路。

## 非目标（本阶段不做）

- 向量检索 / embedding
- 自动 compaction（P5.2）
- 改写 Soul Profile 存储位置（仍用 `memory/soul_profile.py`，block 只做 memories 表）

## Schema 变更

在 `memory/store.py` 的 `memories` 表新增（ALTER 幂等）：

| 列 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `block_type` | TEXT | `'insight'` | 结构化 block 枚举 |
| `label` | TEXT | `''` | 块内标签，如 `writing_style`、`core_values` |

### block_type 枚举

| block_type | 含义 | 典型 label 示例 |
|------------|------|-----------------|
| `human` | 用户档案 / 事实 | `location`, `occupation` |
| `persona` | Agent 演进 / 自我描述 | `tone`, `boundaries` |
| `preference` | 偏好 | `writing_style`, `communication` |
| `decision` | 决策记录 | 项目名或日期 |
| `event` | 事件 | — |
| `insight` | 通用洞察（默认） | — |

### 与现有 `type` 的映射（写入时推断）

| 现有 type | 默认 block_type |
|-----------|-----------------|
| fact, identity | human |
| preference, creative_identity | preference |
| decision, project | decision |
| emotion_pattern, life_theme, reflection_anchor, … | insight（或 event） |
| project_mythology, self_narrative | human / insight |

`save()` / pending 接受时：若调用方未传 `block_type`，用上表推断；`label` 可选。

## API 变更

### `memory/store.py`

- `save(..., block_type=..., label=...)` 
- `search(..., block_type=..., label=...)`
- pending → active 时保留 block 字段

### `memory/retrieve.py`

- `for_context(..., block_types: list[str] | None = None)`
- `filter_by_block_type(block_type, limit=...)`

### `memory/extract.py`

- extract prompt 增加 block 输出字段；解析后写入 pending

### Desktop

- MemoryPage：block_type 筛选 Tab / 下拉（human / persona / preference / decision / event / insight）
- 卡片展示 `block_type` + `label` badge

## 兼容与迁移

1. 新列默认值 `block_type='insight'`，旧数据无需回填即可运行
2. 可选一次性脚本：按 `type` 批量 UPDATE `block_type`（非阻塞）
3. 所有现有测试保持绿；新增 `tests/test_memory_blocks.py`

## 验收标准（阶段二）

- [ ] 保存/检索/按 block_type 筛选单测通过
- [ ] extract 推断 block_type 单测通过
- [ ] MemoryPage 可按 block 筛选
- [ ] 现有 `test_memory_a4.py` 等回归全绿

## 推荐实现顺序（阶段二）

1. store schema + save/search 参数
2. retrieve `filter_by_block_type`
3. extract 推断 + pending 字段
4. MemoryPage UI
5. `tests/test_memory_blocks.py`

## 与 Part 3 / Part 4 关系

- **Part 3**：无依赖；TS skill 迁移已主体完成
- **Part 4**：orchestrator 的 `memory_scope` 可在后续迭代中映射到 block_type 过滤（P5.1 不阻塞 P4）
