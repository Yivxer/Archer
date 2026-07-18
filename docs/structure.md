# Archer 整体结构说明

> 更新日期：2026-07-17
> 当前定位：一个项目根目录内维护三个使用端口：终端端、桌面客户端、网页端；同时以 Runtime Foundation 作为稳定性地基，统一承接本地 API、工具执行、权限审计、Trace 诊断、幂等和后台任务。Part 10（架构治理）已完成 Wave 1-4，god file 拆分收口，Desktop API 按 domain 模块化。

## 一句话结构

```text
/Users/Yivxer/Projects/Archer/
├── terminal/              # 终端入口与 Desktop 本地 FastAPI 服务
│   └── api/               # Desktop API 路由、工具桥、配置与安全层
├── client/desktop/        # macOS 桌面客户端 Electron + React
│   └── src/agent/         # Desktop AgentEvent、Trace、Job、Approval 类型与聚合逻辑
├── web/                   # 官网/网页端静态站点
├── core/                  # 三端共用的核心能力与 Runtime Foundation
├── memory/                # 长期记忆、项目、任务、反馈等 SQLite 逻辑
├── knowledge/             # Vault focus、Obsidian 观察与知识上下文辅助
├── integrations/          # Obsidian 等外部应用/资料源集成
├── skills/                # 终端/客户端可调用的工具技能
├── workflows/             # 可复用工作流
├── modes/                 # 终端对话模式提示词
├── templates/             # 初始化模板
├── docs/                  # 工程说明文档
└── tests/                 # Python 自动化测试
```

根目录不是单一端口目录，而是 Archer 的总工作区。三个端口分别放在 `terminal/`、`client/desktop/`、`web/`，共享模块继续放在根目录的 `core/ memory/ knowledge/ integrations/ skills/ workflows/`。

## 三个端口

| 端口 | 当前目录 | 主要用途 | 主要入口 |
|---|---|---|---|
| 终端端 | `/Users/Yivxer/Projects/Archer/terminal/` | 终端对话、记忆、技能、工作流、项目管理 | `terminal/archer.py` |
| Desktop 本地 API | `/Users/Yivxer/Projects/Archer/terminal/api/` | 给桌面客户端提供 FastAPI runtime、配置、工具、诊断接口 | `terminal/api/fastapi_app.py` |
| 客户端 | `/Users/Yivxer/Projects/Archer/client/desktop/` | macOS 桌面客户端，调用本地 API | `client/desktop/src/main/index.ts` |
| 网页端 | `/Users/Yivxer/Projects/Archer/web/` | 官网、登录页、Soul 建档入口、静态部署 | `web/public/*.html` + `web/deploy.sh` |

根目录保留兼容入口：

```text
/Users/Yivxer/Projects/Archer/archer.py
/Users/Yivxer/Projects/Archer/archer_api.py
```

它们只是转发到真实实现。后续改终端主流程优先看 `terminal/archer.py`，改 Desktop 本地 API 优先看 `terminal/api/`。

## 终端端状态

终端端是真正的 Archer 核心体验。

主要文件：

```text
terminal/archer.py        # 终端 REPL 主入口，处理 /memory /project /skill /work 等命令
terminal/archer_api.py    # 兼容入口/旧入口，不再作为 Desktop API 的主要演进位置
archer.toml               # 本地配置，含模型、路径、账号、MCP、权限等
COVENANT.md               # 根契约，运行时会读取
PRESENCE.md               # 当前在场方式，运行时会读取
```

启动终端：

```bash
cd /Users/Yivxer/Projects/Archer
.venv/bin/python terminal/archer.py
```

或使用根目录兼容入口：

```bash
.venv/bin/python archer.py
```

不要把 `COVENANT.md`、`PRESENCE.md` 当普通说明文档删除。当前 `archer.toml` 的 persona 配置会读取它们。

## Desktop 本地 API 状态

桌面客户端现在主要通过 FastAPI runtime 连接 Archer 能力层。Part 10 Wave 1-2 把原本两个 god file（`_routes.py` 913 行、`_tools.py` 3368 行）按 domain 拆分到独立模块，`_routes.py` / `_tools.py` 退化为 facade，通过 re-export 保持向后兼容。

主要文件：

