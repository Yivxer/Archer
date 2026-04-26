# Archer — 个人终端 AI 智能体

> 本文档用于向 AI 模型（Claude / ChatGPT / Gemini）征求设计意见、漏洞修复建议和改进方向。

---

## 一、项目定位

Archer 是一个运行在 macOS 终端的个人 AI 智能体，用 Python 实现，基于 REPL（交互式命令行）架构。

核心理念：**持久记忆 + 技能插件 + 个性化人格**，让 AI 像"了解你的老朋友"而非每次从零开始的工具。

目标用户：单人使用，高度个人化，不追求通用部署。

---

## 二、技术架构

```
archer.py            # 主 REPL 循环，命令路由，会话管理
├── core/
│   ├── llm.py       # LLM 调用（OpenAI SDK 兼容，流式 + function calling）
│   ├── context.py   # System prompt 构建（人格 + 记忆 + 模式 + DB记忆）
│   ├── session.py   # 单次会话历史管理，JSON 持久化
│   ├── input.py     # 输入框（prompt_toolkit，多行，Tab补全，历史）
│   ├── compressor.py # 上下文压缩（超限时自动摘要历史）
│   └── file_ref.py  # @路径 语法解析，支持文本/图片/PDF 直接附入消息
├── memory/
│   ├── store.py     # SQLite 记忆 CRUD（save/list/search/update/archive/delete）
│   ├── extract.py   # 对话结束后 LLM 提炼记忆（每 3 轮自动触发）
│   ├── retrieve.py  # 按用户输入语义检索相关记忆注入 System prompt
│   └── session_insights.py # 会话统计报表
└── skills/
    ├── loader.py    # 技能动态加载，转换为 OpenAI tools 格式
    ├── installer.py # 技能安装/卸载（本地路径 or GitHub URL）
    └── *.py         # 各技能实现（见下文）
```

**依赖**：`openai` · `rich` · `prompt_toolkit` · `tomllib`（内置）

**配置**：`archer.toml`（TOML格式），支持多模型、Obsidian vault 路径、记忆库路径等

---

## 三、核心功能

### 3.1 对话与流式输出

- OpenAI SDK 兼容，`base_url` 可指向 DeepSeek / 本地 Ollama 等任意提供商
- 流式输出（`stream=True`）直写 stdout，避免 Rich Live 覆盖问题
- Function calling 多轮循环（最多 10 轮），工具调用时显示进度提示
- 视觉模型支持：消息含图片时自动切换 `vision_model`

### 3.2 记忆系统

```
提炼（extract.py）→ 暂存（_PENDING_MEMORIES）→ 用户确认 → SQLite 存储
```

- **自动提炼**：每 3 轮对话后 LLM 提炼记忆，暂存待用户 `/memory accept/reject` 确认
- **手动管理**：`/memory add / list / search / update / archive / delete`
- **健康检查**：`/memory review` 检测重复（SequenceMatcher ≥0.62）、冲突、过期线索
- **上下文注入**：每次对话前按 query 语义检索相关记忆，注入 System prompt

### 3.3 技能插件系统

每个技能文件暴露：`SKILL` 元数据 dict + `schema()` 返回 OpenAI function schema + `run(args)` 执行

**已内置技能**（18 个）：

| 技能 | 功能 |
|------|------|
| `obsidian_read/write/search` | 读写搜索 Obsidian vault |
| `file_ops` | 本地文件读写（action=read/write/append/list） |
| `shell` | 执行终端命令 |
| `web_fetch` | 抓取网页正文 |
| `rss_reader` | 读取 RSS 订阅 |
| `file_search` | 文件名/内容模糊搜索 |
| `pdf_reader` | PDF 正文提取 |
| `image_ocr` | 图片 OCR |
| `screenshot` | 截图 |
| `weather` | 天气查询 |
| `github_ops` | GitHub 仓库操作 |
| `summarize` | 长文摘要 |
| `humanizer` | 内容人性化改写 |
| `hugo_blog` | Hugo 博客文章管理 |
| `apple_reminders` | Apple 提醒事项 |
| `whisper_transcribe` | 音视频转录（中文优先） |
| `weekly_review` | 周复盘报告生成 |
| `installer` | 技能安装/卸载逻辑 |

技能可通过 `/skill install <本地路径 or GitHub URL>` 热加载，无需重启。

### 3.4 人格与模式

System prompt 分层构建：

