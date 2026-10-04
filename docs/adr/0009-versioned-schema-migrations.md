# ADR 0009: 数据库与配置的版本化迁移

Date: 2026-10-04
Status: accepted（回溯记录现有实现）

## Context

数据库增加表、字段和 Runtime 账本时，需要可重复执行、拒绝不兼容版本和失败恢复的明确入口。配置升级还涉及凭证，不能沿用数据库备份方式留下明文副本。

## Decision

1. SQLite 通过 `memory.migrations.run_migrations` 迁移。`schema_version` 记录版本、checksum、说明与应用时间；已应用版本不再重复执行。
2. 应用前核验已记录版本：未知版本或 checksum 不符即拒绝继续。新增变更追加 migration，不改写已发布迁移的身份材料。
3. 有待应用迁移时，先做 WAL checkpoint，再使用 SQLite backup API 保存迁移前状态；随后顺序应用并记录版本。异常时恢复本次备份；新建数据库无原文件时清理失败产物。
4. FastAPI 启动先迁移，再做 Runtime / Outbox 恢复。升级应用前仍需当前数据快照，不能拿旧快照覆盖后来产生的有效数据。
5. TOML 配置由 `core.config_contract` 校验 `config_version`，拒绝未来版本；凭证迁移完成、序列化并再校验后，通过同目录临时文件原子替换。不会自动留一份含明文密钥的配置备份。

## Consequences / Limits

- 数据库迁移与 TOML 配置迁移是两条机制；数据库版本号不代表桌面版本或 authority 切换状态。
- checksum 使用 migration 的既定材料；现有迁移提供稳定 `checksum_material`，并非自动追踪所有被调用函数的源码变化。修改 schema 必须新增 migration。
- 当前 runner 没有覆盖整个迁移序列的跨进程互斥锁，也没有通用向下迁移能力。迁移应由受控启动执行，避免并行 migrator；失败备份恢复不等于任意版本降级。
- 本批只记录和回归机制，不执行生产数据迁移。

## Evidence

- 源码：[`migrations.py`](../../memory/migrations.py)、[`config_contract.py`](../../core/config_contract.py)、[`fastapi_app.py`](../../terminal/api/fastapi_app.py)。
- 回归：[`test_migrations.py`](../../tests/test_migrations.py)、[`test_config_contract.py`](../../tests/test_config_contract.py)。