```text
terminal/api/fastapi_app.py           # FastAPI app 入口，供 Electron 启动
terminal/api/_routes.py               # facade：re-export 各 domain 模块公开函数（593 行）
terminal/api/_tools.py                # facade：re-export 工具执行 helper（756 行）
terminal/api/_config.py               # 配置、tool approval audit、客户端状态缓存
terminal/api/_security.py             # token 校验、限流、安全辅助
terminal/api/contract.py              # CONTRACT_VERSION + versioned_payload
terminal/api/turn_context.py          # TurnContext + file_refs/memory_mode/obsidian_mode 清洗

# Domain routes（每个独立模块承担一组路由的实现）
terminal/api/session_routes.py        # sessions / threads / append_session / save_session（含 per-session-id 锁）
terminal/api/job_routes.py            # 后台 job lifecycle（_run_job / _run_job_chat_with_tools / trace_id 绑定）
terminal/api/job_enrichment.py        # 后台 job memory/web_search/web_fetch 上下文增强
terminal/api/tool_approval_routes.py  # tool approval 流程（_tool_approval / _run_approved_draft / outbox）
terminal/api/tool_stage.py            # tool stage 共享状态
terminal/api/memory_routes.py         # memory / hypotheses / vault_reflection / sensors
terminal/api/profile_routes.py        # settings / profiles / skills / soul
terminal/api/initiative_routes.py     # Part 8 shadow initiative 路由

# Tool execution helpers（从 _tools.py 抽出）
terminal/api/api_tool_helpers.py      # _is_dangerous_shell / _execute_shell_command / _obsidian_write_draft 等 11 个安全敏感 helper
terminal/api/hugo_workflow.py         # Hugo 发布/删除工作流 helper
terminal/api/desktop_tool_execution.py # _run_desktop_tool_loop / _iter_*_events / _append_obsidian_draft
```

facade 边界由 `tests/test_architecture_boundaries.py` 守门，每个 domain 模块对应一个 `test_*_live_behind_routes_facade` 测试，确保 `_routes.py` / `_tools.py` 只 re-export 不直接定义 domain 函数。god file 行数由 `GOD_FILE_LINE_BASELINE` 监控，超基线即测试失败。

关键接口：

```text
/health               # 轻量存活检查
/ready                # Desktop 启动 readiness 检查
/status               # 本地 API 状态，仍需 token，但不走普通请求限流
/config/doctor        # 配置诊断
/tool-approval-audit  # 工具审批/权限审计
/chat/stream          # 聊天流
/settings             # 当前设置与 active profile
/settings/profile/switch # 模型 profile 切换
```

当前稳定性约定：

1. `/health`、`/ready`、`/status` 是自检路径，不能被普通聊天限流误伤。
2. 模型切换后必须读回 `/settings` 确认实际 active profile，避免前端只做表面切换。
3. 现阶段默认以 `lite` / DeepSeek profile 作为稳定性测试基线；Kimi、GLM 等多模型切换先作为后续压力项，不作为当前地基验收前提。

## 客户端状态

客户端是 Electron + React 桌面应用。它本身不重新实现记忆和技能，而是通过本地 API 连接终端能力层。

主要文件：

```text
client/desktop/package.json                    # 客户端脚本、依赖、打包配置
client/desktop/src/main/index.ts               # Electron 主进程，负责启动窗口和 API 进程
client/desktop/src/main/apiProcess.ts          # API 子进程、ready 探测、重启与错误处理
client/desktop/src/preload/                    # Electron preload
client/desktop/src/renderer/                   # React UI
client/desktop/src/renderer/src/adapters/      # localArcher bridge、EventLog 适配
client/desktop/src/agent/                      # AgentEvent、Trace、Approval、Job 类型与聚合逻辑
client/desktop/resources/                      # App 图标等资源
client/desktop/out/                            # 构建产物，可再生成
client/desktop/release/                        # DMG/App 安装包，可再生成
```

常用命令：

```bash
cd /Users/Yivxer/Projects/Archer/client/desktop
npm run dev
npm run build
npm run build:mac:local
```

客户端启动 API 的主要路径：

```text
/Users/Yivxer/Projects/Archer/terminal/api/fastapi_app.py
```

所以后续如果客户端连不上，优先检查：

1. `client/desktop/src/main/apiProcess.ts` 和 `client/desktop/src/main/index.ts` 是否正确启动 API 进程。
2. `/ready`、`/status`、`/config/doctor` 是否正常。
3. token 文件和 Electron 传给 API 的 token 是否一致。
4. `archer.toml` 的 `active_profile`、模型 profile、provider/base URL 是否正常。

真实安装验证：

