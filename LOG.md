# Archer 构建日志

> 格式：bullet，只写改了什么和为什么，最新在前。

---

## [Claude Code] 初衍 v1.2 稳定在场版（20260427）

设计文档：`初衍进化1.2-最终整合执行版.md`，git commit `2a33c1d`，339 个测试全绿（新增 57 个）。

**Phase 0 — 安全热修**
- `core/policy.py`：新增 `is_inside_vault(resolve+relative_to)`，替换原 `"obsidian" in path.lower()` 字符串匹配，修复路径遍历/字符串绕过漏洞；`score_shell_risk()` 实现 low/medium/high/critical 四级评分；shell DENY 范围收窄（仅 critical 命中），high 风险触发新增 `STRONG_CONFIRM` 决策；`sudo` 从 DENY 改为 STRONG_CONFIRM（`sudo rm` 仍 DENY）；新增高风险模式：osascript/launchctl/nohup/defaults write/pmset/crontab -r 等
- `core/doctor.py`：新增 `_check_path_safety()` 检查 vault_path 是否存在、是否可 resolve、是否含符号链接
- `tests/test_policy.py`：更新 `test_deny_sudo` → `test_deny_sudo_rm`，新增 `test_sudo_is_high_not_deny`、`test_shutdown_is_high_not_deny`、`test_chmod_recursive_is_high`
- `tests/test_v12_phase0_security.py`：新增 18 个专项测试（vault 路径判断 / shell 评分 / STRONG_CONFIRM / file_ops 归属）

**Phase 1 — 灵魂三层**
- 新建 `COVENANT.md`（根契约 v1.0，不接受自动 proposal，修改需 `/covenant propose` + 强确认）
- 新建 `PRESENCE.md`（在场方式 v1.0，只 suggest 不 smart update）
- `archer.toml`：新增 `[persona] covenant_path/presence_path`、`[persona.history] covenant_dir/presence_dir`、`[critique] weekly_enabled=false`、`[security] shell_risk_scoring=true`、`[mcp] schema_policy/recent_window_turns`
- `core/context.py` 全面重构：8 层注入顺序（Runtime Safety→COVENANT→PRESENCE→核心人格+mode→SOUL→MEMORY→活跃项目→DB Memories）；SOUL 从 Layer 1 常驻下沉到按 intent 按需注入（只在 decision/emotional/reflection 时注入，chat/task 不注入）；`is_heavy_query()` 升级为 `classify_query_intent()`（返回 intent/needs_memory/needs_soul 等字段，向后兼容）；关键词集合分为 decision/project/reflection/emotional/task 五类
- `archer.py`：新增 `_handle_covenant()`（view/history/propose）、`_handle_presence()`（view/edit/suggest/history，edit 前自动备份）、`_handle_critique()`（scan/list/view/dismiss/new）；主循环引入 `classify_query_intent()`，`intent` 字段传入 `build_messages()`
- `tests/test_v12_phase1_soul_layers.py`：21 个测试（意图分类/heavy 兼容/COVENANT-PRESENCE-SOUL 注入顺序）

**Phase 2 — 自我批评**
- 新建 `memory/critique.py`：`self_critiques` 表（含 evidence_json 必填、observation ≥30字约束）；`create_critique/list_critiques/get_critique/dismiss_critique/scan_critiques`；`try_create_from_user_signal()` 实现会话级限流（同 session 最多 1 条 / 24h 同类不重复）；所有接口通过 `_conn()` 动态引用 `store.DB_PATH`，支持测试 monkeypatch
- `memory/store.py`：`init_db()` 末尾调用 `init_critiques_table()`
- `weekly_self_critique` 默认关闭（`cfg["critique"]["weekly_enabled"]=false`）
- `scope=skill_router_hint` 仅建议展示，不写任何文件
- `tests/test_v12_phase2_critique.py`：8 个测试

