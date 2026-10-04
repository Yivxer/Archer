# ADR 0006: FastAPI 作为默认本地 API 入口

Date: 2026-10-04
Status: accepted（回溯记录现有实现）

## Context

桌面客户端需要共享 Python 的对话、工具、安全判断和持久化能力。旧 HTTP handler 与新客户端并存时，分别实现业务规则会产生行为分歧。历史设计见 [P5.8](../p5-fastapi-migration-design.md)。

## Decision

1. `terminal/archer_api.py` 默认启动 FastAPI / uvicorn；`--legacy` 保留旧 HTTP server 作为兼容入口，不作为新增业务的第二份实现。
2. `terminal/api/fastapi_app.py` 负责 HTTP 传输、鉴权、限流、响应契约与启动恢复。普通请求进入 `_routes` facade，再转到领域模块；Runtime 路由单独注册。
3. Python 核心提供业务与执行能力，桌面端通过本地 HTTP 读取和操作这些能力。`POST /chat/stream` 使用 SSE。
4. 服务组合入口注入 `RuntimeContext`，传递数据库、配置、时钟、事件总线、模型客户端与取消注册表；不让客户端决定服务端存储位置。

## Consequences / Limits

- 业务模块拆分可保留旧调用路径； facade 规则沿用 [ADR 0002](0002-part10-facades-and-god-file-baseline.md)。
- 当前源码还提供 `/ws/chat`。它是服务端兼容能力，不能据此宣称桌面客户端已改走 WebSocket。
- 启动路径包含迁移、恢复和其他后台工作。路由测试应使用合成状态，不能为了验证传输层而启动生产迁移或调用真实模型。
- 本记录不删除 legacy 入口，也不调整 API 契约和部署方式。

## Evidence

- 源码：[`terminal/archer_api.py`](../../terminal/archer_api.py)、[`fastapi_app.py`](../../terminal/api/fastapi_app.py)、[`runtime_context.py`](../../core/runtime_context.py)。
- 回归：[`test_fastapi_routes.py`](../../tests/test_fastapi_routes.py)、[`test_desktop_api.py`](../../tests/test_desktop_api.py)、[`test_architecture_boundaries.py`](../../tests/test_architecture_boundaries.py)。
