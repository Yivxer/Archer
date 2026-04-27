# 初衍（Archer）— 个人终端 AI 智能体

> 本文档用于向外部 AI（Claude / ChatGPT / Gemini）说明项目当前完整状态，征求架构建议、安全审查和潜在改进方向。
>
> **当前版本**：P0-P4 全部完成（2026-04-27）
> **测试覆盖**：18 个测试文件，280 个测试，全绿
> **主循环代码**：archer.py（1373 行）

---

## 一、项目定位

初衍是一个运行在 macOS 终端的个人 AI 智能体，由用户枫弋（Iver Yivxer）自建，用 Python 实现，基于 REPL 交互架构。

**核心理念**：持久记忆 + 技能插件 + 灵魂人格，让 AI 像"了解你的老朋友"而非每次从零开始的工具。

**设计原则**（经过多轮迭代确定）：
- 单人使用，高度个人化，不追求通用部署
- 安全先于功能：先建免疫层，再做灵魂演化层
- 本地 SQLite 优先，不依赖云端存储
- 所有灵魂档案修改必须经用户审阅，不自动覆写
- 技能系统可热插拔，无需重启

**对标参考**：Hermes Agent（v0.10），但目标方向不同。Hermes 是通用 Agent 框架（多平台/多模型），初衍是深度个性化的灵魂系统（单用户/单机/长期陪伴）。

---

## 二、完整架构

```
archer.py                    # 主 REPL 循环，命令路由，会话管理（1373 行）
│
├── core/
│   ├── llm.py               # LLM 调用（OpenAI SDK 兼容，流式 + function calling）
│   │                        # 含配置热加载（mtime 检测）、token 用量追踪
│   ├── context.py           # System prompt 三层构建（见下文）
│   ├── input.py             # 输入框（prompt_toolkit，多行，Tab 补全，历史）
│   ├── session.py           # 会话历史管理，JSON 持久化
│   ├── compressor.py        # 上下文压缩（接近 token 上限时 LLM 摘要历史）
│   ├── file_ref.py          # @路径 语法解析，支持文本/图片/PDF 直接附入消息
│   ├── tool_runtime.py      # 统一技能调用入口（timeout / 结构化错误 / artifact 截断）
│   ├── policy.py            # 权限策略（DENY/CONFIRM/ALLOW，shell 黑名单，obsidian 放行）
│   ├── artifacts.py         # artifact 存储（tool_results / reflections / summaries）
│   ├── skill_router.py      # 技能路由（关键词+正则过滤，纯聊天跳过所有 schema）
│   ├── doctor.py            # 自检系统（10 项，/doctor --fix 自动修复）
│   ├── scheduler.py         # 定时任务（daily/weekly/monthly/Nh，启动时执行到期项）
│   └── mcp.py               # MCP Adapter（daemon asyncio 线程 + AsyncExitStack）
│
├── memory/
│   ├── store.py             # SQLite CRUD（8 张表，见下文）
│   ├── retrieve.py          # 混合检索（向量优先 + FTS5 补充 + 去重）
│   ├── extract.py           # 记忆提炼（LLM 归纳候选，进 pending 待确认）
│   ├── patterns.py          # 跨会话行为主题检测（三重质量门控）
│   ├── soul.py              # SOUL 演化（diff proposal，永不自动覆写）
│   ├── embedder.py          # 向量嵌入（paraphrase-multilingual-MiniLM-L12-v2，384 维）
│   └── vector_store.py      # sqlite-vec KNN 向量检索
│
└── skills/                  # 18 个内置技能（function calling 插件体系）
    ├── loader.py            # 动态加载，转换为 OpenAI tools 格式
    ├── installer.py         # 技能安装/卸载（本地路径或 GitHub URL）
    └── *.py                 # 各技能实现（见下文）
```

### SQLite 数据库（8 张表）