**Phase 3 — 记忆质量**
- `memory/store.py`：`init_db()` 新增幂等 ALTER TABLE，为 memories/project_events/soul_proposals 补 `session_id TEXT` 列；`save()` 接受 `session_id` 参数；新增 `generate_session_id()`（YYYYMMDD-HHMMSS-uuid8 格式）；新增 `run_importance_decay()`（context/state 30天/todo/risk/project 60天 decay importance-1，最低 1，identity/decision/preference 不 decay）；`get_memories_for_detection()` 返回结果含 `session_id` 字段
- `memory/patterns.py`：themes 检测从"跨≥2个不同日期"升级为"跨≥2个 session_id + 尽量跨不同日期"；同日不同 session 时 strength 上限 0.65；兼容旧记忆（无 session_id 时降级到跨日期门控）
- `archer.py`：`run()` 启动时调用 `generate_session_id()` 初始化 `_current_session_id`
- `tests/test_v12_phase3_session_memory.py`：10 个测试

**Phase 4 — MCP 注入优化**
- `archer.py`：新增 `_MCP_CAPABILITY_KW` 关键词集合；新增 `_should_inject_mcp()`（recent/server_name/capability_keyword 三条件策略）；MCP 从"始终暴露"改为按需注入；新增 `_turn_counter` + `_mcp_last_used_turn` 追踪最近使用轮次

---

## [Claude Code] 架构重构 P4 — 上下文治理 + 质量约束（20260427）

- **Step 17 Context Builder 三层上下文**：`core/context.py` 全面重构；Layer 1（System，始终注入）= `_ARCHER_CORE` + 模式 prompt + SOUL.md；Layer 2（Working，heavy=True 时注入）= MEMORY.md + 活跃项目摘要（名称/描述/最近 3 条事件）；Layer 3（Memory）= DB 检索结果；新增 `is_heavy_query()`（输入 ≥40 字或含决策关键词）；`_load_soul/_load_memory` 改用 `is_file()` 防空路径报错；`archer.py` 每轮传入 `heavy`/`project`/`proj_evts`；git tag `step-17-context-builder`
- **Step 18 Pattern 质量约束**：`memory/patterns.py` 新增三重门控：名称 ≤12 字符、证据 ≥2 条、证据跨 ≥2 个不同日期（跨会话代理）；`store.get_memories_for_detection()` 补 `created_at` 字段供跨日期检查；git tag `step-18-pattern-quality`
- **测试**：新增 `tests/test_p4_context_patterns.py`（13 个测试），更新 `test_patterns.py`（跨日期测试数据），280 个测试全绿

---

## [Claude Code] 架构重构 P3 — 体验修补（20260427）

- **Step 16 call_with_tools spinner**：`_run_with_tools()` 中 `call_with_tools` 非流式调用期间加 `Live(Spinner("arc"))` 弧形进度指示，transient 模式不残留；git tag `step-16-p3-fixes`
- **ui/app.py 清理**：删除 502 行废弃 Textual TUI 代码（`ui/` 目录整体移除）；`requirements.txt` 移除 `textual>=0.47.0`
- **/mode 持久化**：新增 `_persist_mode(mode)` 函数（regex 插入/替换 `[persona]` 段中 `current_mode` 字段）；`_handle_mode()` 切换成功后写入 `archer.toml`，重启后生效
- **FTS5 ≤2 字符降级**：`memory/store.py search()` 预检关键词长度，<3 字符直接走 LIKE 跳过 FTS5 trigram；`_memory_search()` 增加 UI 提示说明使用模糊匹配
- **测试**：新增 `tests/test_p3_fixes.py`，8 个测试（ui 清理验证、mode 持久化插入/替换、FTS5 短词/正常词、spinner 结构性导入验证），267 个全绿

---

## [Claude Code] 架构重构 P2 — 增强层（20260427）