```bash
cd /Users/Yivxer/Projects/Archer
VERIFY_OPEN_APP=1 bash scripts/verify_desktop_live.sh
```

汇报 Desktop 状态时要明确区分：

```text
dev verified     # dev 环境验证
build verified   # npm run build 通过
packaged         # 已打包出 app/dmg
installed        # 已替换 /Applications/Archer.app 并通过 installed smoke
```

## Runtime Foundation 稳定性层

这层是 2026-06 稳定性优化的核心，不属于单一端口，而是终端、Desktop API、客户端共同依赖的地基。

当前主链路：

```text
ChatPage
  -> localArcher.ts
  -> FastAPI /chat/stream
  -> terminal/api/_tools.py
  -> core/llm.py + core/tool_runtime.py + core/api_tool_service.py
  -> skills/ workflows/ integrations/
```

核心职责：

1. **Readiness 和恢复**
   `/health`、`/ready`、`/status`、API restart、token 校验、429 防误伤。

2. **技能安全包装**
   `core/tool_runtime.py` 是技能执行安全边界。技能异常应返回结构化失败，而不是拖垮聊天流。

3. **权限分级和审计**
   `core/permission_levels.py` 负责 `read-only`、`write-local`、`write-vault`、`deploy-remote` 分类。审批与审计记录要带 `permissionLevel`。

4. **工具幂等**
   `core/api_tool_service.py`、`obsidian_write`、`hugo_blog` 等副作用工具需要 fingerprint，避免重复点击、重复请求造成双写或双部署。

5. **Trace 和故障诊断**
   客户端聚合 `runtime.context`、`status.event`、`tool.request/result`、`failure.hint`、`job.event`。相关逻辑在 `client/desktop/src/agent/traceDiagnostics.ts` 和 EventLog 适配层。

6. **僵尸任务清理**
   后台 job 的 `running`、`waiting_approval`、`queued` 状态需要 stale/cancel 规则，避免无限 loading 或 worker 结束后覆盖 cancelled 状态。

7. **配置诊断和缓存策略**
   `core/doctor.py` 和 `core/cache_policy.py` 负责 doctor 摘要、缓存 TTL 规则、冷启动验收信息。

## Part 9 稳定性框架防塌层

Part 9 在 Runtime Foundation 之上补齐六层防塌架，让 Archer 从「偶发救火」变成「可观测、可量化、可回放」。详细设计见 `docs/stability-framework.md`（Obsidian 副本：`Archer 稳定性框架.md`），工作计划见 `Archer 稳定性框架·工作计划.md`。

### L0 自我感知 + §三-B 后端关键路径

```text
core/active_context.py            # active_context schema 读写 + 崩溃检测（SIGTERM + FastAPI shutdown 钩子）
core/tool_runtime.py              # B1.1 tool→summary 闭环兜底（工具执行后模型无回复时自动生成摘要）
core/permission_levels.py         # B3.1 P0 skill 统一执行包装（hugo_blog/obsidian_write/file_ops 异常结构化失败）
core/desktop_tool_router.py       # B5.1 simple path / full path 分叉（轻量意图不走完整 tool_loop）
core/provider_breaker.py          # B6.1 provider 熔断（连续失败 N 次切回 default profile）
terminal/api/fastapi_app.py       # L0.3 startup/shutdown 钩子 + /active-context 路由
terminal/api/_tools.py            # B1.1 + B5.1 改
docs/api-contract.md              # B.doc failure.hint.keyword 完整枚举
```

### L1 连接状态机

```text
client/desktop/src/renderer/src/lib/connectionState.ts        # 6 状态枚举 + 17 条转移规则
client/desktop/src/renderer/src/lib/useConnectionState.ts     # 5s 心跳 + 30s doctor + 1s tick + transitions 持久化
client/desktop/src/renderer/src/components/ConnectionBadge.tsx # 6 状态视觉规范
client/desktop/src/main/apiProcess.ts                         # L1.2.3 brain status → 6 状态映射
```

### L2 对话事件契约

```text
client/desktop/src/renderer/src/lib/chatEventDispatcher.ts     # 输入事件 → UI action，覆盖 10 种 failure 类型
docs/api-contract.md                                          # L2.1 SSE 事件完整类型清单 + 顺序契约
```

### L3 领域状态统一源

