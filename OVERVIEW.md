# 初衍（Archer）— 个人终端 AI 智能体

> 本文档用于向外部 AI（Claude / ChatGPT / Gemini）说明项目当前完整状态，征求架构建议、安全审查和潜在改进方向。
>
> **当前版本**：v1.2 稳定在场版（2026-04-27，git commit: 2a33c1d）
> **测试覆盖**：22 个测试文件，339 个测试，全绿
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
- v1.2 新增：克制扩张，边界优先——不新增功能直到已有功能稳定

**对标参考**：Hermes Agent（v0.10），但目标方向不同。Hermes 是通用 Agent 框架（多平台/多模型），初衍是深度个性化的灵魂系统（单用户/单机/长期陪伴）。

---

## 二、完整架构

```
archer.py                    # 主 REPL 循环，命令路由，会话管理（1373 行）
│
├── COVENANT.md              # 根契约（v1.2）：我不会/会做的事，不可自动修改
├── PRESENCE.md              # 在场方式（v1.2）：回应基调/节奏，只 suggest 不自动更新
│
├── core/
│   ├── llm.py               # LLM 调用（OpenAI SDK 兼容，流式 + function calling）
│   │                        # 含配置热加载（mtime 检测）、token 用量追踪
│   ├── context.py           # System prompt 8 层构建（v1.2，见下文）
│   │                        # classify_query_intent()，SOUL 按需注入
│   ├── input.py             # 输入框（prompt_toolkit，多行，Tab 补全，历史）
│   ├── session.py           # 会话历史管理，JSON 持久化
│   ├── compressor.py        # 上下文压缩（接近 token 上限时 LLM 摘要历史）
│   ├── file_ref.py          # @路径 语法解析，支持文本/图片/PDF 直接附入消息
│   ├── tool_runtime.py      # 统一技能调用入口（timeout / 结构化错误 / artifact 截断）
│   ├── policy.py            # 权限策略（v1.2：DENY/STRONG_CONFIRM/CONFIRM/ALLOW）
│   │                        # shell 四级风险评分；is_inside_vault() 路径安全
│   ├── artifacts.py         # artifact 存储（tool_results / reflections / summaries）
│   ├── skill_router.py      # 技能路由（关键词+正则过滤，纯聊天跳过所有 schema）
│   ├── doctor.py            # 自检系统（10 项 + path_safety_check，/doctor --fix 自动修复）
│   ├── scheduler.py         # 定时任务（daily/weekly/monthly/Nh，启动时执行到期项）
│   └── mcp.py               # MCP Adapter（daemon asyncio 线程 + AsyncExitStack）
│
├── memory/
│   ├── store.py             # SQLite CRUD（10 张表，含 session_id，见下文）
│   ├── retrieve.py          # 混合检索（向量优先 + FTS5 补充 + 去重）
│   ├── extract.py           # 记忆提炼（LLM 归纳候选，进 pending 待确认）
│   ├── patterns.py          # 跨会话行为主题检测（v1.2：session_id + date 双重门控）
│   ├── soul.py              # SOUL 演化（diff proposal，永不自动覆写）
│   ├── critique.py          # 自我批评（v1.2）：self_critiques 表，user_signal 限流
│   ├── embedder.py          # 向量嵌入（paraphrase-multilingual-MiniLM-L12-v2，384 维）
│   └── vector_store.py      # sqlite-vec KNN 向量检索
│
└── skills/                  # 18 个内置技能（function calling 插件体系）
    ├── loader.py            # 动态加载，转换为 OpenAI tools 格式
    ├── installer.py         # 技能安装/卸载（本地路径或 GitHub URL）
    └── *.py                 # 各技能实现（见下文）
```

### SQLite 数据库（10 张表）

| 表名 | 用途 |
|---|---|
| `memories` | 长期记忆，含 type/scope/confidence/importance/valid_until/last_used_at/session_id |
| `memories_fts` | FTS5 全文索引（trigram tokenizer，≥3 字符）|
| `pending_memories` | 待用户确认的候选记忆（进程崩溃不丢失）|
| `themes` | 跨会话行为主题（patterns/themes 图结构）|
| `memory_links` | 记忆与主题的多对多关联（含 strength 权重）|
| `projects` | 多项目追踪（name/description/status）|
| `project_events` | 项目事件日志（reflect/log/listen 事件，含 session_id）|
| `soul_proposals` | SOUL.md 演化提议（pending/accepted/rejected，含 session_id）|
| `scheduled_tasks` | 定时任务（interval_h/next_run_at/enabled）|
| `self_critiques` | 自我批评记录（v1.2）：observation/evidence_json/scope/status |