- **P2-B 技能路由过滤**：新增 `core/skill_router.py`；关键词表（15 组）+ URL/路径正则，纯聊天 → `{}` 跳过全部 tool schema（省 ~3k tokens/轮）；MCP skills 绕过路由始终暴露；27 个测试；git tag `step-11-skill-router`
- **P2-C /doctor 自检系统**：新增 `core/doctor.py`；10 项检查函数（config/api/memory/pending/soul/obsidian/skills/artifacts/sessions/risk）；`Level` enum OK/INFO/WARN/ERROR；`CheckResult.fix_fn` 可选修复函数；`/doctor --fix` 自动执行所有修复；修复：`_artifacts.ARTIFACTS_DIR` 动态引用而非静态 import（允许测试 patch）；`_check_pending` 改用 `COUNT(*) FROM pending_memories`（无 status 列）；24 个测试；git tag `step-12-doctor`
- **P2-D 定时任务调度器**：新增 `core/scheduler.py`；`scheduled_tasks` 表（skill_name/label/interval_h/next_run_at/last_run_at/enabled）；`parse_interval()` 支持 daily/weekly/monthly/Nh；`run_due_tasks()` 在 REPL 启动时执行到期任务；`/cron` 命令（list/add/del/run）；25 个测试；git tag `step-13-scheduler`
- **P2-E MCP Adapter**：新增 `core/mcp.py`；`MCPManager`（daemon 线程 + `asyncio.new_event_loop()` + `AsyncExitStack`）；工具命名 `{server}__{tool}`（双下划线，避开 OpenAI 函数名限制）；`make_skill_modules()` 生成合成 skill 模块；`load_from_config(cfg)` 读 `archer.toml [mcp]`；pip install mcp 启用，未安装时返回 None；同步修复 `doctor.py` pending 查询 bug；24 个测试；git tag `step-14-mcp`
- **P2-F 向量检索全栈**：新增 `memory/embedder.py`（paraphrase-multilingual-MiniLM-L12-v2，384维，懒加载，`list(vec)` 兼容 numpy/mock）；新增 `memory/vector_store.py`（sqlite-vec KNN，`struct.pack` blob，DELETE+INSERT upsert，未安装时静默降级）；`memory/store.py` 新增 `_try_embed()`（save 后触发）、`get_by_ids()`（向量命中水合）、`delete()` 清理向量；`memory/retrieve.py` `_hybrid_search()`（向量优先 + FTS5 补充，去重）替换原 `search()` 调用；`archer.py` 启动 `init_vec_table()`、`/memory reindex` 命令；pip install sqlite-vec sentence-transformers 启用；17 个测试；git tag `step-15-vector-search`
- **测试覆盖**：16 个测试文件，259 个测试全绿

---

## [Claude Code] 架构重构 P1 — 灵魂成长层（20260427）

- **Step 6 Memory Schema 生命周期字段**：`memories` 表新增 `scope/confidence/last_used_at/valid_until` 列（幂等 ALTER TABLE）；`pending_memories` 新增 `confidence`；`save()` 接收新参数；自动提炼默认 `confidence=0.7`、手动写入 `0.9`；`update_last_used()` 追踪检索活跃度；`retrieve.py` 过滤 `reflection` 类型 + 过期记忆，检索后更新 `last_used_at`；git tag `step-6-memory-schema`
- **Step 7 patterns/themes 图结构**：`store.py` 新增 `themes` + `memory_links` 表；`memory/patterns.py`——`detect_and_save()`（LLM 从记忆库归纳主题，写库并建立关联）、`themes_summary`、`theme_detail`；`archer.py` 新增 `/themes` 命令（列表/detect/详情）；git tag `step-7-themes`
- **Step 8 事件触发提炼**：移除每 3 轮同步 `_auto_extract`（阻塞 REPL）；新增 `_bg_extract()`（daemon 线程，静默）+ `_wait_for_extract()`；每 6 轮触发后台提炼；`/exit` 和 Ctrl+C 等待后台线程完成后再执行一次全量同步提炼；`/reflect` 后追加 `_bg_extract`；新增 `/memory extract` 手动触发；git tag `step-8-event-extract`
- **Step 9 Project State**：`store.py` 新增 `projects` + `project_events` 表；完整 CRUD——`create/list/get/get_by_name/archive_project`、`log_project_event/get_project_events`；`archer.py` 新增 `_active_project_id` 会话全局、`/project` 命令（list/new/use/log/status/archive）；`/reflect` 完成后自动向活跃项目写入 `reflect` 事件；`/status` 显示活跃项目；git tag `step-9-project-state`
- **Step 10 SOUL 演化**：`store.py` 新增 `soul_proposals` 表；`memory/soul.py`——`should_propose()`（identity/decision ≥4 或 `obsidian_hint=SOUL.md`）、`propose_from_memories/propose_from_obsidian_hints`、`accept()`（追加到 SOUL.md 末尾，永不覆写）、`reject()`；`_auto_extract` 将 SOUL 相关内容路由到 proposal 而非直接展示；`/reflect` 的 `memory_candidates` 也触发检测；新增 `/soul` 命令（list/accept/reject/view）；`/status` 显示待审阅提议数；git tag `step-10-soul-evolution`
- **测试**：11 个测试文件，129 个测试，全绿；每步一个 git tag（step-6 → step-10）

