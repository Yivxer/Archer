# Settings 领域读取与写入收口

2026-10-04，**installed，1.0.36**。实现提交 `7f91eb1`，发布提交 `8b46973`；干净发布 worktree 构建，本批集中安装一次。

## 行为与边界

- 新增 settingsAdapter，设置与定时 HTTP 操作复用既有鉴权/传输；从整体 localArcher 读取、ArcherAdapter 类型和 mockArcher 中删除 settings 快照。预览资料放独立 mockSettings，仅用于预览；本地连接没有配置时显示读取状态，不用预览档位充当已确认配置。
- settingsStore 持有最近成功 GET 的配置，合并并行读取，force/reset/凭据变更隔离旧响应；读取失败保留最近配置并标记不可写，重试仅发 GET。共享快照不保留输入密钥。
- SettingsPage、ChatPage 的档位/模型列表及个人面板读取同一领域投影。main 的专家刷新不再改写 settings 快照，而是定向重读；连接失效与凭据修改清除旧投影。聊天页切换按钮依据读取状态和 busy 禁写，并提供配置读取重试。
- settingsStore 负责设置保存、档位配置保存和活动档位切换的 busy、回执及成功后回读。离开设置页后已成功保存仍能更新共享配置；连接 reset 隔离旧写回执及后续读取。成功 POST 与回读失败分开，回读失败后禁止再写，先恢复 GET，不自动重复 POST；模型档位只以 GET 确认结果显示。
- 编辑草稿和提交后新增输入仍由页内 settingsSession 持有。成功保存后用共享已确认配置重建基线，避免重复读取和覆盖草稿。定时列表仍为页内会话投影，本批没有新增全局定时 store。
- 本批只收口 Settings 配置领域，不改变后端 REST/SSE/schema、Runtime、候选反馈或其他领域状态。SettingsPage 因其他跨域内容仍接收 ArcherAdapter；不宣称所有页面已完成拆分。

## 验证

- 聚焦 Desktop：3 files / **41 tests passed**（settingsStore 11、settingsSession 8、localArcher 22）。覆盖并行读取合并、失败保留、强制读取旧响应、reset/凭据隔离、重复切换、拒绝回执、POST 成功但 GET 失败、实际回读档位不符、保存后离页。
- Desktop 全量：**56 files / 672 tests passed**；TypeScript 和 `npm run build` 通过。
- 实际 React SettingsPage 合成浏览器：**8/8**。刷新保留草稿、读取失败保留/禁写、共享错误状态、保存中新输入、共享已保存值与草稿分离、档位拒绝、定时失败保留、未声明请求/真实模型请求为 0。全部 8765 请求由隔离浏览器处理器拦截，不连接生产 API，不读取用户浏览器资料。
- 隔离 runner：**18 passed**（profile、mode/expert、mock preview、Memory、conversation、Jobs、initiative 权威守门）；使用源码归档和合成配置，保护真实资料与生产 API。未重复无关 Python 全量。
- `git diff --check` 通过。模型切换回读的旧测试迁至领域 store；保留档位不符和拒绝回执的行为验证。

证据：`work/settings-domain-{focused-final,desktop-final,build-final,browser-final,authority-final}.log`、`work/settings-domain-authority.json`；组件入口 `work/settings-check/{fixture.tsx,check.mjs}`。没有真实模型调用或生产资料写入。

## 发布与安装版验收

- 1.0.36 TypeScript/build、arm64 DMG、deep-strict ad-hoc 签名通过，本地包未公证。仅安装一次；安装版 app.asar 与构建包哈希一致。沿用本批已通过的 672 Desktop、41 聚焦、18 隔离边界和 8/8 合成组件结果，没有重复无关全量。
- 停止确切旧主进程前检查无活跃后台任务，确认旧监听退出后重新取得当时生产资料/SQLite 一致性快照、桌面状态、源码归档及旧 app。没有使用前一批快照回滚。
- 安装版本机检查 9/9；实际原生窗口 Settings 检查 7/7：一次合成 GET 失败禁写、实际 GET 重试保留临时草稿并恢复可写、恢复确认配置、读取真实定时列表、切页签保留恢复结果、renderer 错误 0、写请求/模型请求尝试 0。只读取数值/布尔做验证，不导出私人 DOM、响应正文或截图；临时草稿已恢复，没有提交真实设置或运行定时任务。真实保存行为仍由 8/8 合成组件和领域测试证明。
- 验收过程中观察到个人中心鼠标点击被 chat-layout 遮挡，键盘 Enter 能进入设置；未定位成因、未证明旧版也存在，记录为后续体验问题。本批不改布局。脚本另修正了连接提示文案及回读完成等待时机，不改产品源码、未重装。
- 临时调试启动已结束，正常启动 ready，调试端口关闭；仅一个主进程与 8765 API，后端 cwd 主仓库。首次正常重开未留下运行进程，确认旧进程退出后重开成功，疑似退出/重开时机竞态，未作为产品修复宣称。
- 安装前后 51 张普通 DB 表完全一致；128 个原有检查文件无新增，配置/会话/线程及 4 个无关 dirty 文件不变。仅 schedules.json 顶层 updatedAt 和 4 份日/周自动导出改变，任务数组不变，保留自然启动导出。
- Runtime 未切权，候选反馈未代填，真实跨会话/回答质量和主动投递仍待实际使用与审查。接下来进入日常使用观察，优先真实问题的小修复，不追加本批功能或重构。

受保护证据与当前恢复资料：`/Users/Yivxer/Library/Application Support/Archer Desktop Checks/20261004-settings-domain-77cep7og`（0700）。

- app.asar SHA-256：`cffe128d9af3cf1fe8821045fcc338e088e4eccafe42905ef6b8c5bd4830abb5`
- DMG SHA-256：`a6ee10eb3a0d88fe0789295404fa66c9dcd4becaf65f7341fc2054a8e11ae537`
- 包：`/Users/Yivxer/.codex/worktrees/foundation-release/Archer/client/desktop/release/Archer-1.0.36-arm64.dmg`
- 结果：`installed.json`、`native-settings.json`、`live-smoke.log`、`comparison.json`；当时快照、旧 app 与源码归档均保留在同目录。