---

## 三、分层实现记录（P0→P4 + v1.2）

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

### v1.2 — 稳定在场版（2026-04-27）

| Phase | 内容 |
|---|---|
| Phase 0 — 安全热修 | `is_inside_vault()` 路径验证（resolve+relative_to，修复字符串绕过）；shell 四级风险评分（low/medium/high/critical）；STRONG_CONFIRM 新决策级别；`doctor.py` 新增 `path_safety_check` |
| Phase 1 — 灵魂三层 | 新建 `COVENANT.md`（根契约，不可自动修改）、`PRESENCE.md`（在场方式，只 suggest）；`context.py` 重构为 8 层注入；`classify_query_intent()` 替换 `is_heavy_query()`（向后兼容）；SOUL 按 intent 按需注入；`archer.py` 新增 `/covenant`、`/presence`、`/critique` 命令组 |
| Phase 2 — 自我批评 | `memory/critique.py`：`self_critiques` 表 + CRUD + user_signal 限流；observation 最低 30 字；scope=skill_router_hint 仅建议不写文件；weekly_critique 默认关闭 |
| Phase 3 — 记忆质量 | `memories/project_events/soul_proposals` 新增 `session_id` 列；`generate_session_id()`（YYYYMMDD-HHMMSS-uuid8）；`run_importance_decay()`（context/todo/risk 按期衰减，identity/decision 不衰减，floor=1）；patterns 升级为 session_id+date 双重门控 |
| Phase 4 — MCP 注入 | `_should_inject_mcp()`：recent_use OR server_name_match OR capability_keyword_match 三条件策略，避免每轮暴露所有 schema |

---

## 四、18 个内置技能

| 技能 | 功能 | 风险级别 |
|---|---|---|
| `obsidian_read` | 读取 Obsidian vault 笔记 | low（直接 ALLOW）|
| `obsidian_write` | 写入 Obsidian vault 笔记 | low（直接 ALLOW，is_inside_vault 验证）|
| `obsidian_search` | 搜索 Obsidian vault | low（直接 ALLOW）|
| `file_ops` | 本地文件读写（read/write/append/list）| write 时 CONFIRM（obsidian 路径用 is_inside_vault 放行）|
| `shell` | 执行终端命令 | 四级评分：low→ALLOW / medium/high→CONFIRM / critical→DENY |
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
  /covenant view/propose    查看根契约 / 提交修改建议（v1.2）
  /presence view/suggest    查看在场方式 / 提交调整建议（v1.2）

自我批评系统（v1.2）
  /critique list            查看所有批评记录（open/dismissed）
  /critique add             手动新建一条批评（需 ≥30 字 observation）
  /critique dismiss <ID>    驳回某条批评

项目系统
  /project list/new/use/log/status/archive

自动化
  /cron list/add/del/run    定时任务管理

运维
  /doctor [--fix]           系统自检（11 项，含 path_safety_check）
  /sessions [天数]          历史会话统计

技能
  /skill list/info/install/remove
```

---

## 六、Context 8 层构建（v1.2）

```
Layer 0 — Runtime Safety（始终注入，最高优先级）
  = 安全边界硬约束（不可被后续 prompt 覆盖）

Layer 1 — 根契约摘要（COVENANT.md 存在时注入）
  = "我不会做的事" + "我会做的事"（节选核心条目）

Layer 2 — 在场方式摘要（PRESENCE.md 存在时注入）
  = 默认基调 + 回应节奏（前两个 section）

Layer 3 — 对话模式（始终）
  = mirror / coach / critic / operator prompt

Layer 4 — 灵魂档案（SOUL.md，仅 decision/emotional/reflection 意图注入）
  = 完整 SOUL.md 内容（identity/preference/growth 档案）

Layer 5 — Working Context（classify_query_intent().needs_memory = True 时注入）
  = MEMORY.md（当前状态，~1-2KB）
  + 活跃项目摘要（name/description + 最近3条 project_events）

Layer 6 — 项目上下文（有活跃项目时注入）
  = 项目名称/描述/最近事件

Layer 7 — Memory Context（DB 检索结果非空时注入）
  = SQLite 混合检索结果（向量优先 + FTS5 补充，≤5条）

意图分类（classify_query_intent）：
  chat       → 仅 Layer 0-3（不注入 SOUL / MEMORY.md）
  task       → Layer 0-3 + 5-7（需记忆，不注入 SOUL）
  project    → Layer 0-3 + 5-7（需记忆，不注入 SOUL）
  decision   → Layer 0-7（完整注入，含 SOUL）
  emotional  → Layer 0-7（完整注入，含 SOUL）
  reflection → Layer 0-7（完整注入，含 SOUL）
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
     → memories 表（active status，含 session_id）
