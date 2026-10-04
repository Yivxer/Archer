# ADR 0010: Durable Outbox 的发送事实与重试边界

Date: 2026-10-04
Status: accepted（回溯记录现有实现）

## Context

审批后的外部动作可能在执行、回执写入或进程退出之间中断。仅有内存审批缓存，无法在重启后明确区分待执行、执行中与已完成。

## Decision

1. `infrastructure.outbox` 持有 SQLite `durable_outbox`，保存 payload、唯一幂等键、状态、尝试次数、重试时间、错误与结果。
2. 正常路径为 `pending → approved → sending → sent`。pending / approved / failed 可取消；sending 失败进入 failed，达到次数上限后不再领取。
3. `enqueue` 复用相同幂等键且 payload 一致的行，冲突 payload 拒绝。`claim_for_sending` 用 `BEGIN IMMEDIATE` 事务检查状态、尝试次数和到期时间并领取。
4. `mark_failed` 记录指数退避；force 重试可跳过等待时间，但不能跳过状态约束或次数上限。启动将遗留 sending 标为 interrupted / failed，不据此认定外部动作没发生。
5. 工具审批入口负责 enqueue / approve / claim / result 收口；tool_stage 只通过注入回调帮助处理。Outbox 的发送状态与 Runtime 的执行、核验、完成状态分别归自己的存储所有。

## Consequences / Limits

- eventId 缓存、请求 fingerprint 与 durable 行各有用途；缓存不能替代重启后恢复的持久化结果。
- `sent` 表示这条投递已记录结果，不直接等于 Runtime run 已通过核验并完成。
- 外部动作成功、回执尚未落库时崩溃，仍存在重试重复动作的窗口。通用 Outbox 不提供任意工具的 exactly-once 保证；需要具体工具的幂等能力或恢复核验。当前 Runtime 绑定的 Obsidian 链路有专门恢复校验，不能推广到所有副作用。
- 工具重试与主动投递是不同消费者；启动恢复 sending 不等于自动重跑所有工具。

## Evidence

- 源码：[`outbox.py`](../../infrastructure/outbox.py)、[`tool_approval_routes.py`](../../terminal/api/tool_approval_routes.py)、[`obsidian_runtime_bridge.py`](../../terminal/api/obsidian_runtime_bridge.py)、[`initiative_delivery.py`](../../core/initiative_delivery.py)。
- 回归：[`test_outbox.py`](../../tests/test_outbox.py)、[`test_tool_approval_cache_replay.py`](../../tests/test_tool_approval_cache_replay.py)、[`test_obsidian_runtime.py`](../../tests/test_obsidian_runtime.py)。