```text
client/desktop/src/renderer/src/lib/externalStore.ts          # 外部 store 模式 + useSyncExternalStore 基座
client/desktop/src/renderer/src/lib/memoryStore.ts            # 记忆 store
client/desktop/src/renderer/src/lib/soulStore.ts              # 灵魂档案 store
client/desktop/src/renderer/src/lib/sessionStore.ts           # 会话 store
client/desktop/src/renderer/src/lib/jobStore.ts               # 后台任务 store
client/desktop/src/renderer/src/lib/initiativeStore.ts        # 主动消息 shadow store（只读，Part 8 边界）
client/desktop/src/renderer/src/lib/threadStore.ts            # ConversationThread 连续性契约
client/desktop/src/renderer/src/lib/storeEventBus.ts          # 10 事件类型 + 错误隔离
client/desktop/src/renderer/src/lib/storeSync.ts              # shadow truth 同步（syncStoresFromAdapter）
```

### L4 交互原语库

```text
client/desktop/src/renderer/src/components/ConfirmationCard.tsx  # 工作意图确认卡
client/desktop/src/renderer/src/components/WorkReceipt.tsx        # 工作完成回执
client/desktop/src/renderer/src/components/TracePanel.tsx         # 诊断信息展开面板
client/desktop/src/renderer/src/components/ErrorRecovery.tsx      # 错误恢复（10 种 failure 类型）
client/desktop/src/renderer/src/components/PermissionPrompt.tsx   # 4 级权限提示
client/desktop/src/renderer/src/components/AttachmentUpload.tsx   # 附件后台上传 + 状态展示
client/desktop/src/renderer/src/components/EmptyState.tsx         # 统一空状态文案
client/desktop/src/renderer/src/components/LoadingState.tsx       # 统一加载状态文案
docs/ui-primitives.md                                            # 8 原语完整 props 签名 + 视觉规范
```

### L5 旅程 Smoke 套件 + Q1 量化指标

```text
scripts/journey_smoke.sh                # L5.2 journey runner（--all / --case / --list）
scripts/replay_trace.py                 # L5.11 trace 顺序契约回放（L2 顺序检查）
scripts/collect_metrics.py              # Q1 量化指标采集（failure.hint 计数 + dead→ready 恢复耗时）
client/desktop/src/renderer/src/lib/connectionLog.ts  # Q1 transitions localStorage 持久化
```

### 当前 P9 进度

- ✅ 阶段 0-5 完成（baseline + L0/§三-B + L1 + L2 + L3 + L4），tag `part9-L4-done`（commit `36ef256`）
- ✅ 阶段 6 可自动部分（L5.1 / L5.2 / L5.11）+ Journey 1-7 基础验证 + 阶段 7 Q1 量化采集
- ✅ 2026-07-10 阶段性收口：L5.12 口径调整为趋势报警（不再要求连续 7 天 8/8），Q2-Q4 转为持续观察，无硬性未完成项

## Part 10 架构治理

Part 10 在 Runtime Foundation + Part 9 稳定性框架之上，把 god file 拆分、domain 模块化、facade 边界守门、安全敏感函数测试补齐、可观测性 trace 绑定收口。详细工作计划见 `docs/superpowers/plans/2026-07-1[2-6]-part10-*.md`，成长计划见 Obsidian `Archer 成长计划.md` Part 10 节。

### Wave 1：god file 拆分（2026-07-12 ~ 07-13）

- `_tools.py` 从 3368 行拆出 `api_tool_helpers.py` / `hugo_workflow.py` / `desktop_tool_execution.py` 三个 helper 模块，自身降到 756 行 facade
- `_routes.py` 从 3075 行（实际工作版本 913 行）拆出 `session_routes.py` / `job_routes.py` / `memory_routes.py` / `profile_routes.py` / `initiative_routes.py` / `tool_approval_routes.py`，自身降到 593 行 facade

### Wave 2：六项 authority 迁移（2026-07-13 ~ 07-16）

- approval / job / session / profile / skill / taskRoute 六个 domain 的实现 authority 从 `_routes.py` / `_tools.py` 迁移到对应 domain 模块
- `_routes.py` / `_tools.py` 通过 `from X import Y as _Y` 形式 re-export 历史私有名，保持 `archer_api.py` / 测试 / 桌面端的导入路径不变
- Skill System 收口为 Python-only：删除 `core/ts_skill_bridge.py` 和 `client/desktop/src/agent/skills/localSkillBridge.ts`，43 个 Python skill / 0 个 TS skill

### Wave 3：后置能力（2026-07-16）

