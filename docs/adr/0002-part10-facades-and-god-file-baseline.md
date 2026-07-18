# ADR 0002: Part 10 Facades 与 god file 行数守门

Date: 2026-07-18
Status: accepted

## Context

Part 10 之前 `terminal/api/_routes.py`（913 行）和 `terminal/api/_tools.py`（3368 行）是 god file：所有路由、所有工具执行 helper 都堆在一起。每次新增功能都让它们更难维护，但旧调用方（FastAPI app、终端、Desktop adapter）又大量引用其中的函数名，直接迁移会破坏多个端口。

Part 10 Wave 1-2 需要一个既能拆分又不破坏调用方的边界规则。

## Decision

1. 把 `_routes.py` 和 `_tools.py` 改为 **facade**：只做 re-export，不再直接定义 domain 函数。
2. 真实实现按 domain 落到 `terminal/api/{session,job,tool_approval,memory,profile,initiative}_routes.py` 和 `terminal/api/tool_*_helpers.py`。
3. 用 `tests/test_architecture_boundaries.py` 守门：每个 domain 模块对应一个 `test_*_live_behind_routes_facade` 测试，确保 facade 只 re-export 不直接定义 domain 函数。
4. 用 `GOD_FILE_LINE_BASELINE` 监控 `_routes.py` / `_tools.py` / `job_routes.py` / `ChatPage.tsx` 等关键文件行数，超基线即测试失败。

## Consequences

- 调用方无需改动 import 路径（facade 兼容）。
- 新功能必须落到 domain 模块，不能再加到 facade 里。
- god file 只会单调下降；任何回升都需要显式抬高 baseline 并说明理由。
- 后续若要彻底废弃 facade，只需删 re-export 行，调用方按 domain 模块逐个迁移。

## Non-goals

- 不要求一次性删除所有 facade re-export（向后兼容优先）。
- 不在本次引入按 domain 拆分的子测试套件。
