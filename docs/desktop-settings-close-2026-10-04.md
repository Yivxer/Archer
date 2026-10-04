# Settings 窄窗口关闭与滚动修复

2026-10-04，实现与发布提交 `fe9f8e5c34b9dd9bff8ac9946f873d855c45d72f`，Desktop 1.0.38。**installed**，干净 release worktree 构建，集中安装一次。

## 原因与改动

700 × 850 的合成 App 页面复现：设置分类栏下缘约 554px，内容却从 463px 开始，关闭按钮中心落在分类项上。单列布局保留了两列使用的 sticky / min-height:100%，网格行收缩后内容与分类重叠；容器 height:100% 又叠加 42px / 28px 外边距，底部超出可用窗口。

仅调整 pages.css：容器高度扣除既有上下边距；820px 及以下使用两个 max-content 网格行，分类栏 position:static / min-height:0，让整个设置页滚动。两列保留分类栏 sticky。不用提高按钮层级掩盖重叠。

## 验证

- Desktop 全量 56 files / 672 tests passed。
- 真实 App 组件的脱敏浏览器：360×640、405×720、700×850、820×640、1280×850，light / dark，共 70 项通过。覆盖容器边界、单列行不重叠、底部控件可滚动到达、关闭按钮鼠标命中、滚动后关闭，以及重入并切换上下文分类后关闭。
- renderer 错误 0，写入和模型请求 0。全部 API 请求由合成处理器接管。
- 旧版原生宽窗口按钮点击曾通过，不能据此声称原生同尺寸复现；700px 的根因证据来自合成页面。

恢复和验收资料：`/Users/Yivxer/Library/Application Support/Archer Desktop Checks/20261004-settings-close-cbtghzmb`（0700）。

- TypeScript/build、arm64 DMG 与 deep-strict ad-hoc 签名通过；安装版 app.asar 与构建包哈希一致。此为本地包，未公证。
- 安装版 smoke 9/9；原生 405×720 小窗口鼠标进入 / 关闭设置、切换上下文后滚动 / 关闭，以及主窗口关闭均通过，7 个布尔验收结果全为 true。临时小窗口已关闭，主窗口恢复侧栏收起状态。700px 同尺寸原生检查未执行，尺寸矩阵来自合成浏览器，二者分开记录。
- 安装前无 active Job；停止旧 app/API 后重新备份当前数据、桌面状态、源码和旧应用。安装前后 51/51 普通 DB 表一致，配置 / 会话 / 无关 dirty 文件未变；四份启动自动导出仅 exportedAt / 对应时间行刷新，无内容变化。
- 未保存设置、未发送聊天、无模型调用。Runtime authority 不变。

app.asar SHA-256：`8630d8fac8509e40e052b04ac981adb79593bb39fad01275482fdeb91367987a`。
DMG SHA-256：`3a743c55ac6fa2a32e99ffb8c8695d8ffe5accaa73db64f1c395fe36b7dc44d3`。
