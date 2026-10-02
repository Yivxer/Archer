# Archer 1.0.28：J8 安装态检查与主动线索生命周期

2026-10-02，验证等级 **installed**。本地分支 `codex/foundation-20261001`，未推送或公开发布。

## 本轮交付

- `8bdf186`：安装版 gate 报告因混用带时区/无时区历史时间，排序抛错。将时间统一到既有本地时钟，观察天数使用相同日期边界，不重写历史行。4 个脱敏复现先失败、后通过。
- `3c318ab`：Part 8 线索支持 `resolved / closed / dismissed / expired`。Today 和工作台观察候选卡提供“已完成 / 关闭 / 忽略 / 已过期”。操作不关闭普通聊天线程，不记为认可反馈，不修改 opt-in。
- 相同来源文本的重复保存复用原线索，终态不自动重开；不同来源依据保留独立线索。状态操作幂等，另一个终态请求返回冲突。
- 终态保留线索、时间和候选来源，追加 lifecycle trace、归档关联候选，取消尚未发送的关联 Outbox。排队、重试和聊天候选均检查线索状态；投递更新额外要求候选未归档，防止发送途中关闭后继续投递或覆盖终态证据。
- 过期由用户逐条标记，或显式调用维护入口；默认 30 天无更新。没有在启动/扫描时自动过期真实线索，当前生产线索不做批量清理。
- `a7c7e60`：Desktop 升至 1.0.28，使用干净 release 工作树打包；原 9 个未收口视觉/网页/评估修改未进入安装包，也未修改。

新增 POST `/initiative-threads/{id}/status` 与 `/initiative-threads/expire`，沿用认证、错误和版本封装。普通 `/threads` 与既有 REST/SSE 保持行为；数据库 schema 和记忆写入政策未改。新状态接口只控制 Part 8 cue，不用于 conversation capsule。

## 验证

| 范围 | 结果 | 边界 |
|---|---|---|
| 相关 Python | 45 passed | 终态、幂等/冲突、并发去重、显式过期、真实 capsule 域隔离、Outbox 取消与关闭/投递竞争 |
| Foundation | 137 passed，6 subtests | 提交 `3c318ab`；现有隔离入口和合成配置 |
| 完整 Python 离线 | 2004 passed / 65 deselected，6 subtests | 提交 `a7c7e60`；integration/journey 未运行；原 80 条长对话与 27 case baseline 保留 |
| Desktop | 44 files / 572 tests | 干净源码 `3c318ab`；其中新增控件/传输校验 16 项 |
| Build / package / sign | 通过 | Node 24.19.0；1.0.28 DMG；ad-hoc 签名，未公证 |
| Installed smoke | 9/9 | 首次在 API 就绪前执行失败，日志保留；等待 `/ready` 后重跑通过 |
| Installed 新接口 | 400 / 404，均符合预期 | 无效状态、缺失线索；没有对真实线索执行关闭或生成测试记忆 |
| 正常退出与重启 | 通过 | 退出后无监听；重启一个新 API PID，cwd 为主库；安装 app.asar 与干净包 SHA-256 一致 |
| 已有线程投影 | 40/40 匹配 | 安装版只读 REST capsule/version 与原库一致，不证明真实跨会话使用或模型回答 |
| 当前源码 J8 副本复查 | 真资料 30/30；真对话拆分回放 10/10 | 捕获实际模型调用前上下文，网络拒绝；30 题动态原文片段与 10-01 终稿完全一致，沿用人工复核的 1/25 无关（4%），未重新人工打分 |
| 模型额度 | 本轮 0 次 | 前轮脱敏 5 次尝试不变；没有发送私人问题到远程模型 |

13 个相关 Python 文件 Ruff 对照旧提交，新增诊断 0；新文件检查通过，既有诊断和 FastAPI/AsyncMock warning 未宣称清零。diff check 通过。UI 控件和传输已做回归、构建、安装；没有代替用户点击真实线索或反馈。

## 原始状态与恢复材料

受保护目录：`/Users/Yivxer/Library/Application Support/Archer J8 Checks/20261002-105054`。含原始资料摘要、只读 SQLite backup、前后状态比对、私人 J8 副本结果、失败/最终日志、1.0.27 app 备份及本轮源码 archive。私人内容没有写入仓库；本轮工具结果仅输出脱敏案例、代码、字段名和汇总。

安装检查启动应用时，既有 `create_rotating_backup` 自动更新当周两个导出文件、轮换删除最旧日备份一对。先保存全部新导出，再从启动前快照恢复这四个原导出文件；当天新备份保留。没有回退数据库或用户新内容。最终 **86 个原文件内容、51 个普通表（含虚拟表 shadow 数据）及 9 个原无关修改一致**。这证明内容/行一致，不宣称导出文件的 mtime 从未变化。

安装包在 `/Users/Yivxer/.codex/worktrees/foundation-release/Archer/client/desktop/release/Archer-1.0.28-arm64.dmg`。若需回滚，先正常退出并备份此刻新增状态，再恢复本轮 app 备份并匹配上一后端源码；无需为此次版本变化回退数据库。

## 保留未完成

- 完整 J8：真实历史跨会话样本和安装版完整私人回答质量。拆分回放不替代历史样本；本轮没有重新测语义检索 p95，10-01 的 340.72ms / 300ms 缺口保留。
- 主动续话真实反馈至少 3 条、相关性判断、人工 opt-in、真实投递与关闭停发。安装版 gate 已恢复正常报告，但 `can_enable_delivery=false`、opt-in=false，保持 shadow；不据本轮交付开放 Part 8。
- 桌面原视觉改动收口、store/adapter 与大文件治理、反馈回归产品闭环、Runtime 人工审查及逐域迁移、policy/ADR 仍依原成长计划推进。
- 10-01 诊断误打印私人上下文的事故记录保留。本轮输出边界守住，不撤销此前事故，也不据此声称整段历史从未暴露私人内容。
