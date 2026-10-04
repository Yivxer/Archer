# 侧栏隐藏控件与个人中心入口验收

2026-10-04，**installed，1.0.37**。实现与发布提交 `cd5158df086cf36e5a45e94dc8977dde2ae5ef5f`，干净 release worktree 构建，集中安装一次。

## 原因与修复

- 复核 1.0.36 原生窗口时，侧栏实际处于收起状态。展开侧栏后，鼠标可以打开个人中心并进入 Settings。此前 Settings 验收脚本直接定位收起侧栏内的 `.profile-footer`，再用 Enter 激活，没有先展开侧栏；因此此前的聊天区域拦截记录不能证明可见入口存在层级故障。
- 实际缺口：收起侧栏的内部控件仍可获取键盘焦点，也出现在原生无障碍树。脱敏浏览器复现隐藏个人入口 `focus()` 后成为 activeElement；安装版旧无障碍树也包含这个隐藏入口。
- `main.tsx` 的 sidebar aside 增加 `inert={!sidebarOpen}` 与 `aria-hidden={!sidebarOpen}`。收起时阻止焦点与交互，并明确隐藏可访问性内容；展开后恢复。保持现有布局、路由、设置同步与 CSS 层级。

## 验证

- 连接状态聚焦：24 passed；Desktop 全量：56 files / 672 tests passed。
- 实际 App 组件的脱敏浏览器：700 / 820 / 1280 三种宽度 × light / dark，两种外观，共 **44 项通过**。包括隐藏焦点隔离、可访问控件过滤、展开恢复、按钮中心命中、鼠标进入 Settings 和再次收起。renderer 错误 0，全部 8765 请求被合成处理器拦截，写入 / 模型请求尝试 0。
- TypeScript/build、arm64 DMG、deep-strict ad-hoc 签名通过；安装版 app.asar 与构建包一致。本地包未公证。
- 安装版本机 smoke **9/9**；原生鼠标操作 **6/6**：收起隐藏入口、展开显示就绪入口、鼠标打开个人中心、鼠标进入 Settings、鼠标返回聊天、再次收起后隐藏入口。没有提交设置或聊天，恢复原侧栏收起状态；只保存布尔验收结果。
- 正常启动，主进程一份、8765 API 一份。未启用临时远程调试端口。

## 数据与恢复

安装前确认无运行中 Job，停止确切旧主进程并等待 API 退出后，重新取得当时的 SQLite 一致性备份、文件快照、桌面状态、源码归档与旧 app。没有拿上一批快照回滚。

安装前后 51 张普通表中，50 张完全一致；`scheduled_tasks` 仅已有内部 `reflection_scheduler.scan_hypotheses` 到期扫描的一行 `last_run_at / next_run_at` 更新，无新增或删除任务。对应 schedules.json 只改任务的 lastRunAt / nextRunAt 及顶层 updatedAt；另有四份启动日/周自动导出刷新。配置、会话、其他记忆表和四个无关 dirty 文件未变。保留这些自然启动结果，没有回滚。

受保护恢复与验收资料：`/Users/Yivxer/Library/Application Support/Archer Desktop Checks/20261004-sidebar-entry-damm3oeu`（0700）。

- `installed.json`、`native-entry.json`、`comparison.json`、`quiescence.json`，以及本批日志、数据、桌面状态、源码和旧 app。
- app.asar SHA-256：`514d0ecf5856ba73f217b5640fe6217fcdc953ce523aa51aadc542a35924ea1e`。
- DMG SHA-256：`b7f2eccb7f2e1c7a819f5b41b8a4527e7b0ec5bcfcfe112503f61583ff185006`。
- 包：`/Users/Yivxer/.codex/worktrees/foundation-release/Archer/client/desktop/release/Archer-1.0.37-arm64.dmg`。

## 独立观察项

700px 合成窗口中，Settings 关闭按钮的鼠标点击被 settings-side-nav / window-drag-strip 拦截；原生当前窗口的返回检查通过。窄窗口安装态尚未复核，这个现象没有在本批修复，不与隐藏侧栏问题混为一项。后续先在该窗口尺寸复现，再处理对应布局。

本批不切换 Runtime authority，不新增主动投递，也不修改生产设置。