```
核心人格摘要（硬编码）
  + 当前模式 prompt（mirror/coach/critic/operator）
  + SOUL.md（用户定义的灵魂档案）
  + MEMORY.md（用户定义的当前状态文件）
  + DB 记忆（SQLite 语义检索结果）
```

模式通过 `/mode <mirror|coach|critic|operator>` 切换，每种模式有独立的 prompt 覆盖层。

### 3.5 其他功能

- **上下文压缩**（`/compact` 或自动）：接近 token 上限时 LLM 摘要历史消息
- **复盘**（`/reflect`）：LLM 分析近期对话，输出洞察/决策/待办/待写入记忆
- **会话统计**（`/sessions [天数]`）：展示历史会话分布
- **Token 追踪**：状态栏显示本次会话累计用量及上限比例
- **@路径 语法**：输入时可引用本地文件/图片，内容直接注入消息
- **历史持久化**：`/save` 或 `/exit` 将会话 JSON 保存至本地

---

## 四、配置结构（archer.toml）

```toml
[api]
base_url     = "https://api.deepseek.com/v1"
api_key      = "sk-xxx"
model        = "deepseek-chat"
vision_model = "deepseek-chat"
models       = ["deepseek-chat", "deepseek-reasoner"]  # 可切换列表

[persona]
name         = "Archer"
soul_path    = "/path/to/SOUL.md"
memory_path  = "/path/to/MEMORY.md"
default_mode = "coach"
current_mode = "coach"

[persona.modes.mirror]
name   = "镜子"
prompt = "..."

[persona.modes.coach]
name   = "教练"
prompt = "..."

[memory]
db_path              = "/path/to/archer.db"
max_context_memories = 5

[context]
token_limit = 1000000

[obsidian]
vault_path = "/path/to/vault"
```

---

## 五、已知问题与设计缺陷（供审查）

### 5.1 架构层面

1. **`call_with_tools` 不支持流式**：function calling 第一步用非流式，等待时无反馈（spinner 未实现）
2. **技能调用结果无长度限制**：大型文件或长网页原文直接传入 messages，可能快速耗尽上下文
3. **记忆提炼阻塞主循环**：`_auto_extract` 在对话后同步调用，增加每 3 轮的等待感
4. **config 在 LLM 层单例缓存**：运行中修改 `archer.toml` 不会生效，需重启

### 5.2 记忆系统

5. **相似度检测是字面匹配**（SequenceMatcher），无语义向量，误报率高
6. **记忆注入用 LIMIT 硬截断**，不按相关性排序（retrieve.py 的 `for_context` 实现较简陋）
7. **待确认记忆存在内存**（`_PENDING_MEMORIES` 全局列表），进程崩溃后丢失

### 5.3 技能系统

8. **技能 `run()` 无超时机制**：长时 shell 命令或网络请求会无限阻塞
9. **技能错误被 `str(result)` 吞掉**：异常栈不传给 LLM，LLM 无法做失败重试判断
10. **`installer.py` 未做沙箱隔离**：从 URL 安装技能直接执行，存在安全风险

### 5.4 用户体验

11. **多行输入和流式输出共用 stdout**，偶尔在某些终端出现光标错位
12. **`/reflect` 输出纯文本，不进入对话历史**，无法追问复盘内容
13. **模式切换不持久化到 toml**，重启后恢复默认模式

---

## 六、待实现方向（欢迎提供优先级建议）

- [ ] 技能调用流式进度反馈（当前只显示 `→ skill_name…`）
- [ ] 记忆语义向量检索（embedding，替代字面匹配）
- [ ] 技能结果长度截断 + 摘要降级策略
- [ ] MCP（Model Context Protocol）协议支持，接入外部 MCP server
- [ ] 多会话切换（目前只有一个活跃 session）
- [ ] 定时触发（周复盘、每日 briefing）
- [ ] 语音输入（whisper_transcribe 已有，但未接入主循环）
- [ ] Web UI（`ui/app.py` Textual TUI 曾尝试后废弃）

---

## 七、文件体积说明

项目代码约 **200KB**，`.venv` Python 虚拟环境约 **852MB**。
分享代码时请排除 `.venv/`：

```bash
zip -r archer_src.zip . -x "*.venv/*" -x "__pycache__/*" -x "*.pyc" -x ".git/*"
```

---

*项目作者：枫弋（Iver Yivxer）· 2026*