- Durable Outbox：tool approval 的持久化 outbox，避免 LLM 幻觉"已部署"
- `archer.toml` v1 schema 校验
- MCP config v2
- Skill Manifest（manifest 强制 `name/version/risk/auto_trigger/permissions/inputs/outputs`）
- performanceEvent 协议
- contractVersion 协商
- Evals 框架评估

### Wave 4：收尾审查与债务收口（2026-07-17）

- **P0 并发与边界债**：`session_routes.append_session` 并发漏洞修补（per-session-id `threading.Lock`）；`_routes.py` god file 阈值超标（抽 9 个 tool approval 函数到 `tool_approval_routes.py`，913→593 行）；17 个死 import 清理
- **P1 测试与可观测性补强**：`taskRouter.ts` 死代码删除；`api_tool_helpers.py` 22 个直接单元测试（`tests/test_api_tool_helpers.py`）；`session_routes` facade 边界测试；后台 job trace_id 绑定 structlog（`job_routes.py` 的 `_run_job` / `_run_job_chat_with_tools`）
- **P2 文档校正**：`docs/refactor/audit-report.md` Skill System Boundary 节更新
- **Wave 4 后置修补**：5 个 job trace_id 绑定/清理 + session append 并发压力测试（`tests/test_job_trace_and_session_concurrency.py`）；抽 `job_enrichment.py` 让 `job_routes.py` 从 896 降到 824 行；收紧 `GOD_FILE_LINE_BASELINE`（`_tools.py` 3368→840、`_routes.py` 3075→660，新增 `job_routes.py` 880）

### 守门测试

```text
tests/test_architecture_boundaries.py  # facade 边界 + god file 行数 + 模块依赖禁令 + skill system 边界
tests/test_api_tool_helpers.py          # 11 个安全敏感 helper 直接单元测试
tests/test_job_trace_and_session_concurrency.py  # job trace_id 绑定/清理 + session append 并发压力
client/desktop/src/agent/__tests__/pythonSkillAuthority.test.ts  # 桌面端 skill 加载只走 Python
```

## 真实工作流地图

当前高频工作不再依赖模型自然语言“猜执行”，而是收束到确认卡、工具执行、完成回执、Trace 诊断四段。

```text
用户请求
  -> /chat/stream 识别工作意图
  -> tool.request 确认卡（workIntent）
  -> /tool-approvals 执行技能
  -> ToolResult / approval.result（workReceipt）
  -> ChatPage 显示回执，Trace 面板保留诊断事件
```

### Hugo / 枫弋札记

```text
发布：
源稿/附件/路径
  -> _parse_markdown_for_hugo
  -> 确认 titleSource（frontmatter title / H1 / filename）
  -> hugo_blog action=publish
  -> 写入或复用 content/posts
  -> build/deploy
  -> HTTP 200 验证
  -> workReceipt

删除：
标题/slug/filename/URL
  -> 匹配 content/posts 候选
  -> 候选唯一才生成确认卡
  -> hugo_blog action=delete_and_deploy
  -> 移入 .archer-trash/posts
  -> build/deploy
  -> 原 URL HTTP 404 验证
  -> workReceipt
```

设计约束：

1. 发布、删除、重新部署都属于 `deploy-remote`，默认必须确认。
2. 标题必须来自源稿 frontmatter、H1 或文件名，禁止模型自拟标题覆盖源稿。
3. 同 slug 同内容复用，同 slug 不同内容拒绝覆盖。
4. 删除不再用“设为草稿”冒充删除；必须移出 `content/posts` 并验证线上 404。

### Obsidian 写入

```text
用户请求写入 Vault
  -> 生成 obsidian_write tool.request
  -> workIntent 显示目标路径、mode、原文件行数、写前校验
  -> 用户确认
  -> obsidian_write run_structured
  -> 指纹/mtime/size 校验
  -> 写入或拒绝
  -> workReceipt
```

设计约束：

1. Vault 写入属于 `write-vault`，默认必须确认。
2. 覆盖、prepend、section 等破坏性模式必须带预览时的文件状态。
3. 长笔记写入前保留备份路径；append 回滚说明为手动删除新增段落。

### 空回复诊断

聊天流结束前必须区分：

| keyword | 含义 |
|---|---|
| `model_empty_response` | provider 请求结束，但模型没有返回文本 |
| `tool_executed_no_summary` | 工具事件已产生，但模型没有返回总结 |
| `model_stream_timeout` | 模型流式响应超时 |
| `provider_connection_failed` | provider/API 连接失败 |
| `chat_busy` | 上一轮仍在处理 |
| `context_trimmed` | 长上下文被裁剪 |