```

### 记忆类型

| type | 用途 | Decay 策略 |
|---|---|---|
| identity | 身份信息（价值观/性格）| 不衰减 |
| preference | 偏好（做事方式/沟通风格）| 不衰减 |
| decision | 决策记录 | 不衰减 |
| project | 项目进展/卡点 | 60 天未用则降权 |
| todo | 待办/承诺 | 60 天未用则降权 |
| insight | 洞察（学到了什么）| 不衰减 |
| risk | 潜在问题 | 60 天未用则降权 |
| context | 临时上下文 | 30 天未用则降权 |
| reflection | 复盘摘要（不自动注入，只在相关时检索）| 30 天未用则降权 |

Decay：`run_importance_decay()` 每次衰减 -1，floor=1，identity/decision/preference 免疫。

### 记忆生命周期字段

```sql
scope        TEXT DEFAULT 'user'    -- 作用域
confidence   REAL DEFAULT 0.8       -- 置信度（自动提炼默认0.7，手动0.9）
importance   INTEGER DEFAULT 3      -- 重要度（1-5，★ 4+为核心记忆）
valid_until  TEXT                   -- 有效期（state类型必须设置）
last_used_at TEXT                   -- 最近检索时间（decay 基准）
session_id   TEXT                   -- 会话标识（YYYYMMDD-HHMMSS-uuid8）
status       TEXT DEFAULT 'active'  -- active/archived
```

### 向量检索

- 模型：`paraphrase-multilingual-MiniLM-L12-v2`（384维，中英文，~120MB，本地缓存）
- 存储：`sqlite-vec` KNN，与 archer.db 同文件
- 策略：向量优先 + FTS5 补充 + 去重，未安装 sqlite-vec 时静默降级到纯 FTS5
- FTS5 短词：≤2字符跳过 trigram 索引直接走 LIKE

### Patterns/Themes 质量门控（v1.2 升级）

LLM 归纳行为主题时，每条主题必须满足三重约束才能入库：
1. 名称 ≤12 个字符（防止诊断化/描述过长）
2. 证据链接 ≥2 条
3. **跨 session 门控（v1.2）**：若 ≥2 个不同 session_id → 通过；若无 session_id（旧数据）→ 降级到跨≥2日期

### SOUL 演化

- SOUL.md 永不自动覆写
- 从对话/复盘中检测到 identity/decision 信号时，生成 soul_proposal（含 session_id）
- `/soul list` 查看所有待审提议
- `/soul accept <id>` 追加到 SOUL.md 末尾（保留版本历史）
- `/soul reject <id>` 丢弃

### 自我批评系统（v1.2 新增）

- `memory/critique.py`：`self_critiques` 表存储结构化批评记录
- 字段：title / observation（≥30字）/ evidence_json / scope / source / status
- 触发：用户 `/critique add` 手动，或 `try_create_from_user_signal()` 自动检测负向反馈
- 限流：同一 session 最多 1 条 user_signal；同类型 24h 冷却
- scope=`skill_router_hint`：仅生成建议，不自动写文件
- weekly_critique 默认关闭（可在 `archer.toml` 启用）

---

## 八、安全设计（v1.2 升级）

### Shell 四级风险评分

| 风险级别 | 处理 | 典型命令 |
|---|---|---|
| critical | DENY（直接拒绝）| `sudo rm -rf /`、`dd of=/dev/`、Fork bomb、`curl\|sh` |
| high | STRONG_CONFIRM（需明确确认+理由）| `sudo`、`shutdown`、`osascript`、`launchctl`、写 shell 配置、递归 rm |
| medium | CONFIRM | 大多数有副作用的命令 |
| low | ALLOW | `git status`、`ls`、`cat`、只读命令 |

`score_shell_risk(command)` 返回 `(risk_level, reason)` 元组，供 `check()` 消费。

### 路径安全

`is_inside_vault(child, vault_path)` 使用 `Path.resolve() + relative_to()` 验证路径真正在 vault 内，防止：
- 字符串绕过（如路径包含 "obsidian" 但实际在外部）
- `../` 路径穿越
- 符号链接跳出

### 权限策略

| 技能 | 策略 |
|---|---|
| `obsidian_*` | 直接 ALLOW |
| `file_ops read/list` | 直接 ALLOW |
| `file_ops write` 到 vault 内（is_inside_vault 验证）| 直接 ALLOW |
| `file_ops write` 到其他路径 | CONFIRM（三选项弹框）|
| `shell` low risk | ALLOW |
| `shell` medium/high risk | CONFIRM / STRONG_CONFIRM |
| `shell` critical | DENY |
| `installer` URL 安装 | 下载→代码扫描→预览→输入 `INSTALL <name>` 确认 |

### CONFIRM / STRONG_CONFIRM 弹框格式

```
# CONFIRM
  ⚠  <操作描述>
  需要确认：
  y 确认执行    n 跳过此步    q 取消任务
  →

