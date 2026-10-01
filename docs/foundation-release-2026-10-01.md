# Archer 1.0.27 本机交付记录

2026-10-01，验证等级 **installed**。分支 `codex/foundation-20261001`，未推送远端或公开发布。

## 安装与源码

- 安装包构建提交：`5e704ff7f9c69fc9cda07dfeab311ab497c9cc63`，来自独立干净工作树；原未收口的样式/网页/评估文件不在包中。
- 后续测试隔离：`883b0c6`、`98d1d88`，不改变生产逻辑。实际后端 `/Users/Yivxer/Projects/Archer` 的 268 个生产 Python 文件与构建提交逐文件一致。
- 已安装 `/Applications/Archer.app`，版本 1.0.27，app.asar 与干净构建包 SHA-256 相同；DMG 在独立 release 工作树的 `client/desktop/release/Archer-1.0.27-arm64.dmg`。
- Node 24.19.0 / npm 11.12.1；Python 3.14.6；配置 v2、数据库迁移 v10。配置内容未变，REST/SSE 与 schema 未扩展。
- ad-hoc 本机签名通过；未公证或面向外部分发。

## 验证

| 范围 | 结果 | 边界 |
|---|---|---|
| Python 离线回归 | 1959 passed，65 未选，退出码 0 | 选择 not integration and not journey；独立 checkout/config |
| 审计隔离追加回归 | 196 passed | Desktop API/契约、Obsidian Runtime、Outbox、Reflect；用户审计不变 |
| 项目 smoke | 9/9 | `run_tests.sh`，无模型 |
| Desktop | 42 files / 556 tests | Node 24；production build 通过 |
| Workflow eval | 27 case 通过 | 原 baseline 未改 |
| 脱敏记忆 | 30/30 正确，0/30 无关 | 合成主题与明确回忆问法；不代表私人全量或任意语义改写 |
| 脱敏线程 | 10/10 | 每线程两会话、重复注册、独立 Python 进程恢复目标/决定/纠正/未完成/停点 |
| 长对话 | 原 80 条回归保留通过 | 没有改写原预期 |
| 模型 | 两条隔离记忆/线程检查 + 一条安装版普通对话 | 安装 API 回复 OK，约 1.95 秒；没有保存测试会话或记忆 |
| 安装版本机检查 | 9 PASS / 0 FAIL | health / ready / status / modes / config doctor / bundle |
| 页面与重启 | 已验证 | Today、记忆、设置、已有历史会话；退出后监听消失，重启只有一个监听，原 Job receipt/attempt 不变 |

Python 检查仍有已有 FastAPI on_event 弃用及测试 AsyncMock warning；没有据此宣称全库 lint/type 债务清零。未启动全套模型 Journey。

## Runtime 原 blocker

原 Job `job-aa92290a` / Run `run-task-plan-c464da4408f7f6853390929a`，目标、保存参数、force=false、原 note mtime/hash 经核对。只执行一次显式 retry，未删除失败或新造替代样本。

- attempt `job-attempt-b01c3bc4553dec38edbe284c` complete；persisted result 和 business outcome 均 verified。
- Evidence Window `reviewable`，16 route receipt / 6 distinct Run；create/start 各 6 verified distinct Run，retry 3（4 verified candidate），drift/conflict/blocker 为 0。
- `authorityEnabled=false`、`humanReviewApproved=false`；Runtime 仍 shadow。完整迁移及人工审查留到下一阶段。
- 本次真实任务产出的候选 memory 307–311 / Soul proposal 117 保持 pending。
- 历史聊天中的旧失败文本保留为原记录，当前任务终态以 `/jobs` 与验证 receipt 为准；重启未重放该任务。

## 现场与测试隔离事故

开始前备份完成；9 个独立视觉、网页和评估文件与开始时哈希一致。原修改未整体提交、覆盖或清理。

旧测试只替换部分路径引用，曾污染默认情绪/独白/shadow/线程状态。对照开始前 SQLite backup：既有行逐行未变，清理前再次备份，只删除 12 条情绪、42 条独白、1 条 shadow 发送、8 条线程绑定、7 条线程状态（共 70），恢复原线程 JSON；真实 retry 的数据与 evidence 保留。独立工作树还会使用 HOME 审批审计，另备份并移除 76 条可确认的测试记录，保留 1646 条历史记录。

Reflect 和共享 API 审计路径已补测试隔离。其他旧测试的默认路径没有全面重写，后续全套仍必须使用独立 checkout 和临时配置，不能直接跑生产默认库。五类失败的复现与回归入口见 `docs/foundation-regression-2026-10-01.md`。

## 本机备份与回滚

受保护目录：`/Users/Yivxer/Library/Application Support/Archer Foundation Backups/20261001-141144`。含原 1.0.26 app、原后端 archive、配置、SQLite backup、memory 任务/会话、原工作树补丁、清理前状态、项目文档原件、发布 manifest 与验收日志。SQLite backup 的临时副本恢复完整性为 ok。

回滚顺序：正常退出 Archer → 备份此刻新增数据和改动 → 恢复旧 app → 将原后端 archive 解到独立目录，校对并切换到与 app 匹配的后端/必要配置。不要直接覆盖当前工作树或原未提交改动。应用版本回退通常无需恢复数据库；只有实际数据不兼容时才在保留新增用户数据的前提下另行处理数据库。

原 Obsidian 成长计划、架构当前事实区和客户端构建日志已回写。后续仍沿用原计划；本文件仅记录交付证据，不建立新的长期待办源。私人全量 J8、完整 Runtime v1、两周使用证据、UI/adapter 治理与反馈自动化均未在本轮宣告完成。
