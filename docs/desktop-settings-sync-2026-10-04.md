# Settings 数据同步切片

2026-10-04，**installed，1.0.35**。实现提交 `db678e5`，发布提交 `895b62c`；从干净发布 worktree 构建，本批集中安装一次。

实际 Settings 组件的合成失败回归：输入 `unsaved-model` 后刷新，新快照将其覆盖成 `server-model`。修复后同一场景通过。

- 新增页内 settingsSession，读取 `/settings` 后按基线保留用户改动；模型档位字段一起保留，避免把一个档位的草稿配到另一档位。保存期间的新输入继续保留，已保存密钥清空；恢复按钮使用最近成功读取的基线。
- 设置和定时列表的读取各有序号，页面离开、连接失效、凭据更换隔离旧响应；读取失败保留现有数据、显示错误及重试，禁用相应写操作。连接以 ready/degraded 为准，不能只看保留的 local adapter 快照。
- 页内写操作同步 busy 防重复。成功保存重读配置；成功定时变更重读列表。写入成功与后续读取失败分别呈现，不因 GET 失败自动重发 POST。档位配置保存收到失败回执时停止切换。
- 同步逻辑限 Settings，本批没有移除整体 adapter 的 settings 字段，也没有宣称整个 Settings 领域 authority 迁移完成。未改后端、CSS、Runtime、其他页面；未调用真实模型。开发阶段未触碰生产资料，安装启动的文件变化见下。

验证：Desktop 聚焦 **2 files / 30 tests passed**（settingsSession 8、localArcher 22）；TypeScript 与 `npm run build` 通过；实际 React Settings 组件的浏览器合成验收 **6/6**（刷新、失败保留/禁写、保存中编辑、档位拒绝、定时失败保留、未声明 API 调用为 0）。没有重复 Python 或 Desktop 无关全量。开发期未做真实 installed UI/API 验收；本次安装验收见下。

合成入口与结果：`work/settings-check/fixture.tsx`、`check.mjs`、`results.log`。使用隔离浏览器，全部 8765 请求由合成处理器拦截；系统 Chrome 仅用于实际组件渲染，不读取用户浏览器资料。运行时 Node/Playwright 路径见交接。

开发阶段曾因旧 guard 的 quota 增幅规则停止；这是历史记录。最终收尾使用更新后的 guard，开始时 green（5h 51%、7d 36%），按既有授权继续。

## 最终发布与只读验收

- 干净发布提交 `895b62c`：TypeScript/build、arm64 DMG 打包、deep-strict ad-hoc 签名通过。本地包未公证，未公开发布。`/Applications/Archer.app` 版本 1.0.35，与构建 app.asar 哈希一致；安装只执行一次。
- 安装前确认后台任务无活跃项，受控终止确切旧主进程并确认旧 8765 监听消失；这不冒充正常 UI Quit 验收。随后重新取得当时生产资料和 SQLite 一致性快照、桌面状态、当前源码归档及旧 app，没有使用昨日快照回滚。
- 本机检查 9/9，单个 8765 API，后端 cwd 为主仓库。实际安装版 API → 当前 Settings 读取器/settingsSession 的只读验收通过：设置/定时 ready、未保存草稿跨 GET 保留、恢复基线；同版本源码 SettingsPage 静态渲染成功。最终一次限定 3 GET；前两次脚本缺浏览器存储模拟失败，修正脚本后通过，累计 9 GET，写请求和模型请求均 0。监听检查另修正了 lsof 字段解析；产品源码未改，未重装。
- 本批未做安装版窗口内交互操作；实际交互证据仍为前述 6/6 合成浏览器测试。只读源码渲染不能替代安装窗口交互验收。未执行真实保存、模型连通测试或定时运行，不代填候选反馈。
- 安装前后 51 张普通 DB 表完全一致；128 个原有检查文件中，`memory/schedules.json` 仅顶层 updatedAt 改变，任务数组不变；4 份既有自动备份导出改变，另新增当天 2 份导出。配置、会话、线程、记忆表及 4 个无关 dirty 文件不变。保留这些自然启动导出，没有回滚用户资料。
- 整体 adapter 的 settings 字段仍保留，Settings 完整领域拆分、其他领域和 Runtime 权威迁移未在本批完成；Runtime 未切权。

证据与当前生产恢复材料：`/Users/Yivxer/Library/Application Support/Archer Desktop Checks/20261004-settings-r5uojq_k`（目录权限 0700）。只读结果仅保存数量、布尔与哈希，不保存响应私人正文；生产快照仅存受保护目录。

- app.asar SHA-256：`41695407f85faebec763b58aec0e5e1dfb73a09d8d48571af49e535c801321e4`
- DMG SHA-256：`4ed7f9ee2a1831b3d5ee84565718a4edae08d7b2743d64fe24ad235b137d95fe`
- 包：`/Users/Yivxer/.codex/worktrees/foundation-release/Archer/client/desktop/release/Archer-1.0.35-arm64.dmg`

本批最终发布收尾完成，停止，不继续其他领域。
