# Settings 数据同步切片

2026-10-04，**build verified**，未打包、未安装。版本号仍为 1.0.34；当前安装包不包含本批源码。

实际 Settings 组件的合成失败回归：输入 `unsaved-model` 后刷新，新快照将其覆盖成 `server-model`。修复后同一场景通过。

- 新增页内 settingsSession，读取 `/settings` 后按基线保留用户改动；模型档位字段一起保留，避免把一个档位的草稿配到另一档位。保存期间的新输入继续保留，已保存密钥清空；恢复按钮使用最近成功读取的基线。
- 设置和定时列表的读取各有序号，页面离开、连接失效、凭据更换隔离旧响应；读取失败保留现有数据、显示错误及重试，禁用相应写操作。连接以 ready/degraded 为准，不能只看保留的 local adapter 快照。
- 页内写操作同步 busy 防重复。成功保存重读配置；成功定时变更重读列表。写入成功与后续读取失败分别呈现，不因 GET 失败自动重发 POST。档位配置保存收到失败回执时停止切换。
- 同步逻辑限 Settings，本批没有移除整体 adapter 的 settings 字段，也没有宣称整个 Settings 领域 authority 迁移完成。未改后端、CSS、Runtime、其他页面；未调用真实模型、未修改生产资料。

验证：Desktop 聚焦 **2 files / 30 tests passed**（settingsSession 8、localArcher 22）；TypeScript 与 `npm run build` 通过；实际 React Settings 组件的浏览器合成验收 **6/6**（刷新、失败保留/禁写、保存中编辑、档位拒绝、定时失败保留、未声明 API 调用为 0）。没有重复 Python 或 Desktop 无关全量，也没有真实 installed UI/API 验收。

合成入口与结果：`work/settings-check/fixture.tsx`、`check.mjs`、`results.log`。使用隔离浏览器，全部 8765 请求由合成处理器拦截；系统 Chrome 仅用于实际组件渲染，不读取用户浏览器资料。运行时 Node/Playwright 路径见交接。

Token Guard red：检查时任务日志约 1.32M，5h quota 29%（+23pp）；该日志量不等于计费 Token。按 guard 完成当前修复及必要验证后停止。后续只做一次集中打包安装及受保护只读验收；既有授权有效，安装前必须重新取得当前生产快照，不能复用昨日资料回滚。四个既有无关 dirty 文件保留。
