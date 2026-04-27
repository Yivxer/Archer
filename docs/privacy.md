# 隐私说明

## 本地优先设计

Archer 的设计原则是：你的个人数据不会离开你的机器，唯一的例外是你主动发起的 LLM API 调用。

**留在本地的数据：**

| 数据 | 位置 |
|------|------|
| 长期记忆 | `~/.archer/archer.db`（SQLite） |
| 灵魂档案 | `~/.archer/SOUL.md` |
| 记忆快照 | `~/.archer/MEMORY.md` |
| 根契约 | `~/.archer/COVENANT.md` |
| 在场方式 | `~/.archer/PRESENCE.md` |
| 会话记录 | `~/.archer/sessions/` |
| 产物文件 | 项目目录下的 `.artifacts/` |
| 配置文件 | `archer.toml`（在项目目录，已在 gitignore 中） |

以上文件均不会传输到任何 Archer 服务器。Archer 没有服务器。

## 什么数据会离开你的机器

**LLM API 调用。** 当你发送消息时，Archer 会发送：

- 你的消息内容
- 对话历史（接近 Token 上限时会压缩）
- 从本地数据库中检索到的相关记忆
- 你的灵魂/记忆/契约/在场方式文件的摘要（仅在与查询相关时）
- 技能 Schema（用于函数调用）

这些数据发送给你在 `archer.toml` 中配置的 LLM API（`api.base_url`），适用于该提供商的隐私政策。

**嵌入向量调用。** 如果安装了 `sentence-transformers`，记忆嵌入向量在**本地**计算——不发起任何 API 调用，模型完全在你的机器上运行。

## Git 安全

以下文件默认在 `.gitignore` 中，绝不会被意外提交：

```
.env
archer.toml
SOUL.md
MEMORY.md
COVENANT.md
PRESENCE.md
*.db
sessions/
.artifacts/
```

如果你 Fork 或参与贡献，你的个人数据不可能被包含在 commit 中。

## 无遥测

Archer 不收集任何使用数据、崩溃报告或统计信息。没有任何内置的追踪机制。

## 第三方技能

从外部来源安装的技能可能会发起自己的网络请求。安装前请查看技能源代码。技能安装流程会在确认前向你展示完整源代码。

## LLM 提供商选择

你选择你的提供商。如果隐私是核心要求：
- 通过 Ollama 运行本地模型（`http://localhost:11434/v1`）
- 选择数据保留政策较强的提供商
- 在将敏感个人数据用于 Archer 之前，先阅读提供商的服务条款
