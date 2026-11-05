# archer.toml 配置参考

Archer 的主配置文件位于项目根目录 `archer.toml`（gitignore，不提交）。模板见 `templates/archer.example.toml`。

加载入口：`core/llm._load_config()` / `terminal/api/_config._load_config()`。修改后 CLI 支持热加载（`pop_config_reloaded()`）；Desktop API 路径类字段保存后需重启 API。

---

## `[api]` — LLM 与网络

| 键 | 类型 | 默认值 | 说明 |
|----|------|--------|------|
| `base_url` | string | — | OpenAI 兼容 API 根地址，如 `https://api.deepseek.com/v1` |
| `api_key` | string | — | 服务商密钥 |
| `model` | string | — | 默认聊天模型 |
| `model_auto` | bool | `true` | `true` 时按意图从 `models[]` 自动选型；`/model <名>` 锁定后置 `false` |
| `vision_model` | string | 同 `model` | 带图片附件时使用的模型 |
| `models` | string[] | `[model]` | 候选模型列表；通常 `[0]` 快聊、`[1]` 重推理/工具 |
| `timeout_s` | number | `45` | 单次 LLM 请求超时（秒） |
| `max_retries` | number | `1` | LLM 失败重试次数 |

**示例**

```toml
[api]
base_url     = "https://api.deepseek.com/v1"
api_key      = "sk-..."
model        = "deepseek-chat"
model_auto   = true
vision_model = "deepseek-chat"
models       = ["deepseek-chat", "deepseek-reasoner"]
timeout_s    = 45
max_retries  = 1
```

---

## `[persona]` — 人格、模式、灵魂文件

| 键 | 类型 | 默认值 | 说明 |
|----|------|--------|------|
| `name` | string | `"Archer"` | 显示名 |
| `soul_path` | path | — | `SOUL.md` 路径（长期自我叙事） |
| `soul_profile_path` | path | — | `SOUL_PROFILE.json`（结构化画像） |
| `memory_path` | path | — | `MEMORY.md`（当前状态快照，注入 system prompt） |
| `covenant_path` | path | — | `COVENANT.md`（根约定，不自动改写） |
| `presence_path` | path | — | `PRESENCE.md`（交互风格） |
| `default_mode` | string | `"listener"` | 默认对话姿态 id |
| `current_mode` | string | 同 default | 当前锁定姿态（`/mode` 或 Desktop 切换写入） |
| `mode_auto` | bool | `true` | `true` 时每轮由 orchestrator 选姿态；`false` 时用 `current_mode` |
| `modes_dir` | path | — | 额外 `.md` 模式文件目录（文件名 stem = mode id） |
| `project_root` | path | `cwd` | 项目根；也可用环境变量 `ARCHER_PROJECT_ROOT` |
| `modes.<id>.name` | string | id | TOML 内嵌模式显示名 |
| `modes.<id>.prompt` | string | — | 模式 system 片段 |

**子表 `[persona.history]`**

| 键 | 类型 | 说明 |
|----|------|------|
| `covenant_dir` | path | 约定修订提案历史目录 |
| `presence_dir` | path | presence 变更历史目录 |

**示例**

```toml
[persona]
name          = "Archer"
soul_path     = "~/.archer/SOUL.md"
memory_path   = "~/.archer/MEMORY.md"
covenant_path = "~/.archer/COVENANT.md"
presence_path = "~/.archer/PRESENCE.md"
default_mode  = "coach"
current_mode  = "coach"
mode_auto     = true
modes_dir     = "modes"

[persona.modes.coach]
name   = "Coach"
prompt = "Current mode: coach. Drive toward action."
```

---

## `[experts.<id>]` — 专家档案（Part 6 + 人格层）

专家 id 是表名，例如 `[experts.developer]`。内置 id：`default`、`developer`、`video-coach`、`content-creator`、`counselor`、`parent-educator`。未写进 toml 的内置专家用 `core/experts.py` 的默认值。

