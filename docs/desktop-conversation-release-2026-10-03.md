# Archer 1.0.32：会话与话题数据同步治理

2026-10-03，验证等级 **installed**。构建提交 `d4615f62b7ab70ad252e0643296e526c9659e21f`（实现 `fecc369`），本地分支 `codex/foundation-20261001`，未推送或公开发布。

## 行为与数据来源

- 会话、话题 HTTP 操作拆到 `conversationAdapter`；列表、详情、搜索、保存、删除由独立 store 管理。整体 adapter、mock/offline 和快照同步不再含 sessions/threads，Review、Projects、Chat 和导航读取同一份服务端投影。
- 普通并发读取合并；强制刷新/reset 使旧成功或失败失效。读取失败保留最近内容并显示刷新错误，成功保存与随后刷新失败分别处理，避免重复保存。切换会话和删除后不让迟到详情覆盖当前选择。
- 删除前端拼接话题摘要的路径，避免将助手建议标成用户最近结论。保存后重新读取会话/话题；两个独立领域各自发布状态，不承诺跨领域同一事务。
- Review 新增“在新会话继续这个话题”：沿用服务器 threadId 和线程上下文，首轮发送后保存为新会话，原会话保留。普通“恢复”仍续写原会话。断连或话题尚未成功加载时禁用新入口。
- 未改 Python 生产逻辑、REST/SSE、schema 或 Runtime 权威；POST 继续是原 flat receipt，GET 继续解包版本化 data。新增回归不放宽服务器要求完整用户/助手消息对的保存条件。

## 验证

| 范围 | 证据 |
|---|---|
| Desktop | 干净构建提交 49 files / 618 tests passed；TypeScript 和 production build 通过 |
| Foundation | 隔离 runner 138 passed、6 subtests、9 既有 warnings；包含两个进程之间创建同线程两份会话、重启恢复、只追加第二份、依次删除保持/移除话题的测试 |
| 领域守门 | 会话/Memory/Soul 六项源码边界检查通过；新增测试文件 Ruff、diff check 通过 |
| 合成页面 | 实际 Review/Projects/Chat 组件和生产样式，mock HTTP/bridge：读取失败保留、禁续话、恢复清错、删除为空及新会话续话→保存第二份均通过；未知请求 0 |
| Package | Node 24；arm64 DMG 和 deep/strict ad-hoc 签名通过；未公证 |
| Installed | `/Applications/Archer.app` 1.0.32，asar 与干净包 SHA-256 一致；对确切旧 app 进程受控终止，旧监听消失；启动后一个 API 监听，cwd 为主仓库，本机检查 9/9。未将该过程称作正常 UI 退出验收 |
| 真实只读投影 | installed API → 当前实际 adapter/stores → Review/Projects SSR：默认列表 20 份会话、40 个话题，真实标题进入渲染；只保存数量、布尔及 HTML 哈希，未保存私人 HTML |

默认 `/sessions` 为最近 20 份；受保护的 50 个原会话文件另行只读核对，50 个不同 threadId，真实多会话线程仍为 0。当前 `thread_resume` 候选 129、反馈 0、enabled opt-in 0、投递 0，shadow interactions 0。合成续话证明关联与刷新行为，真实只读投影证明展示链路；两者不证明真实跨会话回答质量或完整 J8。验收模型调用 **0**；完整 Python 离线全量未重复。

## 资料与恢复

受保护目录：`/Users/Yivxer/Library/Application Support/Archer Desktop Checks/20261003-conversations-wccq_5s3`。包含原配置/资料、SQLite backup、前后逐行哈希、测试/构建/安装日志、只读证据和旧 1.0.31 app 恢复副本。

- 纯测试阶段：129 个原文件和 51 张普通数据库表均未变化；虚拟表不直接查询，完整 SQLite backup 保留它们。
- 安装阶段：51 张普通数据库表均未变化，原配置、会话、记忆、线程以及四个无关未提交文件保持原内容。原有 startup portable backup 轮换产生 2026-10-03 每日两份文件，轮换删除旧每日四份并更新本周两份；旧六份原件在 protected/original。该副作用保留，不能称持久化文件全部未变。
- 旧 app：`app-recovery/Archer.app.backup-20261003-105948`；回滚先退出 app，恢复匹配旧包与后端源码，保留安装后的用户数据，不整库回退。

本批会话/话题子域完成；Jobs、initiative、Settings 等后续同步治理和组件职责拆分继续待办。另一分支 `feat/ui-shell` 的界面改版没有合入本包。J8 等待至少 10 个真实跨会话线程；候选反馈至少 3 条来自用户实际判断，再复核 gate。Runtime 切换保持独立安排。
