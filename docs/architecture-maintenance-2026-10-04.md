# 架构说明与后端维护收口

2026-10-04。范围：五篇回溯 ADR、工具审批职责说明、policy 按职责拆分与行数守门。现有 ADR 0001–0005 保留。

## 决策入口

| ADR | 说明 |
| --- | --- |
| [0006 FastAPI](adr/0006-fastapi-local-api.md) | 默认本地 API、传输层与 Python 业务分工 |
| [0007 core / memory](adr/0007-core-memory-dependency-boundary.md) | 模型 port 注入、core.paths 兼容例外与历史全局依赖 |
| [0008 服务端权威状态](adr/0008-server-authoritative-state.md) | 持久化事实、客户端投影、草稿及 Runtime 切权边界 |
| [0009 schema migration](adr/0009-versioned-schema-migrations.md) | 版本、checksum、备份恢复与配置原子替换 |
| [0010 Durable Outbox](adr/0010-durable-outbox.md) | 持久化发送状态、领取、重试与重复副作用窗口 |

## 工具审批职责与调用边界

| 模块 | 持有的职责 | 状态边界 |
| --- | --- | --- |
| `terminal/api/tool_approval_routes.py` | 审批编排、选草稿、接执行器、Hugo follow-up、Outbox 与 Runtime 桥接、回执收口和重试 | 协调已有存储；不另建审批事实库 |
| `terminal/api/tool_stage.py` | 解析决策、准备 fingerprint、包装执行结果、组合响应与 follow-up | 经注入的回调读写、执行；无自有数据库和缓存 |
| `terminal/api/_config.py` | eventId 草稿、事件结果、fingerprint 结果缓存和审批 audit 接口 | 进程内缓存不能替代 Outbox 持久化事实 |
| `infrastructure/outbox.py` | durable payload、发送状态、领取、退避、结果与中断恢复 | 唯一的 Outbox 行状态；不拥有 Runtime 完成状态 |
| `terminal/api/obsidian_runtime_bridge.py` | 绑定 Runtime、批准/取消/失败、核验写入及恢复已完成执行 | 把工具结果交给 Runtime 生命周期接口收口 |

实际主调用顺序：

1. `_tool_approval` 经 `parse_approval_decision` 校验输入，优先复用 eventId 结果；再解析草稿与 fingerprint 结果。
2. 对有 runtime_context 的 tool_request 准备 durable 行。approved 才领取 sending；denied 走取消与 audit / 结果缓存。
3. `_run_approved_draft` 注入具体执行回调给 `execute_approved_draft`，必要时运行 Hugo follow-up。带 Runtime 契约的路径由 bridge 校验与收口。
4. `_finalize_approval` 调用 stage 的响应构造与缓存/audit 回调；发送成功记录 sent，执行失败记录 failed。缓存命中路径也检查已有 Runtime 收口。
5. `_retry_tool_outbox` 从 durable payload 恢复草稿；Runtime 绑定路径核对 fingerprint、尝试恢复已有完成结果，再执行与核验。重试不依赖旧进程内草稿。

判断：当前 stage 的数据对象和回调不是第二套持久化状态机；调用图与源码没有给出把两个模块合并的依据。因此保留分工。将来若 helper 自建缓存/数据库或同一状态出现两套迁移，再以具体复现立项。

## policy 维护

- `core/policy.py` 从 896 降为 730 行，保留 ALLOW / CONFIRM / STRONG_CONFIRM / DENY 的决策入口、命令风险、路径和 MCP 判断。
- `core/policy_code_scan.py` 188 行，完整承接 installer 的危险 API 表、AST 扫描、编码展开与语法错误回退。公开和历史私有名字继续由 policy 导出；未修改规则、提示或风险等级。
- 两文件以实际行数纳入 `GOD_FILE_LINE_BASELINE`。新增 helper 依赖守门，防止 scanner / stage 直接接数据库或业务存储；增加六个编码、去重顺序、回退与干净代码回归案例。
- 达到职责完整性和主文件 <800 的目标，本批不再为 <400 强拆命令与 MCP。

## 验证与发布边界

验证结果待隔离回归后填写。本批没有修改桌面源码、版本和安装包，没有改变生产配置、数据库、审批缓存或 Runtime authority 开关。