前端收到上述情况时，不再只显示“模型无回复”，而是显示简短原因，并保留 Trace 入口。

## 网页端状态

网页端现在已经并入 Archer 总目录：

```text
/Users/Yivxer/Projects/Archer/web/
```

主要文件：

```text
web/public/index.html       # 官网首页
web/public/archer.html      # Archer 网页入口原型：Soul 建档 + 首次回应
web/public/soul.html        # Soul 模型说明页
web/public/login.html       # Magic Link 登录页
web/public/auth.html        # 登录回调页
web/public/privacy.html     # 隐私政策
web/public/terms.html       # 用户协议
web/public/fonts/           # 字体资源
web/deploy.sh               # 静态站部署脚本
web/README.md               # 网页端维护说明
web/.impeccable.md          # 网页端设计上下文
```

部署命令：

```bash
cd /Users/Yivxer/Projects/Archer/web
./deploy.sh
```

部署脚本用自身位置计算 `public/`，所以现在移动到 `web/` 后仍然有效：

```bash
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_DIR="$ROOT_DIR/public"
```

线上位置仍然是：

```text
https://www.yivxer.com
/var/www/archer/
ssh alias: archer
```

## 共享能力层

这些目录不属于某一个端口，而是终端和客户端共享的核心能力。网页端目前主要是静态站，不直接调用这些 Python 模块。

```text
core/         # LLM、上下文、tool_runtime、权限、幂等、缓存、doctor、模型 profile 等
memory/       # SQLite 记忆、pending memories、项目、任务、反馈、主题、向量检索等
knowledge/    # Vault focus sensor、mtime cache、知识上下文辅助
integrations/ # Obsidian 等外部资料源/应用集成
skills/       # 工具技能：shell、文件、网页、Obsidian、Hugo、图片、文档、GitHub 等
workflows/    # 项目简报、URL 阅读笔记、语音日记、周报等复用流程
modes/        # coach / mirror / critic / operator 模式提示词
templates/    # SOUL / MEMORY / COVENANT / PRESENCE / archer.toml 模板
tests/        # Python 测试；Desktop 测试在 client/desktop/src/**/__tests__
```

## 修改时看哪里

