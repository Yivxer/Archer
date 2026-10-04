# Settings 领域读取与写入收口

2026-10-04，**build verified**。源码提交 `7f91eb1`。本批未修改版本号、未打包、未安装；`/Applications/Archer.app` 仍为此前 1.0.35，仅包含前一批页内同步修复，不包含本批领域拆分。

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

当前最强状态为 **build verified**；没有本批 native Electron dev 验收、打包/安装或安装窗口真实保存验收。前一批 1.0.35 的 installed 证据不能替代本批安装验收。成长计划保留逐页拆分父项待办，本批到此停止。