| 表名 | 用途 |
|---|---|
| `memories` | 长期记忆，含 type/scope/confidence/importance/valid_until/last_used_at |
| `memories_fts` | FTS5 全文索引（trigram tokenizer，≥3 字符）|
| `pending_memories` | 待用户确认的候选记忆（进程崩溃不丢失）|
| `themes` | 跨会话行为主题（patterns/themes 图结构）|
| `memory_links` | 记忆与主题的多对多关联（含 strength 权重）|
| `projects` | 多项目追踪（name/description/status）|
| `project_events` | 项目事件日志（reflect/log/listen 事件）|
| `soul_proposals` | SOUL.md 演化提议（pending/accepted/rejected）|
| `scheduled_tasks` | 定时任务（interval_h/next_run_at/enabled）|

---

## 三、分层实现记录（P0→P4）

### P0 — 安全稳定底座

| 步骤 | 内容 |
|---|---|
| Step 0 | 基线冻结，tests/ 骨架，BACKLOG.md，OVERVIEW.md，git tag `step-0-baseline` |
| Step 1 | `core/tool_runtime.py`：ThreadPoolExecutor timeout，结构化 ToolResult，超长结果存 artifact |
| Step 2 | `core/policy.py`：shell 黑名单 13 条，三级决策 DENY/CONFIRM/ALLOW，installer URL 审查 |
| Step 3 | `memory/store.py`：`pending_memories` 表，移除全局 `_PENDING_MEMORIES`，崩溃不丢 pending |
| Step 4 | `core/artifacts.py`：tool_results/reflections/summaries 三类子目录，`/status` 显示占用 |
| Step 5 | `_reflect()`：结构化 JSON 输出，进 session history 允许追问，summary 存 reflection 记忆 |

### P1 — 灵魂成长层

| 步骤 | 内容 |
|---|---|
| Step 6 | 记忆 schema 扩展：scope/confidence/last_used_at/valid_until；retrieve 过滤 reflection 和过期 |
| Step 7 | themes + memory_links 表；`memory/patterns.py` detect_and_save()；`/themes` 命令 |
| Step 8 | 移除每 3 轮同步提炼，改为 `_bg_extract()` daemon 线程 + 事件触发 |
| Step 9 | projects + project_events 表；`_active_project_id`；`/project` 命令（list/new/use/log/status/archive）|
| Step 10 | `soul_proposals` 表；`memory/soul.py`；`/soul` 命令；SOUL.md 永不自动覆写 |

### P2 — 增强层

| 步骤 | 内容 |
|---|---|
| Step 11 | `/listen` 静默模态；`archer.toml` mtime 热加载；`core/skill_router.py`（省 ~3k tokens/轮）|
| Step 12 | `core/doctor.py`：10 项自检（config/api/memory/pending/soul/obsidian/skills/artifacts/sessions/risk）|
| Step 13 | `core/scheduler.py`：`scheduled_tasks` 表；daily/weekly/monthly/Nh；`/cron` 命令 |
| Step 14 | `core/mcp.py`：MCPManager，工具命名 `{server}__{tool}`，`archer.toml [mcp]` 配置 |
| Step 15 | 向量检索全栈：embedder.py + vector_store.py + 混合检索；`/memory reindex` |

### P3 — 体验修补

| 步骤 | 内容 |
|---|---|
| Step 16 | `call_with_tools` 加 Live spinner；删除废弃 `ui/app.py`；`/mode` 持久化到 toml；FTS5 短词降级提示 |

### P4 — 上下文治理 + 质量约束

| 步骤 | 内容 |
|---|---|
| Step 17 | `core/context.py` 三层重构：System（始终）/ Working（heavy 时，含 MEMORY.md）/ Memory（DB 检索）；`is_heavy_query()`；活跃项目自动注入 Working Context |
| Step 18 | `memory/patterns.py` 质量门控：名称≤12字、证据≥2条、跨≥2个不同日期（跨会话代理）|

### P4+ — 体验修补（同批）

