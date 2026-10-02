# Archer 1.0.30：Soul 页面领域状态治理

2026-10-02，验证等级 **installed**。构建提交 `b971886`，本地分支 `codex/foundation-20261001`，未推送或公开发布。

## 改动与问题依据

旧路径会把整体 adapter 的 profile/files 注入 Soul store，页面还能回退读取旧 profile。重复加载及写入前的迟到响应可能覆盖新内容；失败的结晶响应也可能被标为 ready。新增回归在旧代码上复现 5 项失败，修复后通过。

- 新增 `soulAdapter.ts`，集中 profile、文件、结晶、导入和导出 HTTP 操作，复用原认证/超时/REST 解包。Python 核心、REST/SSE、schema、记忆审阅政策和 Runtime 权威未修改。
- Soul profile/files 从 `ArcherAdapter`、整体加载、mock/offline shell、storeSync 注入/回投影中删除。连接/重连成功后独立加载；SoulPage 只订阅其档案领域，ReviewPage 的 profile 也改订阅该 store。
- 普通并发加载合并；force 刷新和 reset 使旧成功/失败响应失效。全域读取成功才替换内容，失败保留上次有效内容并显示错误；初次未加载/失败不显示成已确认的空档案。
- 导入/结晶成功后强制刷新完整 Soul 域，避免动作之前的读取回盖；结晶动作较原实现多两次本地 GET。成功导入与后续读取失败分别显示，拒绝写入不发成功事件；跨域只定向重载 memory。
- 未连接时禁用刷新、导入、导出。选中空复盘时显示该周期为空，不回退到 SOUL 文件。

`localArcher.ts` 从 1128 减至 1089 行，`storeSync.ts` 从 78 减至 62 行。SoulPage 的 hypothesis/周期复盘/日记仍为其他领域的显式 props；其他页面和 adapter 域未完成迁移，不能称整端状态治理结束。

## 验证

| 范围 | 结果 |
|---|---|
| 相关 Desktop | 5 files / 103 tests passed，包含迟到成功/失败、请求合并、reset、导入与读取竞争、拒绝写入、读取失败保留内容和页面渲染 |
| 隔离架构守门 | 31 passed；删除旧字段/加载/注入/回投影路径，页面不读全量 adapter，保留 HTTP 投影边界 |
| Foundation | 干净提交 137 passed，6 subtests，9 既有 warnings |
| 全部 Desktop | 干净提交 45 files / 583 tests passed；TypeScript、production build 通过 |
| 实际 React 合成交互 | 5 场景通过：刷新、失败保留、空复盘、恢复清错、断线禁用；fixture 拒绝所有未声明请求，不加载私人资料 |
| Package / installed | Node 24.19.0；arm64 DMG、ad-hoc 签名验证；1.0.30 已安装，app.asar 与干净包 SHA-256 一致；未公证 |
| 本机检查 | 正常退出旧 API 监听消失，安装后单个 API 监听且 ready；smoke 9/9 |
| 本地真实只读投影 | 生产 HTTP → 实际 soulStore → 实际 SoulPage 的本地 SSR，档案条目与 SOUL 文件进入渲染；只输出布尔/数量摘要，不保存或输出私人 HTML |

真实只读投影使用当前源码与安装版 API，不是对安装版私人 UI 的逐项点击验收，也不证明模型回答或 J8 历史跨会话质量。没有执行真实导入、触发结晶或导出，本轮模型调用 0。没有修改 Python 运行逻辑，完整 Python 离线套件未重复；上一轮 2004 passed 保留为历史证据。

受保护材料：`/Users/Yivxer/Library/Application Support/Archer Desktop Checks/20261002-142655`。86 个原始资料文件最终一致，51 个普通数据库表一致，4 个无关未提交文件一致；启动轮转的 4 个 portable 导出文件先保留新生成材料再恢复原件，没有回滚用户数据库。

成长计划记录首个 Soul 档案领域已完成，逐页迁移大项仍保留待办。下一批处理 Memory 等剩余领域；大文件职责/行数守门和 CSS 治理继续分批，Part 8 gate、J8 真实跨会话及 Runtime 审查边界不变。
