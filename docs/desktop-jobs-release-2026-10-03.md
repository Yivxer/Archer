# Archer 1.0.33：后台任务同步治理

2026-10-03，**installed**。构建提交 `95e6ecc`（实现 `30e4c06`），本地分支 codex/foundation-20261001，未公开发布。

旧列表可覆盖取消后的状态，reset 后旧读取可重新填回数据，切换任务后旧详情和操作提示会串位；创建子任务只刷新列表，父任务详情仍是旧内容。6 条新行为测试先在旧实现失败，修复后通过。

- 任务 HTTP 拆到 jobAdapter；TasksPage 仅接收连接状态，Chat 的创建/取消/重试/审批/子任务/轮询统一经过 jobStore。main 在连接/重连时独立读取任务。
- 普通列表请求合并，force/reset/较新服务端回执使旧读取失效；详情切换/清空也隔离旧响应。失败保留列表并显示独立错误；busy 去重，finally 清除，不让 ok=false 假装成功。
- 先发布真实 POST 回执，再读列表与当前详情。后续读取失败不改成写入失败、不重复 POST；子任务父记录/汇总以服务端为准，失败保留表单。提示只出现在对应任务。
- 聊天轮询进入同一投影，事件采用较新服务器快照。SSE 进度文字仅用于 trace，不覆盖最终 result/evidence；普通详情读取不使聊天轮询停掉。
- 任务操作要求连接、列表成功、选中详情成功且不 busy。未改 Python 生产逻辑、REST/SSE/schema 或 Runtime 权威。

验证：干净提交 Desktop **52 files / 639 tests**，TypeScript/build、arm64 DMG/deep-strict ad-hoc 签名通过；隔离 foundation **140 passed + 6 subtests**（9 既有 warnings，含新增任务来源守门）。实际 TasksPage 合成检查通过失败保留/禁写、恢复、busy 防重复、取消、重试、子任务父详情、迟到详情与提示串位修复；未知请求 0，合成动作 3，模型调用 0。

`/Applications/Archer.app` **1.0.33**，asar 与干净包 SHA-256 一致。本机 **9/9**、一个 8765 API，后端 cwd 主仓库。确切旧 app 进程受控终止后旧监听消失，不冒充正常 UI 退出验收。installed API→实际 jobAdapter/jobStore→TasksPage SSR 一次只读 GET，13 个真实任务，标题进入渲染，仅保存数量/布尔/HTML 哈希。该检查不证明真实任务执行或私人模型回答。

保护与例外：本批期间真实运行新增一份会话和 desktop.obsidian_write 运行记录，已保存当前快照，保留全部新增内容；没有拿早晨基线回退生产数据。安装前后 51 张普通 DB 表中 50 张一致，scheduled_tasks 唯一变化为一行 last_run_at/next_run_at；无增删或任务内容变化。既有 startup 自动备份重写当天/本周四份导出，schedules.json 随调度更新。配置、会话、线程、记忆及四个无关工作树文件不变。不能声称所有持久化状态未变。

受保护目录 `/Users/Yivxer/Library/Application Support/Archer Desktop Checks/20261003-conversations-wccq_5s3` 保存安装前当前资料、DB、匹配源码和 app 恢复副本；无需为界面回滚整库。完整 Python 离线全量未重复；没有真实模型调用、代填候选反馈、开启 opt-in 或 Runtime 切权。下一批处理 initiative 的旧快照入口，Settings/跨域复盘与组件职责债务仍按原计划保留。