| 想改什么 | 优先看哪里 |
|---|---|
| 终端命令、REPL 行为 | `terminal/archer.py` |
| Desktop API 路由和返回值 | `terminal/api/_routes.py`（facade）、对应 domain 模块（`session_routes.py` / `job_routes.py` / `memory_routes.py` / `profile_routes.py` / `initiative_routes.py` / `tool_approval_routes.py`） |
| 聊天流、模型调用、工具事件 | `terminal/api/_tools.py`（facade）、`api_tool_helpers.py` / `hugo_workflow.py` / `desktop_tool_execution.py`、`core/llm.py`、`client/desktop/src/agent/` |
| 后台 job lifecycle / trace_id | `terminal/api/job_routes.py`、`terminal/api/job_enrichment.py` |
| session 并发写入 | `terminal/api/session_routes.py`（per-session-id 锁） |
| 桌面窗口、自动启动 API | `client/desktop/src/main/index.ts`、`client/desktop/src/main/apiProcess.ts` |
| 桌面 UI 页面 | `client/desktop/src/renderer/src/` |
| 模型切换和 profile | `terminal/api/profile_routes.py`、`core/model_profiles.py`、`client/desktop/src/renderer/src/pages/ChatPage.tsx` |
| 工具权限、审批、审计、幂等 | `core/permission_levels.py`、`core/api_tool_service.py`、`terminal/api/_config.py`、`terminal/api/tool_approval_routes.py`、`skills/obsidian_write.py`、`skills/hugo_blog.py` |
| Trace 诊断面板 | `client/desktop/src/agent/traceDiagnostics.ts`、`client/desktop/src/renderer/src/pages/SettingsPage.tsx`、`client/desktop/src/renderer/src/pages/ChatPage.tsx` |
| 后台任务 stale/cancel | `terminal/api/job_routes.py`、`client/desktop/src/agent/`、`client/desktop/src/renderer/src/pages/TasksPage.tsx` |
| 官网首页和网页入口 | `web/public/index.html`、`web/public/archer.html` |
| 部署官网 | `web/deploy.sh` |
| 记忆数据库结构 | `memory/store.py` |
| 记忆检索 | `memory/retrieve.py`、`memory/vector_store.py` |
| 技能加载 | `skills/loader.py`、`skills/*.py`（43 个 Python skill，无 TS skill） |
| 上下文注入 | `core/context.py` |
| 配置路径 | `archer.toml`、`core/paths.py` |
| Desktop installed smoke | `scripts/verify_desktop_live.sh`、`client/desktop/scripts/install-local-mac.sh` |
| P9 L0 自我感知 / 崩溃检测 | `core/active_context.py`、`terminal/api/fastapi_app.py`（startup/shutdown 钩子 + /active-context） |
| P9 §三-B 后端关键路径 | `core/tool_runtime.py`、`core/permission_levels.py`、`core/desktop_tool_router.py`、`core/provider_breaker.py` |
| P9 L1 连接状态机 | `client/desktop/src/renderer/src/lib/connectionState.ts`、`useConnectionState.ts`、`components/ConnectionBadge.tsx` |
| P9 L2 对话事件契约 / failure 类型 | `client/desktop/src/renderer/src/lib/chatEventDispatcher.ts`、`docs/api-contract.md`（failure.hint 枚举） |
| P9 L3 领域状态统一源 | `client/desktop/src/renderer/src/lib/`（memoryStore/soulStore/sessionStore/jobStore/initiativeStore/threadStore/storeEventBus/storeSync） |
| P9 L4 交互原语 | `client/desktop/src/renderer/src/components/`（8 原语 + 专属 .css）、`docs/ui-primitives.md` |
| P9 L5 旅程 Smoke / trace 回放 | `scripts/journey_smoke.sh`、`scripts/replay_trace.py` |
| P9 Q1 量化指标采集 | `scripts/collect_metrics.py`、`client/desktop/src/renderer/src/lib/connectionLog.ts` |
| P10 facade 边界守门 | `tests/test_architecture_boundaries.py`（6 个 `test_*_live_behind_*_facade` + god file 基线） |
| P10 安全敏感 helper 测试 | `tests/test_api_tool_helpers.py` |
| P10 job trace / session 并发 | `tests/test_job_trace_and_session_concurrency.py` |
| P10 trace_id 绑定 | `infrastructure/observability.py`（`bind_trace_context` / `clear_trace_context`）、`terminal/api/job_routes.py` |

## 当前还可以优化的方向

1. **工作树分组收口**
   按 `docs/refactor/runtime-foundation-worktree-groups-2026-06-30.md` 把 Runtime Foundation、模型切换、Trace、权限、Part 8 shadow 等改动分组提交，避免后续排查时一团乱。

2. **单模型稳定窗口**
   七月初先固定 DeepSeek/lite 跑几天真实使用，不急着反复切 Kimi/GLM。等 DeepSeek 基线稳定后，再把多模型切换作为独立压力测试。

3. **真实 provider/model 可见化**
   聊天请求可以在 Trace 里展示实际使用的 provider、model、base URL 摘要，但不展示 key。这样能区分"前端显示切换了"和"后端真的切换了"。

4. **博客发布链路单独验收**
   博客发布不要混在通用聊天稳定性里一起测。建议单独建立 Hugo/Obsidian 发布 smoke：读取源稿、确认标题、生成 slug、写入、构建、部署、HTTP 验证、失败回滚提示。

5. **长上下文与工具调用分离**
   长对话里工具指令要从普通聊天内容里更明确地抽出来，避免"回答旧问题""执行错文章""标题被模型自己改写"这类问题复发。

6. **权限提示更贴近用户动作**
   现在已经有权限等级，下一步可以把提示文案从"读取文件夹权限"改成"本次要读取/写入哪个具体路径、属于哪个权限等级、为什么需要"。

7. **旧文档链接清理**
   README、旧 handoff、旧架构说明里如果仍指向 `terminal/archer_api.py` 或旧 Desktop 路径，后续应统一改到这份结构文档，减少接力误判。

8. **Part 8 thread_resume 真实投递验收（待用户 opt-in）**
   Part 10 Wave 3 gate 因 `insufficient_feedback` 关闭，依赖用户主动 opt-in 后积累反馈样本再验收。

9. **tool domain 进一步合并（架构演进，非修补范畴）**
   `tool_approval_routes.py` 与 `tool_stage.py` 为同域两个模块，未来可考虑合并为单一 tool domain 模块。

## 旧路径对照

