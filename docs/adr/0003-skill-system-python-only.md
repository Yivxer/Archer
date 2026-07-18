# ADR 0003: Skill System 收口为 Python-only

Date: 2026-07-18
Status: accepted

## Context

早期 Archer Desktop 客户端尝试过用 TypeScript 写 skill bridge（`client/desktop/src/agent/skills/localSkillBridge.ts`），核心侧也有 `core/ts_skill_bridge.py` 做桥接。这带来三个问题：

- 同一个 skill 可能存在 Python 和 TS 两份实现，行为不一致。
- 桌面端 skill 加载逻辑与 Python skill 注册逻辑并行维护，重复且易漂移。
- 权限/审计/trace 这些必须在核心侧统一的能力，对 TS skill 来说是后补的，不是原生约束。

## Decision

Skill System **只保留 Python 实现**：

- 删除 `core/ts_skill_bridge.py` 与 `client/desktop/src/agent/skills/localSkillBridge.ts`。
- 桌面端 skill 加载统一走 Python `skills/loader.py` 暴露的接口（通过 FastAPI / IPC）。
- 所有 43 个 skill 都是 Python；不再接受新的 TS skill。
- 权限、审计、trace、幂等由核心侧的 `core/api_tool_service.py`、`core/permission_levels.py`、`core/tool_runtime.py` 统一执行，skill 自身不实现这些。

## Consequences

- Skill 行为只在 Python 一侧定义，桌面端只是调用方。
- 桌面端的 skill 测试（`pythonSkillAuthority.test.ts`）只验证调用路径，不验证 skill 语义。
- 新 skill 只需在 `skills/` 加一个 Python 文件并注册，无需改桌面端代码。
- 若未来要让 skill 在客户端进程内执行，需要重新决策并替换本 ADR。

## Non-goals

- 不在本次引入 skill 签名/版本化机制。
- 不限制 skill 内部是否能调用外部 TS 工具（通过 shell 等方式）。
