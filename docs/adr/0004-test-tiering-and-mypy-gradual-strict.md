# ADR 0004: 测试分层与 mypy 渐进 strict 策略

Date: 2026-07-18
Status: accepted

## Context

P4 之前本地跑全量 pytest 需要 30+ 秒，开发循环慢；PR CI 又用文件列表枚举"快速子集"来压时间，但缺一个明确规则区分快测试和慢测试。

P5 引入 mypy 时面临另一个问题：现有代码 ~280 个 mypy 错误，一次性 strict 化不现实；但放任不管又会持续累积。需要一个既能展示趋势又不阻塞 PR 的策略。

## Decision

### 测试分层

1. 用 pytest marker 区分：
   - `@pytest.mark.unit`（默认）：纯函数 / mock 测试，<1s。
   - `@pytest.mark.integration`：真实 DNS、真实模型 streaming、真实文件 IO 等慢测试。
2. 本地默认：`pytest -m "not integration"` 跳过慢测试（30.6s → 0.46s）。
3. PR CI 继续用文件列表枚举确定性子集，不受 marker 影响；`tests/test_ci_workflows.py` 守门防止 PR CI 子集文件被误标 `integration`。

### mypy 渐进 strict

1. 在 `pyproject.toml` 配置 mypy baseline（`ignore_missing_imports=true`、`disallow_untyped_defs=false` 等宽松选项）。
2. PR CI 加 `mypy-check` job，**`continue-on-error: true`** 非阻塞，仅展示错误数趋势。
3. 对 `terminal.commands.*`（lazy import 误报）、`skills.*`（动态注册）、3 个 facade 大文件做 per-module `ignore_errors=true` 豁免。
4. 按集中爆发点修复（如 `DeferredSkillRegistry` vs `dict`、`lastrowid: int|None`、`int(object)` 转换），每次降低错误数。
5. 错误数降到 0 后再切换为阻塞门禁。

## Consequences

- 本地开发循环回到秒级；慢测试只在显式请求或 CI 全量跑时执行。
- PR CI 时长不因引入 marker 而波动。
- mypy 错误数（基线 278 → 豁免后 128 → 集中修复后 79）可见、可追踪、可回归。
- 后续若要切换为阻塞门禁，需要先把 per-module 豁免逐个解除。
- 解除豁免是按模块渐进的工作，不能一次性 strict 化全项目。

## Non-goals

- 不在本次引入覆盖率门禁。
- 不强制所有新代码必须标注类型（`disallow_untyped_defs=false`）。
- 不为 `terminal.commands.*` 的 lazy import 误报做重构，因为重构风险大于 mypy 收益。