人格层是附加字段，不替换 Part 6 功能键。`developer` 与 `counselor` 的试点文案写在内置默认里；其它专家的人格字段默认为空。

| 键 | 层 | 类型 | 说明 |
|----|----|------|------|
| `label` / `note` | Part 6 | string | 名称与短说明。`note` 保持原义，不被 `subtitle` 替换 |
| `model_profile` | Part 6 | string | `lite` / `pro` / `max` |
| `skill_policy` / `skills` | Part 6 | string / string[] | `open` 或 `allowlist` |
| `prompt_overlay` | Part 6 | string | 专家工作台叠层，先于人格注入 |
| `starters` / `memory_tags` | Part 6 | array | 开场与记忆标签 |
| `subtitle` / `icon` / `color` | 档案 | string | 可选标识。`color` 为 `#RRGGBB` |
| `personality_blurb` | 人格 | string | 人格素描，建议 200 字内，上限 400 |
| `voice_markers` / `voice_avoid` | 人格 | string[] | 可用口头禅 / 禁止话术 |
| `emotional_register` / `silence_behavior` | 人格 | string | 情绪区间 / 用户沉默时的偏向 |
| `mission` / `rules` / `workflow` | 人格 | string / string[] / string | 使命、铁律、工作流。本周注入使用铁律；使命与工作流只入档案 |
| `deliverable_signals` | 人格 | string[] | 体验信号。本周只入档案，不进 prompt |
| `default_stance` | 档案 | string | 建议姿态 id。本周只校验并保存，不改全局 mode 选择 |
| `permission_boundary` | 档案 | string | 可选收紧说明。不改审批器 |

禁止在专家表里写 `covenant_path`、`soul_path`、`presence_path` 或 `system_prompt`。根契约只来自 `[persona].covenant_path`。

运行时拼接顺序写死在 `core/agent_profile.py` 的 `PROFILE_PROMPT_ORDER`，由 `core/context.py` 的 `build_system_prompt()` 发出：

`COVENANT → Soul → Expert overlay → Personality injection → Stance → Skill context`

COVENANT 与 Soul 仍在原锚点；后四层在提示词尾部按同一元组顺序拼接。人格注入开头声明它不能覆盖根契约。

---

## `[obsidian]` — 笔记库

| 键 | 类型 | 默认值 | 说明 |
|----|------|--------|------|
| `vault_path` | path | — | Obsidian vault 根目录；空则跳过笔记检索/写入 |

Desktop 聊天可通过 `obsidianMode` 控制注入强度：`off` / `summary` / `full`（见 API 契约）。

**示例**

```toml
[obsidian]
vault_path = "/Users/me/Obsidian/Vault"
```

---

## `[mcp]` — Model Context Protocol

| 键 | 类型 | 默认值 | 说明 |
|----|------|--------|------|
| `enabled` | bool | `false` | 是否启动 MCP 管理器 |
| `schema_policy` | string | `"capability_aware"` | 工具 schema 注入策略 |
| `recent_window_turns` | number | `10` | 最近 N 轮内用过的 MCP 服务仍视为 active |
| `reconnect_attempts` | number | `2` | 远程 MCP 断线重连次数 |

**`[[mcp.servers]]` 每项**

| 键 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `name` | string | 必填 | 服务 id，工具名前缀 |
| `enabled` | bool | `false` | 是否启用该 server；必须显式开启 |
| `transport` | string | `"stdio"` | `stdio` 或 `streamable_http` |
| `command` | string | — | stdio：启动命令 |
| `args` | string[] | `[]` | stdio：命令参数 |
| `env` | map | — | stdio：子进程环境 |
| `url` | string | — | HTTP：MCP 端点 |
| `auth_type` | string | `"none"` | `none` / `bearer` / `header` |
| `auth_token_env` | string | — | 从环境变量读 token |
| `auth_token` | string | — | 内联 token（不推荐提交） |
| `auth_header` | string | `"Authorization"` | header 模式下的头名 |
| `headers` | map | — | 额外 HTTP 头 |
| `reconnect` | bool | `true` | 调用失败时是否重连 |
| `timeout_s` | number | `45` | 连接/调用超时 |
| `permissions.tools` | map | `{}` | skill 白名单及能力：`read` / `write`；未列出的工具不注册也不可执行 |
| `permissions.allowed_domains` | string[] | `[]` | HTTP(S) 目标域名白名单；支持 `*.example.com`，不隐式放行根域名 |

