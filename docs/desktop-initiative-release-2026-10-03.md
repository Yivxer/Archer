# Archer 1.0.34：候选与反馈页面同步治理

2026-10-03，**installed**。干净构建提交 `303f725`（实现 `97a6acf`），本地分支 codex/foundation-20261001，未公开发布。

旧 initiative 读取只标记已加载，由整体 adapter 回填；报告读取失败可变成成功的空内容，反馈后只改候选而统计仍旧。3 条行为回归先复现旧问题，修复后通过。

- initiativeAdapter 并发读候选及 5 个报告端点，全部成功才由 initiativeStore 一次发布。移除整体 adapter/mock/offline 的 initiative 快照与 main 回填；storeSync 无生产调用。SSE 只提示读取，不在前端编造候选或统计。
- 普通读取合并，force/reset 隔离迟到响应；任一端点失败保留上次完整内容。反馈、静音、授权、线索动作要求读取成功且不 busy；Today、Review、Workspace 使用同一投影，并提供错误/恢复入口。
- POST 校验回执、busy 防重复，成功后重读全部报告。后续 GET 失败单独呈现，不重发已成功的写入；页面不再追加整体刷新。曝光认领并发合并，静音/反馈/reset 隔离旧认领，不使候选复活。
- Today 原先在早返回之后调用两个界面钩子，初次加载后钩子数量可能改变；已移到早返回之前，实际组件从 loading 到 ready 通过。工作台卡片的反馈与线索按钮统一禁写条件。
- REST/SSE/schema、后端投递 gate、显式 opt-in、每日上限和 Runtime 权威不变。合成测试不充当真实反馈；没有真实模型调用。

验证：干净 Desktop **54 files / 653 tests**，TypeScript/build、arm64 DMG/deep-strict ad-hoc 签名通过；隔离 Python 全量 **2013 passed + 6 subtests**，65 integration/journey 未选，160 既有 warnings。首轮 3 个旧源码断言失败，分别仍引用 saveLocalSession、Memory 旧 adapter 和 Review 整体刷新；更新为当前领域 store 与禁写不变量后全量通过，没有改回旧生产路径。

实际 Today/Review 合成页面：初次加载、反馈后报告更新、busy 禁写、单报告失败保留/禁写、恢复、静音通过；未声明请求 0、合成 POST 2。截图和脱敏检查摘要在受保护目录。实际 installed API → initiativeAdapter → initiativeStore → TodayPage SSR 只读 6 GET，5 条候选进入当前读取，页面渲染成功；仅保存数量/布尔/HTML 哈希，不保存私人正文。

`/Applications/Archer.app` **1.0.34**，asar SHA-256 与干净包一致；本机 **9/9**、单个 8765 API，后端 cwd 主仓库。没有活跃后台任务时受控终止确切旧主进程，旧监听消失后安装；这不冒充正常 UI Quit 验收。包为本地 ad-hoc 签名，未公证。

本批安装前后 **51 张普通 DB 表一致**，128 个被检查文件仅当天/本周四份自动备份导出改变，无新增资料文件；配置、会话、线程、记忆、四个无关工作树文件不变。本日早先的真实新会话和运行记录已保留，不使用早晨旧基线回滚数据。当前 51 份真实会话各属不同线程，跨会话样本仍 0；全库 129 候选，真实反馈/投递/enabled opt-in/曝光交互均 0。

受保护目录 `/Users/Yivxer/Library/Application Support/Archer Desktop Checks/20261003-conversations-wccq_5s3` 保存当前安装前资料/DB、对应源码 tar、旧 app 及检查记录。Settings、hypothesis/复盘跨域投影、组件职责与样式债务仍未完成；逐页迁移父项保持待办。真实样本和反馈继续在日常使用积累，Runtime 切换单独安排。另一分支 feat/ui-shell 不在当前包。