---

## [Claude Code] 架构重构 P0 — 安全稳定底座（20260426）

- **Step 0 基线冻结**：新增 `tests/` 目录，9 个 smoke test，`BACKLOG.md`（15 条已知问题），`OVERVIEW.md`（供外部 AI 审查），git tag `step-0-baseline`
- **Step 1 Skill Runtime Wrapper**：新增 `core/tool_runtime.py`，统一技能调用入口；ThreadPoolExecutor timeout 防卡死；结构化 ToolResult（ok/error.type/retryable）；超长结果（>12k chars）存 artifact 不进 messages
- **Step 2 Policy Layer**：新增 `core/policy.py`，三级决策 DENY/CONFIRM/ALLOW；shell 黑名单 13 条（rm -rf ~/sudo/mkfs/fork bomb/curl|sh 等）；file_ops 写操作需确认；installer URL 安装改为下载→代码扫描→预览→输入 `INSTALL <name>` 全字确认；shell/file_ops/github_ops SKILL 元数据加 risk/timeout 字段
- **Step 3 pending 持久化**：`memory/store.py` 新增 `pending_memories` 表；移除 `archer.py` 全局列表 `_PENDING_MEMORIES`；accept/reject 改用真实 DB ID（不再是 1-based 序号）；进程崩溃后 pending 不丢失
- **Step 4 artifact 规范化**：`core/artifacts.py` 支持 tool_results/reflections/summaries 三类子目录；`dir_size()` + `fmt_size()`；`/status` 新增 pending 数量（黄色提示）和 artifact 占用显示
- **Step 5 /reflect 重写**：新增结构化 JSON 输出（summary/user_intent/decisions/open_questions/memory_candidates/next_actions）；结果进入 session.history（允许追问）；summary 存为 `type='reflection'` 记忆；完整 JSON 落盘 `.artifacts/reflections/`；新增 `_reflect_to_text()` 纯函数
- **测试**：5 个测试文件，66 个测试，全绿；每步一个 git tag（step-0 → step-5）

---

## [Claude Code] UI · token统计（20260426）

- `core/llm.py`：新增 `_last_usage` / `_session_tokens` 全局变量，`stream_options={"include_usage": True}` 捕获流式 token 用量，对外暴露 `get_last_usage()` / `get_session_tokens()`
- 修复重复累加：用 `call_usage` 局部变量暂存，generator 耗尽后才写入全局，避免多 chunk 叠加
- `core/input.py`：补全菜单取消灰色背景（`bg:default`），与终端底色统一
- `archer.py` 状态栏：输入框下方只显示模型名，token 统计（`↑输入 ↓输出 · session 累计`）移至 LLM 响应完成后显示
- 修复双空行：删除 `_run_with_tools` 里多余的 `console.print()`，`_stream()` 自带 `\n` 前缀已足够
