# Archer 1.0.31：Memory 领域状态治理

2026-10-02，验证等级 **installed**。构建提交 `62f0f1e695332471551e9fc2ecb19627b9c33c0a`，本地分支 `codex/foundation-20261001`，未推送或公开发布。

## 问题与修复

旧实现确认记忆后直接从 items 删除，分类 groups 没有同步；编辑只改 items，分类仍显示旧文本。读取缺少并发保护，迟到响应可覆盖较新内容。9 条新增行为回归在旧实现上出现 8 条失败，修复后全部通过。

- 新增 `memoryAdapter.ts`，七个记忆 HTTP 操作从整体 adapter 移出，复用原认证、超时和契约解包。未改 Python 运行逻辑、REST/SSE、schema、记忆审阅政策或 Runtime 权威。
- `ArcherAdapter` 不再含 memory；整体加载、mock/offline shell、storeSync 均删除记忆列表、注入和回投影。连接/重连独立加载 Memory；Soul 导入/结晶只定向刷新 Memory。
- 普通并发加载合并；强制刷新/reset 使旧成功或失败响应失效。items、stats、groups 全部读取成功才一起发布，失败保留最近完整快照。
- 确认/拒绝、编辑、批量审阅和演化成功后强制刷新三项，不在本地编造最终状态。已确认记忆保留，分类文本同步；POST 成功和后续读取失败分别呈现，单条操作结束清除 busy。
- MemoryPage 只接收 connected；导航、ProfilePanel、Settings 的记忆数据直接订阅 store，Review 的记忆操作要求连接且已加载成功。页面显示读取错误、初始/加载/成功为空，失败保留可读内容，刷新失败或断连时不能写记忆。

单条审阅从 POST + stats GET 变为 POST + 三个 GET；编辑从 POST 变为 POST + 三个 GET，增加本地读取以保持分类/计数一致。REST `/status` 计数字段继续兼容，界面计数使用 store；没有增加模型调用。其他页面/领域仍待迁移，ChatPage/Settings/main 的职责拆分、实际行数守门和 CSS 治理没有在本轮完成。

## 验证

| 范围 | 结果 |
|---|---|
| 相关 Desktop | 5 files / 104 tests passed：请求合并、旧成功/失败隔离、reset、写入与旧读取竞争、确认后保留、分类编辑同步、失败保留和页面连接边界 |
| 隔离架构守门 | 31 passed：Memory/Soul authority 与既有边界；旧字段/读取/注入/回投影路径删除 |
| Foundation | 干净提交 137 passed，6 subtests，9 既有 warnings |
| 全部 Desktop | 干净提交 46 files / 596 tests passed；TypeScript、production build 通过 |
| 实际 React 合成页面 | 6 场景：确认后分类/计数、编辑同步、读取失败保留并禁写、恢复清错、空分类、断连禁刷新；只使用合成资料与 mock HTTP，拒绝未知请求 |
| Package / installed | Node 24.19.0；arm64 DMG、deep/strict ad-hoc 签名通过；1.0.31 已安装，app.asar 与干净包 SHA-256 一致，未公证 |
| 本机 smoke | 正常退出旧监听消失；新启动单个 API，ready 后 9/9，工作目录为主仓库 |
| 本地真实只读投影 | 安装版 API → 实际 memoryAdapter → memoryStore → MemoryPage SSR：97 条、36 pending、6 groups，待确认文本和统计进入渲染；只输出数量、布尔和 HTML 摘要哈希，不存储或输出私人 HTML |

真实只读投影采用当前源码与安装版 API，不是安装版私人 UI 的逐项点击验收，也不证明模型回答、真实历史跨会话或 J8 完整达标。没有对真实记忆执行确认、拒绝、编辑或演化；验收模型调用 0。Python 运行逻辑未改，完整离线 Python 套件未重复，之前的 2004 passed 只作为历史证据。

## 资料完整性与例外

受保护材料：`/Users/Yivxer/Library/Application Support/Archer Desktop Checks/20261002-151523`，问题回归仅保存合成样本在仓库。

- 85/86 个原始文件一致；51 个普通数据库表中 50 个一致；4 个无关未提交文件一致。不能报告为持久化状态全部未变。
- 唯一例外是原有内部 `reflection_scheduler.scan_hypotheses` 调度任务：旧 next_run 已到期，正常安装重启后的运行时间距安装日志 3.84 秒；`scheduled_tasks` 一行仅 `last_run_at` / `next_run_at` 变化，无增删或任务内容变更。`schedules.json` 对应时间及 updatedAt 改变。启动代码调用既有 run_due_tasks，内部扫描为本地查询，无模型调用。已保留新调度时间，没有回滚用户数据库；原件在受保护快照。
- 启动轮换的 4 个 portable 导出文件已先保留新材料，再恢复原件；记忆、线程、会话内容未变。

这次正常重启属于安装验证，存在上述调度副作用；不应将这份记录作为“所有本地验收均无生产状态变化”的证据。纯副本验收与安装验证分别记录。

成长计划已追加 Memory 子域里程碑；逐页迁移父项继续待办。下一批优先推进剩余领域和旧快照路径，再处理大文件职责/守门。Part 8 gate、真实用户反馈、J8 历史跨会话和 Runtime 人工审查边界不变。