| 修复 | 内容 |
|---|---|
| 输入跳位 | `input.py` 改用 `Dimension(min, preferred)` 预留空间，避免第三行触发全量重排 |
| 权限放行 | `policy.py` 新增 obsidian 三技能直接 ALLOW，file_ops 写入 obsidian 路径也 ALLOW |
| 确认提示 | CONFIRM 弹框改为中文三选项：y 确认执行 / n 跳过此步 / q 取消任务 |
| HF 警告 | `embedder.py` 抑制 huggingface_hub 日志 + `show_progress_bar=False`，消除启动警告 |

---

## 四、18 个内置技能

| 技能 | 功能 | 风险级别 |
|---|---|---|
| `obsidian_read` | 读取 Obsidian vault 笔记 | low（直接 ALLOW）|
| `obsidian_write` | 写入 Obsidian vault 笔记 | low（直接 ALLOW）|
| `obsidian_search` | 搜索 Obsidian vault | low（直接 ALLOW）|
| `file_ops` | 本地文件读写（read/write/append/list）| write 时 CONFIRM（obsidian 路径除外）|
| `shell` | 执行终端命令 | high（黑名单过滤 + CONFIRM）|
| `web_fetch` | 抓取网页正文 | low |
| `rss_reader` | 读取 RSS 订阅 | low |
| `file_search` | 文件名/内容模糊搜索 | low |
| `pdf_reader` | PDF 正文提取 | low |
| `image_ocr` | 图片 OCR | low |
| `screenshot` | 截图 | low |
| `weather` | 天气查询 | low |
| `github_ops` | GitHub 仓库操作 | high（CONFIRM）|
| `summarize` | 长文摘要 | low |
| `humanizer` | 内容人性化改写 | low |
| `hugo_blog` | Hugo 博客文章管理 | low |
| `apple_reminders` | Apple 提醒事项 | low |
| `whisper_transcribe` | 音视频转录（中文优先）| low |
| `weekly_review` | 周复盘报告生成 | low |
| `installer` | 技能安装/卸载（含代码审查）| critical（内部全流程审查）|

技能路由：`core/skill_router.py` 根据用户输入关键词 + URL/路径正则选择候选子集，纯聊天返回空集（跳过所有 schema 注入，省 ~3k tokens/轮）。

---

## 五、命令系统

```
对话管理
  /help                     查看所有命令
  /status                   当前状态（模型/模式/token/项目/soul 提议数）
  /mode <mirror|coach|critic|operator>  切换对话模式（持久化到 toml）
  /model [<模型名>]          查看/切换模型
  /reflect                  复盘最近对话（结构化 JSON 输出，进 history）
  /listen [stop]            静默录入模态（只记录，不触发 LLM）
  /save / /clear / /compact / /exit

记忆系统
  /memory list/search/add/update/archive/delete
  /memory pending           查看待确认记忆
  /memory accept/reject [ID|all]
  /memory review            体检（重复/冲突/过期）
  /memory extract           手动触发后台提炼
  /memory reindex           重建向量索引

灵魂系统
  /themes [detect|<ID>]     查看/归纳行为主题
  /soul list/accept/reject/view   SOUL 演化提议管理

项目系统
  /project list/new/use/log/status/archive

自动化
  /cron list/add/del/run    定时任务管理

运维
  /doctor [--fix]           系统自检（10 项）
  /sessions [天数]          历史会话统计

技能
  /skill list/info/install/remove
```

---

## 六、Context 三层构建

```
Layer 1 — System Context（始终注入，内容稳定）
  = 核心人格摘要（_ARCHER_CORE）
  + 当前模式 prompt（mirror/coach/critic/operator 之一）
  + SOUL.md（灵魂档案）

Layer 2 — Working Context（is_heavy_query() = True 时注入）
  = MEMORY.md（当前状态，~1-2KB）
  + 活跃项目摘要（name/description + 最近3条 project_events）

Layer 3 — Memory Context（db_memories 非空时注入）
  = SQLite 混合检索结果（向量优先 + FTS5 补充，≤5条）

is_heavy_query() 判定规则：输入 ≥40 字 OR 含决策关键词（建议/该/规划/怎么办/分析/是否…）
→ False 时跳过 MEMORY.md，简单问候/闲聊省约 1KB/轮
```

