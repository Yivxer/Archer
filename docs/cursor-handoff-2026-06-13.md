# Cursor Handoff - Archer B18 收口

日期：2026-06-13

这份文档给 Cursor 继续接手用。当前工作树包含多轮混合改动，不要直接全量提交；先按下面的边界继续。

## 已完成并记录到 Obsidian

Obsidian 计划：
`/Users/Yivxer/Library/Mobile Documents/iCloud~md~obsidian/Documents/个人知识管理系统/50计划清单📌/Archer/Archer成长计划.md`

已完成：

1. P4 Orchestrator 主体收口
   - `plan.event` 可见计划卡
   - runtime session id 不再写死为 `desktop-session`
   - 空首页不会隐藏 runtime plan/job/tool activity
   - `project_update` 可生成 pending 项目记忆草稿
   - `/jobs/{id}/spawn` 契约级测试已补

2. B18 Python 环境状态复核
   - `.venv/bin/python --version`：Python 3.14.3
   - `.venv/bin/python -m pytest --version`：pytest 9.0.3
   - 极小单测通过：`tests/test_memory_schema.py::test_add_pending_carries_confidence`
   - 旧的“Python 环境被系统策略阻止”记录已标为过期

3. B18 副作用工具安全验收
   - 修复否定式副作用意图：
     - “不要搜索资料”不保留 `web_search` / `web_fetch`
     - “不要保存到 /tmp/xxx.md”不保留 `file_ops`
   - 保留正向意图：
     - “搜索最新资料”仍保留 `web_search`
     - “保存到 /tmp/xxx.md”仍保留 `file_ops`
   - 相关文件：
     - `core/desktop_tool_router.py`
     - `tests/test_desktop_api.py`
   - 验证：
     - `.venv/bin/python -m pytest -q tests/test_desktop_api.py::TestApiSkillRouting tests/test_hugo_blog_publish.py`
     - `.venv/bin/python -m pytest -q tests/test_desktop_api.py`

4. B18 低成本 smoke 与 Desktop 运行态说明
   - `AGENTS.md` 已新增：
     - Desktop/API 低成本 smoke 顺序
     - Desktop 运行态报告口径：`dev verified` / `build verified` / `packaged` / `installed`
   - 注意：不要把 `npm run build` 说成已安装。

5. B18 子代理产品入口补齐
   - TasksPage 父任务详情已展示 `children` 摘要
   - TasksPage 父任务详情已新增手动「拆分子任务」入口
   - 当前只支持手动创建 1 个 child job：
     - 标题
     - 类型：`analysis` / `review` / `work`
     - prompt
     - 是否立即开始
   - 提交后调用 `spawnChildJobs(parentJobId, [spec])` 并刷新任务列表
   - 相关文件：
     - `client/desktop/src/renderer/src/pages/TasksPage.tsx`
     - `client/desktop/src/renderer/src/styles/pages.css`
     - `tests/test_tasks_page_child_jobs.py`
   - 验证：
     - `.venv/bin/python -m pytest -q tests/test_tasks_page_child_jobs.py`
     - `cd client/desktop && npm run build`
   - 当前状态：`build verified`，未打包，未安装到 `/Applications`

## 当前不要重复做

- 不要重新设计 P4 Orchestrator。
- 不要把子代理入口扩成自动 LLM 拆分。
- 不要做真实长模型/API 流式验证。
- 不要把 build 结果说成 installed。
- 不要直接全量提交当前工作树；当前 dirty diff 混有多轮改动。

## 建议 Cursor 下一步

### 优先路线 A：TS Skill 迁移路线规划（推荐）

目标：只规划，不实现大迁移。

输出建议：

1. 列出现有 Python 技能中适合迁移到 TS 的候选：
   - `file_ops`
   - `web_search` / `web_fetch`
   - `hugo_blog`
   - 其他低风险本地技能
2. 按迁移优先级排序：
   - 风险
   - 依赖复杂度
   - 是否需要审批
   - 是否能用纯 Node 实现
   - 对 Desktop 体验收益
3. 给出下一批只迁一个技能的建议。
4. 更新 Obsidian 成长计划中的 “TS Skill 迁移路线”。

建议结论倾向：

- 第一优先：`file_ops` 的只读/低风险子集，或独立 `file_read` / `file_search`
- 不建议先迁：`hugo_blog`，因为部署、路径、站点验证、副作用审批复杂
- `web_search` 取决于现在 Python skill 的外部依赖，不要盲迁

### 备选路线 B：Git 状态收口前分类

目标：只分类，不提交。

低成本命令：

```bash
git status --short
git diff --stat
git diff --name-status
```

输出分类：

- source runtime
- tests
- docs / rules
- generated artifacts
- runtime data
- unknown / needs user decision

不要做：

- 不要 `git add .`
- 不要删除 untracked
- 不要改功能
- 不要 commit

### 备选路线 C：子代理入口后续增强

只有用户明确要继续子代理产品化时再做。

小步顺序：

1. 多子任务表单
2. 从 Plan 卡生成 child job 草稿
3. 父任务汇总 child job 结果
4. 端到端：Plan 卡 -> child jobs -> 执行 -> 父任务汇总

不要一步到位。

## 建议验证策略

遵守 `AGENTS.md`：

1. 先跑最小相关测试
2. 共享面变化再跑更宽测试
3. Desktop TS/renderer/main 改动才跑：

```bash
cd client/desktop && npm run build
```

4. 真实 Electron/API smoke 只在 UI/runtime 行为需要时做
5. 真实模型/API 请求必须是一句话级别，并先说明可能消耗额度

## 当前剩余未完成项

Obsidian B18 仍未完成：

- Git 状态收口
- 剩余旧文件/测试草稿分类
- TS Skill 执行桥接线 + 按路线逐技能迁移（路线规划已于 2026-06-13 写入 Obsidian「B18 TS Skill 迁移路线」）

P3 长期预留项仍不建议近期做：

- Zustand
- React Router
- FastAPI
- PWA
- 账号体系