# STRONG_CONFIRM（high risk shell）
  🔴  <操作描述>（高风险）
  风险：<reason>
  请说明执行原因，然后输入 YES 确认：
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
covenant_path = "/path/to/COVENANT.md"    # v1.2
presence_path = "/path/to/PRESENCE.md"    # v1.2
default_mode = "coach"
current_mode = "coach"            # /mode 命令自动更新

[persona.history]
covenant_dir  = "/path/to/covenant_history/"   # v1.2 提议版本存档
presence_dir  = "/path/to/presence_history/"   # v1.2 调整历史

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

[critique]                                  # v1.2
weekly_enabled             = false          # 周度自我批评，默认关闭
user_signal_cooldown_h     = 24             # 同类型批评最短间隔（小时）
max_user_signal_per_session = 1             # 每 session 最多触发 1 条

[security]                                  # v1.2
shell_risk_scoring = true                   # 启用四级风险评分
strong_confirm     = true                   # 启用 STRONG_CONFIRM

[mcp]
enabled        = false
schema_policy  = "capability_aware"         # v1.2：按需注入而非全量
recent_window_turns = 10                    # 多少轮内用过视为 recent
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
- **自动写入 COVENANT.md / PRESENCE.md**：根契约和在场方式同样需要人工审阅
- **自动接受 pending 记忆**：所有 LLM 归纳的记忆都需要用户 accept
- **自动应用 self_critiques**：批评记录只观察，不自动修改代码或行为

### 明确延后的（v1.2.1）

- **workflows 层**：voice_to_journal / url_to_reading_note / weekly_digest / project_briefing
- **日报 / 周复盘 briefing**：定时任务调度器已实现，但报告内容模板未接入
- **语音输入主循环集成**：`whisper_transcribe` 技能存在，但未接入主 REPL 输入流

### 更远期（v1.3）

- 完整 `/evolve` 命令
- router_hint_proposals（基于 self_critiques 的路由建议）
- memory usage feedback（记忆检索质量回馈）
- MCP policy 全量接入 capability registry
- capabilities.yaml 基础版

### 设计权衡

- **classify_query_intent() 关键词匹配**是启发式规则，不是分类模型；偶尔误判边界案例（如含决策词的聊天、不含明显关键词的深度问题）
- **MCP 三条件注入**（recent/server_name/capability_keyword）减少了 token 浪费，但可能导致用户首次提及某 MCP 工具时，工具 schema 未注入、LLM 无法调用
- **self_critiques 观察来源**目前主要靠手动 + user_signal 自动触发，LLM 主动生成批评（weekly）默认关闭，实际使用量有限
- **importance decay 阈值**（context:30d / todo/risk:60d）是经验值，实际使用可能需要调整

---

## 十二、欢迎审查的方向

如果你是正在阅读这份文档的 AI，以下方向特别欢迎建议：

1. **记忆系统**：当前 hybrid search（向量 + FTS5）的去重策略是否有改进空间？importance decay 的衰减速率（30/60天）是否合理？
2. **Context Builder**：`classify_query_intent()` 的多关键词分类是否有更好的实现方式？emotional 优先于 decision 的规则在哪些场景下会误触发？
3. **Patterns 质量**：session_id+date 双重门控相比纯日期代理有什么新的边界情况需要注意？
4. **安全边界**：`score_shell_risk()` 的四级分类是否有遗漏的危险命令？STRONG_CONFIRM 弹框的交互设计是否足够清晰？
5. **SOUL 演化**：COVENANT.md 和 PRESENCE.md 的 propose/suggest 流程（目前只进 history，不自动 diff apply）是否合理？
6. **自我批评**：`self_critiques` 的 scope 机制（skill_router_hint 仅建议不写文件）如何扩展到更多 scope 类型？
7. **MCP 注入策略**：三条件策略的假阴性（首次提及时 schema 未注入）如何优雅处理？

---

*项目作者：枫弋（Iver Yivxer）· 初衍（AI 自取名，意"初始演化"）· 2026*
*代码路径：/Users/Yivxer/Projects/Archer/*
