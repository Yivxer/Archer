# Archer BACKLOG

> 只追加，不删除。已处理的条目打 [x] 并标注解决 Step。

---

## 安全 / 稳定

- [ ] `call_with_tools` 非流式调用期间无进度反馈（spinner 缺失）
- [x] 技能 `run()` 无 timeout，长时 shell/网络请求会卡死 REPL → **Step 1 完成**
- [x] 技能异常被 `str(result)` 吞掉，LLM 无法判断错误类型 → **Step 1 完成**
- [x] 技能调用结果无长度上限，大文件/长网页直接进入 messages → **Step 1/4 完成**
- [x] `installer.py` 从 URL 安装技能无隔离、无代码审查 → **Step 2 完成**
- [x] `shell` 技能无 denylist，`rm -rf ~` 等危险命令可直接执行 → **Step 2 完成**
- [x] `file_ops write` 写入路径无限制（现需用户确认）→ **Step 2 完成**

## 记忆系统

- [x] `_PENDING_MEMORIES` 是内存全局变量，进程崩溃后丢失 → **Step 3 完成**
- [x] 每 3 轮同步提炼阻塞 REPL，打断对话流 → **Step 8 完成**（改为事件触发后台线程）
- [x] `retrieve.py` for_context 注入 reflection 类型记忆 → **Step 6 完成**（过滤）
- [x] `retrieve.py` for_context 无过期检查 → **Step 6 完成**（valid_until 过滤）
- [x] 记忆相似度检测用字面 SequenceMatcher（无语义），误报率高 → **P2-F 完成**（sqlite-vec KNN）
- [ ] `memory/store.py search()`：FTS5 trigram 搜索 ≤2 字符时返回空列表但不抛异常，LIKE 降级失效 → 低优先级
- [x] `retrieve.py` for_context 用 LIMIT 硬截断，无相关性排序 → **P2-F 完成**（向量优先混合检索）

## 对话体验

- [x] `/reflect` 不进入 session history，无法追问复盘内容 → **Step 5 完成**
- [ ] `/mode` 切换不持久化到 toml，重启后恢复默认 → 低优先级
- [x] `archer.toml` 修改需重启才生效（config 在 llm.py 单例缓存）→ **P2-A 完成**（mtime 检测热加载）
- [x] 每次把 18 个技能全部暴露给模型，无路由过滤 → **P2-B 完成**（skill_router.py，纯聊天跳过全部 schema）

## 架构

- [ ] `ui/app.py` Textual TUI 代码已废弃但未清理 → 低优先级（可直接删除）

## P2 已完成（20260427）

- [x] **P2-A /listen 静默模态 + 配置热加载**：`/listen` 切换静默模态（仅记录不触发 LLM）；`archer.toml` mtime 检测，每轮检查热加载；git tag `step-11-listen-hotreload`（P2-A 在前序会话完成）
- [x] **P2-B 技能路由过滤**：`core/skill_router.py`，关键词 + URL/路径正则映射，纯聊天返回 `{}` 跳过全部 tool schema，省 ~3k tokens/轮；git tag `step-11-skill-router`
- [x] **P2-C /doctor 自检**：`core/doctor.py`，10 项健康检查（config/api/schema/pending/soul/obsidian/skills/risk/artifacts/sessions）；Level OK/INFO/WARN/ERROR；`/doctor --fix` 自动修复；git tag `step-12-doctor`
- [x] **P2-D 定时任务**：`core/scheduler.py`，间隔制调度（daily/weekly/monthly/Nh）；`scheduled_tasks` 表；启动执行到期任务；`/cron` 命令；git tag `step-13-scheduler`
- [x] **P2-E MCP Adapter**：`core/mcp.py`，MCPManager（daemon asyncio 线程 + AsyncExitStack）；工具命名 `{server}__{tool}`；`load_from_config` 读 `archer.toml [mcp]`；MCP skills 绕过 skill_router 始终暴露；pip install mcp 启用；git tag `step-14-mcp`
- [x] **P2-F 向量检索**：`memory/embedder.py`（paraphrase-multilingual-MiniLM-L12-v2，384维，懒加载）；`memory/vector_store.py`（sqlite-vec KNN，静默降级）；`memory/store.py` save 触发嵌入；`memory/retrieve.py` 混合检索（向量优先 + FTS5 补充）；`/memory reindex`；git tag `step-15-vector-search`

## P3 候选

- [ ] `call_with_tools` 非流式调用期间无进度反馈（spinner 缺失）
- [ ] `ui/app.py` Textual TUI 代码废弃未清理
- [ ] `/mode` 切换不持久化到 toml，重启后恢复默认
- [ ] `memory/store.py search()`：FTS5 ≤2 字符返回空且无降级提示

---

*最后更新：2026-04-27 · P2 全部完成（step-11 → step-15），259 个测试全绿*