**示例**

```toml
[mcp]
enabled = true
reconnect_attempts = 2

[[mcp.servers]]
name    = "fetch"
enabled = true
command = "uvx"
args    = ["mcp-server-fetch"]
permissions = { tools = { fetch_url = "read" }, allowed_domains = ["example.com"] }

[[mcp.servers]]
name             = "remote"
enabled          = true
transport        = "streamable_http"
url              = "https://mcp.example.com/mcp"
auth_type        = "bearer"
auth_token_env   = "ARCHER_MCP_TOKEN"
permissions      = { tools = { search = "read", publish = "write" }, allowed_domains = ["mcp.example.com"] }
```

`write` 工具即使在白名单中也必须经过显式确认。远程 MCP endpoint 本身也必须命中 `allowed_domains`；省略 server 开关、工具权限或域名均按拒绝处理。

---

## `[hooks]` — 生命周期钩子

| 键 | 类型 | 默认值 | 说明 |
|----|------|--------|------|
| `enabled` | bool | `true` | 全局开关 |

**`[[hooks.<EventName>]]` 每项**（Event：`PreToolUse` / `PostToolUse` / `PreCompact` / `PostCompact` / `SessionStart` / `SessionStop`）

| 键 | 类型 | 说明 |
|----|------|------|
| `type` | string | `python` / `command` / `prompt`（prompt 预留） |
| `handler` | string | python：`module:function` |
| `command` | string | command：shell 命令，stdin 收 JSON context |
| `matcher` | string | 可选，限制工具名 |

Hook 返回 JSON：`continue`（false 阻断）、`tool_input`（PreToolUse 改参）、`message`（提示文案）。详见 `docs/p5-hooks-design.md`。

**示例**

```toml
[hooks]
enabled = true

[[hooks.PreToolUse]]
type    = "python"
handler = "myhooks.audit:prepend_tag"
matcher = "web_search"

[[hooks.SessionStart]]
type    = "command"
command = "echo '{\"continue\": true}'"
```

插件安装的 `hooks.json` 会与 `[hooks]` 合并（见 `docs/p5-plugin-design.md`）。

---

## 其他常用段（简要）

| 段 | 用途 |
|----|------|
| `[memory]` | `db_path`、`max_context_memories`（默认 5） |
| `[runtime.migration_modes]` | Runtime Closure 领域迁移模式。缺失时默认 shadow；`background_job = "authoritative"` 也不能绕过 command gate。 |
| `[runtime.command_migration_modes.background_job.<job_kind>]` | Background Job 命令级 migration mode；create / start / retry / cancel / approve / deny 默认 shadow，只有显式 command authoritative、真实 workflow 可达且 evidence gate 通过时才可能授权。 |
| `[context]` | `token_limit`（默认 1000000，压缩阈值） |
| `[paths]` | `sessions_dir`、`artifacts_dir` |
| `[ui]` | `stream`（CLI 流式输出） |
| `[auth]` | Supabase / Magic Link：`supabase_url`、`supabase_key`、`access_token`、`archer_id` |
| `[account]` | `name`（Desktop `/status` 展示） |
| `[proactive]` | `enabled`（默认 true） |
| `[critique]` | 自动自我批判频率与上限 |
| `[security]` | `shell_risk_scoring`、`strong_confirm` |
| `[tools]` | `max_rounds`（工具循环轮数） |
| `[writing]` | 写作辅助相关开关 |

---

## 相关文档

- 分层 Markdown 合并：`docs/p5-layered-config-design.md`
- MCP 细节：`docs/p5-mcp-integration-design.md`
- Hooks 细节：`docs/p5-hooks-design.md`