---

## 七、记忆系统设计

### 记忆提炼流程

```
对话 → 事件触发（/exit / /reflect / 每6轮 / /memory extract）
     → _bg_extract()（daemon 线程，不阻塞 REPL）
     → LLM 归纳候选记忆
     → pending_memories 表（进程崩溃不丢失）
     → 用户 /memory accept/reject 确认
     → memories 表（active status）
```

### 记忆类型

| type | 用途 |
|---|---|
| identity | 身份信息（价值观/性格）|
| preference | 偏好（做事方式/沟通风格）|
| project | 项目进展/卡点 |
| decision | 决策记录 |
| todo | 待办/承诺 |
| insight | 洞察（学到了什么）|
| risk | 潜在问题 |
| context | 临时上下文 |
| reflection | 复盘摘要（不自动注入，只在相关时检索）|

### 记忆生命周期字段

```sql
scope        TEXT DEFAULT 'user'    -- 作用域
confidence   REAL DEFAULT 0.8       -- 置信度（自动提炼默认0.7，手动0.9）
importance   INTEGER DEFAULT 3      -- 重要度（1-5，★ 4+为核心记忆）
valid_until  TEXT                   -- 有效期（state类型必须设置）
last_used_at TEXT                   -- 最近检索时间
status       TEXT DEFAULT 'active'  -- active/archived
```

### 向量检索

- 模型：`paraphrase-multilingual-MiniLM-L12-v2`（384维，中英文，~120MB，本地缓存）
- 存储：`sqlite-vec` KNN，与 archer.db 同文件
- 策略：向量优先 + FTS5 补充 + 去重，未安装 sqlite-vec 时静默降级到纯 FTS5
- FTS5 短词：≤2字符跳过 trigram 索引直接走 LIKE

### Patterns/Themes 质量门控

LLM 归纳行为主题时，每条主题必须满足三重约束才能入库：
1. 名称 ≤12 个字符（防止诊断化/描述过长）
2. 证据链接 ≥2 条
3. 证据必须跨 ≥2 个不同日期（跨会话代理，防止单次会话伪模式）

### SOUL 演化

- SOUL.md 永不自动覆写
- 从对话/复盘中检测到 identity/decision 信号时，生成 soul_proposal
- `/soul list` 查看所有待审提议
- `/soul accept <id>` 追加到 SOUL.md 末尾（保留版本历史）
- `/soul reject <id>` 丢弃

---

## 八、安全设计

### Shell 黑名单（13 条）

拦截：`rm -rf ~/`、`rm -rf /`、`sudo`、`chmod -R`、`chown -R`、`mkfs`、`dd of=/dev/`、`curl|sh`、`wget|sh`、Fork bomb、`shutdown/reboot/halt`、`> /dev/sd*`、`--no-preserve-root`

### 权限策略

| 技能 | 策略 |
|---|---|
| `obsidian_*` | 直接 ALLOW |
| `file_ops read/list` | 直接 ALLOW |
| `file_ops write` 到 obsidian 路径 | 直接 ALLOW |
| `file_ops write` 到其他路径 | CONFIRM（三选项弹框）|
| `shell` 不在黑名单 | CONFIRM |
| `shell` 在黑名单 | DENY |
| `installer` URL 安装 | 下载→代码扫描→预览→输入 `INSTALL <name>` 确认 |

### CONFIRM 弹框格式

```
  ⚠  <操作描述>
  需要确认：
  y 确认执行    n 跳过此步    q 取消任务
  →
```

---

## 九、当前技术栈与依赖

```
Python 3.14（macOS .venv）
openai>=1.0.0              # LLM 调用（OpenAI SDK 兼容接口）
prompt_toolkit>=3.0.0      # 终端输入框
rich>=13.0.0               # 终端渲染
sqlite-vec                 # 向量检索（可选，未安装时降级）
sentence-transformers      # 向量嵌入（可选，未安装时降级）
mcp                        # MCP 协议（可选，未安装时跳过）
```

