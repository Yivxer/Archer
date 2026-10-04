# ADR 0008: 服务端领域状态与客户端投影

Date: 2026-10-04
Status: accepted（当前领域规则；Runtime 全面切权另行验收）

## Context

桌面端的旧快照、未保存表单与服务端确认状态混用，会造成刷新覆盖草稿或把旧值当作新确认值。相同问题也会出现在任务状态、工具结果和记忆展示中。

## Decision

1. 持久化事实由相应 Python 领域接口与存储负责。客户端 adapter 调用 HTTP；客户端 store 保存领域投影、加载状态和错误，不能成为另一份后端执行事实库。
2. Settings 的服务端确认值归 `settingsStore`，当前页的未保存草稿归 `settingsSession`。后台刷新不覆盖 dirty 草稿；读取失败保留上次确认值；迟到响应必须经过 epoch / token 检查。
3. 保存成功后回读服务端确认值。写入成功但回读失败时保留写入成功这一事实，同时标明同步失败，并在读取恢复前阻止下一次写入。
4. Memory、Profile、会话、Job 等领域分别遵守自身 authority 测试与迁移记录。Runtime 客户端只展示 API 投影；工具执行器不直接宣告 Runtime 完成，相关桥接负责核验和生命周期收口。

## Consequences / Limits

- 客户端可以保留草稿、加载状态与展示缓存；这些值不替代持久化事实。
- “服务端权威”是领域规则，不意味着所有旧链路已完成 Runtime authority cutover。shadow、对照和迁移开关继续独立验收。
- 本批没有切换生产 authority，也没有修改桌面源码或安装包。

## Evidence

- Settings：[`领域验收记录`](../desktop-settings-domain-2026-10-04.md)、[`settingsStore.ts`](../../client/desktop/src/renderer/src/lib/settingsStore.ts)、[`settingsSession.ts`](../../client/desktop/src/renderer/src/lib/settingsSession.ts)。
- Runtime：[`obsidian_runtime_bridge.py`](../../terminal/api/obsidian_runtime_bridge.py)、[`authority_migration.py`](../../core/authority_migration.py)。
- 回归：[`test_architecture_boundaries.py`](../../tests/test_architecture_boundaries.py)、[`test_memory_store_authority.py`](../../tests/test_memory_store_authority.py)、[`test_profile_authority.py`](../../tests/test_profile_authority.py)、[`test_authority_migration.py`](../../tests/test_authority_migration.py)。
