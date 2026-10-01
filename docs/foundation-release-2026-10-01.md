# Archer 1.0.27 本机交付记录

2026-10-01，验证等级 **installed**。分支 `codex/foundation-20261001`，未推送远端或公开发布。

## 安装与源码

- 安装包构建提交：`5e704ff7f9c69fc9cda07dfeab311ab497c9cc63`，来自独立干净工作树；原未收口的样式/网页/评估文件不在包中。
- 首次安装时，后端 `/Users/Yivxer/Projects/Archer` 的 268 个生产 Python 文件与构建提交逐文件一致；`883b0c6`、`98d1d88` 只修复测试隔离。随后后端增量见下节，当前不能再称全部 Python 与首包构建提交一致。
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

Reflect 和共享 API 审计路径已补测试隔离。现有 `run_tests.sh` 现在自动创建独立 checkout 和临时配置；其他旧测试的默认路径没有全面重写，不能直接在生产配置下运行裸 pytest。五类失败的复现与回归入口见 `docs/foundation-regression-2026-10-01.md`。

## 同日第一次后端增量与离线入口收口（历史快照）

- 后端提交 `b40c7fea0573a91db6505a0d994af0529a9f50e6`；生产差异只有 `core/user_outcome_confirmation.py` 与 `core/desktop_tool_router.py`。已正常退出并重启安装版加载该后端。桌面包继续是 `5e704ff` 的 1.0.27，app.asar 与原干净包一致；本次没有重新构建 Desktop/DMG。
- `6a27a04`：同一结果确认并发时，Step 已收口而 Run 尚未收口会误报冲突。保留唯一不可变回执，有限次重读/CAS 收敛该中间态；真实状态冲突与取消仍拒绝。8 项确认测试含接受、纠正和取消优先。
- `cbfcad2` / `b40c7fe`：macOS `/Users/` 路径下润色本地文章被旧规则误判成博客发布，抑制写回预览。补充内容修改识别，原文未写入，确认卡恢复；明确发布指令的既有行为保持通过。扩写/缩写只验证不误触发布，未扩展其写回能力。
- `e8762c7` / `86a63a8`：默认 smoke、foundation、full 都由一次性源码快照运行，使用公开模板、合成 persona、独立 DB/session/vault；Python audit hooks 拒绝用户状态写入、用户库连接、外部连接及生产 8765 API。该保护针对意外副作用，不是 OS sandbox。
- 最新验证：smoke 9/9、foundation 90、全量离线 **1967 passed / 65 deselected**（另有 6 subtests）；workflow 原 27 case baseline 由全量套件校验，未改 baseline；改动 Ruff / diff check 通过。没有新增模型调用。
- 安装版本机检查 9/9；退出后无监听，重启一个新 API PID，cwd 指向上述主库后端；界面就绪且已有历史列表恢复。原 Job attempt/verification receipt 不变，窗口仍 reviewable、16 receipt / 6 distinct Run、shadow、authority=false。
- 测试及重启前后：真实库 53 张表逐行哈希一致；配置、任务、线程索引、审计文件与 50 个会话文件清单一致。详细记录保存在原备份的 `offline-entry-20261001/`，含最新后端 archive、验收日志与前后比对，不提交私人数据。

## 最新：跨进程 API 恢复收口

- 当前后端为 `79f256d189b737378bd37888696a2aa45fbf352f`，已由安装版正常退出/重启加载；桌面仍为 `5e704ff` 的 1.0.27，app.asar 与原干净包一致。本次没有重建 Desktop/DMG。
- 新增两个独立 Python 进程中的 FastAPI TestClient 流程：会话保存、记忆必须先 pending、接受/拒绝及重复决定、审批拒绝、建 Job 幂等、取消、重启后恢复目标/决定/纠正/停点。它是合成离线 API 验收，不冒充真实模型旅程，也不验收 Desktop Plan 卡本身。
- `ba466a0`：默认线程索引路径先被解析，随后误判成显式隔离路径，GET 线程漏掉已有 SQLite capsule。保留解析前的路径判断；显式隔离路径继续不访问默认库，显式 db_path 仍可投影上下文。
- `79f256d`：同一审批草稿重建后仅 `_cacheCreatedAt` 不同，会使 Outbox 报载荷冲突。仅该缓存字段可以忽略；其他业务/审批字段必须完全一致才复用原 immutable payload 与 receipt。旧行未重写，真实参数或授权差异仍拒绝；没有重试真实副作用。
- 最新：Python 离线 **1974 passed / 65 deselected**，foundation **101**，smoke 9；Desktop 干净源码 **42 files / 556 tests**，workflow 原 27 case baseline 通过全量校验。新增/审批文件 Ruff 通过；thread_store 既有 UP017、outbox 既有 I001 未顺带修改，按原问题忽略后检查通过；diff check 通过。
- 安装版 9/9；退出后无监听，重启一个新 API PID、cwd 指向当前后端；UI 就绪/历史列表通过。只读 `/threads` 中 40 个已有线程的 capsule 与原数据库完全一致；原 Job attempt/result/outcome receipt 保留，Evidence 仍 reviewable / shadow / authority=false。
- 测试及重启前后真实库 53 张表逐行哈希一致，配置/任务/线程索引/审计和 50 个会话文件清单一致，9 个原无关修改逐字节未变。本轮模型调用 0。
- 原备份的 `api-restart-20261001/` 保存前后对照、失败及最终通过日志、后端 archive 和项目文档快照。此增量无需数据库回退；如需回滚，正常退出并备份新增修改后，将后端恢复为上一增量 `b40c7fe` 的匹配源码，保留同一桌面包、配置与新增用户数据。

## 本机备份与回滚

受保护目录：`/Users/Yivxer/Library/Application Support/Archer Foundation Backups/20261001-141144`。含原 1.0.26 app、原后端 archive、配置、SQLite backup、memory 任务/会话、原工作树补丁、清理前状态、项目文档原件、发布 manifest 与验收日志。SQLite backup 的临时副本恢复完整性为 ok。 同日补充组合恢复演练：旧 1.0.26 app 的 267 个文件及 14 个符号链接逐项匹配，权限与 codesign 检查通过；原后端 `fec88ba`（760 文件）、当前后端 `79f256d`（772 文件）archive 与对应 Git 提交一致，安全解包后逐文件一致，实际 API 入口存在；配置 TOML 可解析；SQLite 53 张表完整性 ok；memory/journal、任务、线程与 50 个会话副本哈希一致且 JSON 可解析。演练临时目录已删除，证据为备份目录的 `restore-drill-20261001.json`。只验证恢复材料，不启动旧 app、不替换当前安装/数据库，不据此宣称旧版本与当前数据运行兼容。

回滚顺序：正常退出 Archer → 备份此刻新增数据和改动 → 恢复旧 app → 将原后端 archive 解到独立目录，校对并切换到与 app 匹配的后端/必要配置。不要直接覆盖当前工作树或原未提交改动。应用版本回退通常无需恢复数据库；只有实际数据不兼容时才在保留新增用户数据的前提下另行处理数据库。

原 Obsidian 成长计划、架构当前事实区和客户端构建日志已回写。后续仍沿用原计划；本文件仅记录交付证据，不建立新的长期待办源。私人全量 J8、完整 Runtime v1、两周使用证据、UI/adapter 治理与反馈自动化均未在本轮宣告完成。