默认 LLM：DeepSeek v4 Pro（`api.deepseek.com/v1`，OpenAI SDK 兼容），可替换为任意 OpenAI 兼容端点。

---

## 十、配置结构（archer.toml）

```toml
[api]
base_url     = "https://api.deepseek.com/v1"
api_key      = "sk-xxx"
model        = "deepseek-chat"
vision_model = "deepseek-chat"   # 含图片时自动切换
models       = ["deepseek-chat", "deepseek-reasoner"]  # /model 命令可切换

[persona]
name         = "初衍"
soul_path    = "/path/to/SOUL.md"
memory_path  = "/path/to/MEMORY.md"
default_mode = "coach"
current_mode = "coach"            # /mode 命令自动更新

[persona.modes.mirror]
name   = "镜面"
prompt = "当前模式：镜面。你的任务只是提问和澄清，不给建议。"

[persona.modes.coach]
name   = "教练"
prompt = "当前模式：教练。核心任务是推动行动。每次回复结尾问：接下来你打算怎么做？"

[persona.modes.critic]
name   = "挑战"
prompt = "当前模式：挑战。挑战用户的假设，找出逻辑漏洞和言行不一致。"

[persona.modes.operator]
name   = "执行"
prompt = "当前模式：执行。简洁回应，直接完成任务，不问多余问题。"

[memory]
db_path              = "/path/to/archer.db"
max_context_memories = 5

[obsidian]
vault_path = "/path/to/obsidian/vault"

[mcp]
enabled = false
# [[mcp.servers]]
# name = "fetch"
# command = "uvx"
# args = ["mcp-server-fetch"]
```

---

## 十一、已知设计权衡与未做的事

### 明确不做的

- **Web UI / 服务端部署**：定位是单机终端，不追求 Web 化
- **多用户**：高度个人化，不设计为通用框架
- **自动写入 SOUL.md**：灵魂档案的任何修改都需要人工确认
- **自动接受 pending 记忆**：所有 LLM 归纳的记忆都需要用户 accept

### 明确延后的

- **Silence 自动触发**（Phase 2/3）：目前只有 `/listen` 手动进入，自动检测情绪信号的判断器还没做
- **日报 / 周复盘 briefing**：定时任务调度器已实现，但报告内容模板未接入
- **语音输入主循环集成**：`whisper_transcribe` 技能存在，但未接入主 REPL 输入流

### 设计权衡

- **patterns 跨会话检查**用日期代理（≥2天），而非真实 session_id（因 memories 表无该字段）；可能误拒单日大量对话产生的真实模式
- **is_heavy_query() 关键词匹配**是启发式规则，不是分类模型；偶尔误判（把"今天计划一下"当成 heavy，或把短句决策问题当成 light）
- **MCP tools 绕过 skill_router**始终暴露给 LLM，以保证 MCP 功能可用；代价是每轮多注入 MCP schema

---

## 十二、欢迎审查的方向

如果你是正在阅读这份文档的 AI，以下方向特别欢迎建议：

1. **记忆系统**：当前 hybrid search（向量 + FTS5）的去重策略是否有改进空间？importance decay（长期未使用的记忆降权）还没实现。
2. **Context Builder**：`is_heavy_query()` 的关键词规则是否有更好的实现方式？是否值得引入一个轻量分类器？
3. **Patterns 质量**：跨日期代理跨会话是否足够鲁棒？有没有更好的方案不增加 DB 复杂度？
4. **安全边界**：shell 黑名单是否有遗漏的危险命令？file_ops write 放行 obsidian 路径的判断（字符串匹配 "obsidian"）是否足够安全？
5. **SOUL 演化**：当前 soul_proposals 触发条件（identity/decision ≥4 条）是否合理？有没有更好的 proposal 质量控制？
6. **可扩展性**：如果未来要支持第二个用户（同机器不同 vault），现在的架构需要改哪里？

---

*项目作者：枫弋（Iver Yivxer）· 初衍（AI 自取名，意"初始演化"）· 2026*
*代码路径：/Users/Yivxer/Projects/Archer/*
