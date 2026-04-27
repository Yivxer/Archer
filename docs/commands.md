# 命令手册

## 对话管理

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有命令 |
| `/status` | 当前模型、模式、Token 用量、活跃项目、灵魂提案 |
| `/mode <mirror\|coach\|critic\|operator>` | 切换对话模式（持久化到 toml） |
| `/model [<name>]` | 查看或切换当前 LLM 模型 |
| `/reflect` | 对当前会话进行结构化复盘（输出 JSON，保留在历史中） |
| `/listen [stop]` | 静默记录模式——保存笔记，不触发 LLM 响应 |
| `/sessions [days]` | 会话历史统计 |
| `/save` | 显式保存当前会话 |
| `/clear` | 清空对话历史（重新开始） |
| `/compact` | 压缩并总结当前历史 |
| `/exit` | 退出 Archer（保存会话，运行后台提取） |

## 记忆系统

| 命令 | 说明 |
|------|------|
| `/memory list` | 列出所有活跃记忆 |
| `/memory search <关键词>` | 混合检索（向量 + 全文） |
| `/memory add <内容>` | 手动添加一条记忆 |
| `/memory pending` | 查看 Archer 提案的待审阅记忆 |
| `/memory accept [ID\|all]` | 接受提案记忆 |
| `/memory reject [ID\|all]` | 拒绝提案记忆 |
| `/memory update <ID> <内容>` | 更新已有记忆 |
| `/memory archive <ID>` | 归档（软删除）一条记忆 |
| `/memory delete <ID>` | 永久删除 |
| `/memory review` | 健康检查——标记重复、冲突、过期条目 |
| `/memory extract` | 手动触发后台提取 |
| `/memory reindex` | 重建向量索引 |

## 灵魂档案系统

| 命令 | 说明 |
|------|------|
| `/soul list` | 查看待处理的 SOUL.md 演化提案 |
| `/soul accept <ID\|all>` | 接受——追加到 SOUL.md |
| `/soul reject <ID\|all>` | 丢弃提案 |
| `/soul view` | 查看近期 SOUL.md 演化历史 |
| `/covenant view` | 查看你的 COVENANT.md |
| `/covenant propose <内容>` | 提议修改根契约（保存到历史，不自动应用） |
| `/presence view` | 查看你的 PRESENCE.md |
| `/presence suggest <内容>` | 建议调整在场方式（保存到历史，不自动应用） |

## 自我批评系统

| 命令 | 说明 |
|------|------|
| `/critique list` | 查看所有批评记录（开放 / 已关闭） |
| `/critique add` | 手动添加一条批评观察（最少 30 个字符） |
| `/critique dismiss <ID>` | 关闭一条批评 |

## 行为主题

| 命令 | 说明 |
|------|------|
| `/themes` | 列出检测到的行为主题 |
| `/themes detect` | 跨记忆运行模式检测 |
| `/themes <ID>` | 查看主题详情及关联记忆 |

## 项目管理

| 命令 | 说明 |
|------|------|
| `/project list` | 列出所有项目 |
| `/project new <名称> [描述]` | 创建项目 |
| `/project use <ID\|名称>` | 设置活跃项目（自动注入上下文） |
| `/project log <ID\|名称> <内容>` | 记录项目事件 |
| `/project status <ID\|名称>` | 查看项目详情 |
| `/project archive <ID\|名称>` | 归档项目 |

## 定时任务

| 命令 | 说明 |
|------|------|
| `/cron list` | 列出计划任务 |
| `/cron add <周期> <任务>` | 添加任务（daily / weekly / monthly / Nh） |
| `/cron del <ID>` | 删除计划任务 |
| `/cron run <ID>` | 立即运行任务 |

## 技能管理

| 命令 | 说明 |
|------|------|
| `/skill list` | 列出已安装技能 |
| `/skill info <名称>` | 技能详情和 Schema |
| `/skill install <路径\|URL>` | 从本地路径或 GitHub URL 安装 |
| `/skill remove <名称>` | 卸载技能 |

## 系统

| 命令 | 说明 |
|------|------|
| `/doctor [--fix]` | 系统健康检查（11 项）；`--fix` 自动修复可修复项 |

## 输入快捷键

| 操作 | 快捷键 |
|------|--------|
| 发送消息 | `Enter` |
| 换行 | `Option+Enter`（macOS） / `Alt+Enter` |
| 附加文件 | `@/path/to/file` 或 `@~/path` |
| 附加带空格路径的文件 | `@"path with spaces"` |
| 命令补全 | 输入 `/` 后按 `Tab` |
| 退出 | `Ctrl+C` |