| 旧路径 | 新路径 |
|---|---|
| `/Users/Yivxer/Projects/archer-site/` | `/Users/Yivxer/Projects/Archer/web/` |
| `/Users/Yivxer/Projects/archer-site/public/` | `/Users/Yivxer/Projects/Archer/web/public/` |
| `/Users/Yivxer/Projects/archer-site/deploy.sh` | `/Users/Yivxer/Projects/Archer/web/deploy.sh` |
| `/Users/Yivxer/Projects/Archer/desktop/` | `/Users/Yivxer/Projects/Archer/client/desktop/` |
| `/Users/Yivxer/Projects/Archer/desktop/release/` | `/Users/Yivxer/Projects/Archer/client/desktop/release/` |
| `/Users/Yivxer/Projects/Archer/desktop/resources/` | `/Users/Yivxer/Projects/Archer/client/desktop/resources/` |
| `/Users/Yivxer/Projects/Archer/archer.py` | `/Users/Yivxer/Projects/Archer/terminal/archer.py`（根目录保留兼容入口） |
| `/Users/Yivxer/Projects/Archer/archer_api.py` | `/Users/Yivxer/Projects/Archer/terminal/archer_api.py`（根目录保留兼容入口） |

## 可清理与不可清理

可以再生成，空间大但删除后需要重装/重构建：

```text
.venv/                         # Python 环境
client/desktop/node_modules/    # Node 依赖
client/desktop/out/             # 客户端构建产物
client/desktop/release/         # DMG 安装包
```

不要随便删除：

```text
archer.toml
COVENANT.md
PRESENCE.md
memory/archer.db
memory/sessions/
.artifacts/
web/public/
client/desktop/resources/
```

## 推荐后续整理规则

1. 新说明文档优先放 `docs/`，不要再散落到根目录。
2. 稳定性地基类改动优先归入 Runtime Foundation，不和新技能扩展混在一起。
3. 运行时人格/边界文件只保留根目录 `COVENANT.md`、`PRESENCE.md`，模板放 `templates/`。
4. 终端相关改动写到 `terminal/`、`core/`、`memory/`、`skills/`。
5. 客户端相关改动写到 `client/desktop/`。
6. 网页端相关改动写到 `web/`。
7. Obsidian 里的历史日志可以保留，但以后以这份结构说明作为当前路径基准。

---

## 数字 Baseline（2026-07-17 Part 10 Wave 4 收尾后更新）

> Source-of-truth 口径：以本节为准，其他文档引用时需对齐此处。

| 维度 | 数值 | 统计方式 |
|---|---|---|
| Python 测试文件 | 150 | `ls tests/test_*.py \| wc -l` |
| Python 测试用例 | 1682 | `pytest --collect-only` 全量（含 Wave 4 新增 5 个） |
| TS 测试文件 | 37 | 28 `.test.ts` + 9 `.test.tsx` |
| TS 测试用例 | 538 | `npm test -- --run` |
| 技能数 | 43 | `ls skills/*.py \| wc -l`（Python-only，无 TS skill） |
| 对话模式 | 12 | `ls modes/*.md \| wc -l` |
| Memory SQLite | 1 | `memory/archer.db` |

**god file 行数基线**（`tests/test_architecture_boundaries.py::GOD_FILE_LINE_BASELINE`）：

| 文件 | 基线 | 实际（2026-07-17） |
|---|---:|---:|
| `terminal/api/_tools.py` | 840 | 756 |
| `terminal/api/_routes.py` | 660 | 593 |
| `terminal/api/job_routes.py` | 880 | 824 |
| `memory/store.py` | 1609 | 1369 |
| `client/desktop/src/renderer/src/pages/ChatPage.tsx` | 2361 | 2343 |
| `client/desktop/src/renderer/src/adapters/localArcher.ts` | 1132 | 1132 |

**PR CI 子集**（必绿）：7 个 Python 测试文件 + TS 全量单元测试 + tsc 类型检查
- Python 子集：`tests/test_fastapi_routes.py` / `tests/test_active_context.py` / `tests/test_provider_breaker.py` / `tests/test_simple_path_fork.py` / `tests/test_p0_skill_wrapping.py` / `tests/test_thread_store.py` / `tests/test_desktop_api.py::TestDesktopSessions`
- 当前子集用例数：95（约占总数 5.6%）

**Nightly CI**：`scripts/journey_smoke.sh --all` 8 条旅程（journey 0 skip 待 `archer.py --prompt`）+ `scripts/collect_metrics.py` 指标采集

