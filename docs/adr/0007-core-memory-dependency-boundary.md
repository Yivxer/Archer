# ADR 0007: core / memory 依赖边界

Date: 2026-10-04
Status: accepted（回溯记录现有实现）

## Context

运行编排需要检索与保存记忆，记忆分析又需要模型能力。若 memory 直接导入 core 的具体模型和编排实现，会产生反向耦合，难以用合成数据验证。

## Decision

1. `core` 负责上下文组合、风险判断与执行编排；`memory` 负责记忆领域的数据、检索、schema 和分析逻辑。core 可以调用 memory 的领域接口。
2. memory 的模型能力通过 `memory.llm_port` 注入。服务组合入口配置该 port；memory 不导入 `core.llm` 等具体实现。
3. `core.paths` 是现有兼容例外，允许 memory 使用它解析数据库路径。`test_memory_core_imports_cannot_grow_beyond_documented_legacy_debt` 守门：除这个例外外，memory 对 core 的导入必须为空。
4. 新执行路径优先显式传递 `RuntimeContext` 的数据库与依赖。旧签名与 facade 可渐进迁移，不能通过修改全局默认路径隔离新的运行任务。

## Consequences / Limits

- 注入的模型 port 可由测试替身实现，避免真实模型依赖。
- `memory.llm_port` 当前使用进程级客户端；`memory.store.DB_PATH` 等旧默认值仍存在。这不等于已实现所有调用的多实例隔离。
- 本记录固定当前允许的依赖边界，不把所有历史模块一次性改为依赖注入。

## Evidence

- 源码：[`context.py`](../../core/context.py)、[`runtime_context.py`](../../core/runtime_context.py)、[`llm_port.py`](../../memory/llm_port.py)、[`store.py`](../../memory/store.py)、[`paths.py`](../../core/paths.py)。
- 守门：[`test_architecture_boundaries.py`](../../tests/test_architecture_boundaries.py)。
